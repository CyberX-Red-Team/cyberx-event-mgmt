"""License management service.

Handles product CRUD, short-lived token generation/validation,
and per-product concurrency queue for controlled installation rollout.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.license import LicenseProduct, LicenseToken, LicenseSlot

logger = logging.getLogger(__name__)


def _hash_token(raw_token: str) -> str:
    """SHA-256 hash a raw token for storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class LicenseService:
    """Product CRUD, token generation/validation, and concurrency queue."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Product CRUD ────────────────────────────────────────────

    async def list_products(
        self, page: int = 1, page_size: int = 50
    ) -> tuple[list[LicenseProduct], int]:
        count_q = select(func.count(LicenseProduct.id))
        total = (await self.session.execute(count_q)).scalar() or 0

        offset = (page - 1) * page_size
        q = (
            select(LicenseProduct)
            .order_by(LicenseProduct.name)
            .offset(offset)
            .limit(page_size)
        )
        result = await self.session.execute(q)
        return list(result.scalars().all()), total

    async def get_product(self, product_id: int) -> Optional[LicenseProduct]:
        result = await self.session.execute(
            select(LicenseProduct).where(LicenseProduct.id == product_id)
        )
        return result.scalar_one_or_none()

    async def create_product(
        self,
        name: str,
        license_blob: str,
        description: str | None = None,
        max_concurrent: int = 2,
        slot_ttl: int = 7200,
        token_ttl: int = 7200,
        download_filename: str | None = None,
    ) -> LicenseProduct:
        product = LicenseProduct(
            name=name,
            description=description,
            license_blob=license_blob,
            max_concurrent=max_concurrent,
            slot_ttl=slot_ttl,
            token_ttl=token_ttl,
            download_filename=download_filename,
        )
        self.session.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        logger.info("Created license product: %s (id=%d)", name, product.id)
        return product

    async def update_product(self, product_id: int, **kwargs) -> Optional[LicenseProduct]:
        product = await self.get_product(product_id)
        if not product:
            return None

        for key, value in kwargs.items():
            if value is not None and hasattr(product, key):
                setattr(product, key, value)

        await self.session.commit()
        await self.session.refresh(product)
        logger.info("Updated license product: %s (id=%d)", product.name, product.id)
        return product

    async def delete_product(self, product_id: int) -> bool:
        product = await self.get_product(product_id)
        if not product:
            return False

        await self.session.delete(product)
        await self.session.commit()
        logger.info("Deleted license product: %s (id=%d)", product.name, product_id)
        return True

    # ── Token Management ────────────────────────────────────────

    async def generate_token(
        self, product_id: int, instance_id: int | None = None
    ) -> str:
        """Generate a short-lived, single-use token for a product.

        Returns the raw token (only time it's visible). The DB stores only the SHA-256 hash.
        """
        product = await self.get_product(product_id)
        if not product:
            raise ValueError(f"License product {product_id} not found")

        raw_token = secrets.token_urlsafe(48)
        token_hash = _hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=product.token_ttl)

        token = LicenseToken(
            token_hash=token_hash,
            product_id=product_id,
            instance_id=instance_id,
            expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.commit()

        logger.info(
            "Generated license token for product %s (expires %s)",
            product.name,
            expires_at.isoformat(),
        )
        return raw_token

    async def validate_and_consume_token(
        self, raw_token: str, client_ip: str
    ) -> Optional[str]:
        """Validate a token and mark it as consumed.

        Returns the product's license_blob if valid, None otherwise.
        """
        token_hash = _hash_token(raw_token)
        now = datetime.now(timezone.utc)

        result = await self.session.execute(
            select(LicenseToken)
            .where(LicenseToken.token_hash == token_hash)
        )
        token = result.scalar_one_or_none()

        if not token:
            logger.warning("License token validation failed: unknown token (ip=%s)", client_ip)
            return None

        if token.used:
            logger.warning("License token validation failed: already used (ip=%s)", client_ip)
            return None

        # Handle timezone-naive datetimes from DB
        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now > expires_at:
            logger.warning("License token validation failed: expired (ip=%s)", client_ip)
            return None

        # Load the product to get the blob
        product = await self.get_product(token.product_id)
        if not product or not product.is_active:
            logger.warning("License token validation failed: product inactive (ip=%s)", client_ip)
            return None

        # Mark as consumed
        token.used = True
        token.used_at = now
        token.used_by_ip = client_ip
        await self.session.commit()

        logger.info(
            "License token consumed for product %s (ip=%s)",
            product.name,
            client_ip,
        )
        return product.license_blob

    # ── Concurrency Queue ───────────────────────────────────────

    async def acquire_slot(
        self, product_id: int, hostname: str, ip: str
    ) -> dict:
        """Try to acquire an install slot for a product.

        Returns {"status": "granted", "slot_id": ...} or {"status": "wait", ...}.
        """
        product = await self.get_product(product_id)
        if not product:
            return {"status": "error", "message": f"Product {product_id} not found"}

        # Reap expired slots first
        await self._reap_expired_slots_for_product(product)

        # Count active slots for this product
        count_q = select(func.count(LicenseSlot.id)).where(
            and_(
                LicenseSlot.product_id == product_id,
                LicenseSlot.is_active == True,
            )
        )
        active_count = (await self.session.execute(count_q)).scalar() or 0

        if active_count < product.max_concurrent:
            slot_id = secrets.token_urlsafe(16)
            slot = LicenseSlot(
                slot_id=slot_id,
                product_id=product_id,
                hostname=hostname,
                ip_address=ip,
            )
            self.session.add(slot)
            await self.session.commit()

            logger.info(
                "Slot granted for product %s: %s (active=%d/%d)",
                product.name, slot_id, active_count + 1, product.max_concurrent,
            )
            return {
                "status": "granted",
                "slot_id": slot_id,
                "active": active_count + 1,
                "max": product.max_concurrent,
            }

        logger.info(
            "Slot denied for product %s: queue full (active=%d/%d)",
            product.name, active_count, product.max_concurrent,
        )
        return {
            "status": "wait",
            "active": active_count,
            "max": product.max_concurrent,
            "retry_after": 30,
        }

    async def release_slot(self, slot_id: str, result: str, elapsed: int) -> bool:
        """Release an install slot."""
        q = select(LicenseSlot).where(LicenseSlot.slot_id == slot_id)
        slot = (await self.session.execute(q)).scalar_one_or_none()

        if not slot:
            logger.warning("Attempted to release unknown slot: %s", slot_id)
            return False

        slot.is_active = False
        slot.released_at = datetime.now(timezone.utc)
        slot.result = result
        slot.elapsed_seconds = elapsed
        await self.session.commit()

        logger.info("Slot released: %s (result=%s, elapsed=%ds)", slot_id, result, elapsed)
        return True

    async def reap_expired_slots(self) -> int:
        """Clean up all expired slots across all products. Returns count reaped."""
        products_q = select(LicenseProduct).where(LicenseProduct.is_active == True)
        products = (await self.session.execute(products_q)).scalars().all()

        total_reaped = 0
        for product in products:
            total_reaped += await self._reap_expired_slots_for_product(product)

        if total_reaped > 0:
            logger.info("Reaped %d expired license slots", total_reaped)
        return total_reaped

    async def _reap_expired_slots_for_product(self, product: LicenseProduct) -> int:
        """Reap expired slots for a specific product."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=product.slot_ttl)

        q = select(LicenseSlot).where(
            and_(
                LicenseSlot.product_id == product.id,
                LicenseSlot.is_active == True,
                LicenseSlot.acquired_at < cutoff,
            )
        )
        expired_slots = (await self.session.execute(q)).scalars().all()

        for slot in expired_slots:
            slot.is_active = False
            slot.released_at = now
            slot.result = "expired"

        if expired_slots:
            await self.session.commit()

        return len(expired_slots)

    async def get_queue_status(self, product_id: int | None = None) -> list[dict]:
        """Get queue status, optionally filtered by product."""
        if product_id:
            products = [await self.get_product(product_id)]
            products = [p for p in products if p]
        else:
            q = select(LicenseProduct).where(LicenseProduct.is_active == True)
            products = list((await self.session.execute(q)).scalars().all())

        statuses = []
        for product in products:
            # Active slots
            active_q = select(func.count(LicenseSlot.id)).where(
                and_(
                    LicenseSlot.product_id == product.id,
                    LicenseSlot.is_active == True,
                )
            )
            active_count = (await self.session.execute(active_q)).scalar() or 0

            # Recent completions (last 10)
            completed_q = (
                select(LicenseSlot)
                .where(
                    and_(
                        LicenseSlot.product_id == product.id,
                        LicenseSlot.is_active == False,
                    )
                )
                .order_by(LicenseSlot.released_at.desc())
                .limit(10)
            )
            completed = (await self.session.execute(completed_q)).scalars().all()

            statuses.append({
                "product_id": product.id,
                "product_name": product.name,
                "active_slots": active_count,
                "max_concurrent": product.max_concurrent,
                "recent_completions": [
                    {
                        "slot_id": s.slot_id,
                        "hostname": s.hostname,
                        "result": s.result,
                        "elapsed_seconds": s.elapsed_seconds,
                        "released_at": s.released_at.isoformat() if s.released_at else None,
                    }
                    for s in completed
                ],
            })

        return statuses

    async def get_license_stats(self, product_id: int | None = None) -> dict:
        """Get license statistics."""
        now = datetime.now(timezone.utc)

        # Build product filter
        product_filter = []
        if product_id:
            product_filter.append(LicenseToken.product_id == product_id)

        # Total tokens
        total_q = select(func.count(LicenseToken.id))
        if product_filter:
            total_q = total_q.where(*product_filter)
        total = (await self.session.execute(total_q)).scalar() or 0

        # Used tokens
        used_q = select(func.count(LicenseToken.id)).where(LicenseToken.used == True)
        if product_filter:
            used_q = used_q.where(*product_filter)
        used = (await self.session.execute(used_q)).scalar() or 0

        # Expired (unused) tokens
        expired_q = select(func.count(LicenseToken.id)).where(
            and_(LicenseToken.used == False, LicenseToken.expires_at < now)
        )
        if product_filter:
            expired_q = expired_q.where(*product_filter)
        expired = (await self.session.execute(expired_q)).scalar() or 0

        # Active slots
        slot_filter = []
        if product_id:
            slot_filter.append(LicenseSlot.product_id == product_id)

        active_slots_q = select(func.count(LicenseSlot.id)).where(
            LicenseSlot.is_active == True
        )
        if slot_filter:
            active_slots_q = active_slots_q.where(*slot_filter)
        active_slots = (await self.session.execute(active_slots_q)).scalar() or 0

        return {
            "total_tokens_generated": total,
            "tokens_used": used,
            "tokens_expired": expired,
            "active_slots": active_slots,
        }
