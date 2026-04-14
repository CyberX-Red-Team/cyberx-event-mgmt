"""CRUD service for Redirector and StreamConfig models.

SSH keys are encrypted with Fernet before any database write and are
decrypted only on explicit request (get_decrypted_key / get_decrypted_passphrase).
Callers must treat the decrypted key as a short-lived local variable and
must not log, cache, or serialize it.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.redirector import Redirector, StreamConfig
from app.utils.encryption import encrypt_field, decrypt_field


class RedirectorService:
    """Async CRUD service for Redirector and StreamConfig."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # -------------------------------------------------------------------------
    # Redirectors
    # -------------------------------------------------------------------------

    async def list_redirectors(
        self,
        owner_id: int = None,
        include_public: bool = False,
    ) -> List[Redirector]:
        """Return redirectors ordered by name, with stream_configs and owner eager-loaded.

        Scoping:
          - owner_id=None → all redirectors (admin view).
          - owner_id set, include_public=False → only this user's redirectors.
          - owner_id set, include_public=True → user's own + visibility='public'.
        """
        query = (
            select(Redirector)
            .options(
                selectinload(Redirector.stream_configs),
                selectinload(Redirector.owner),
            )
            .order_by(Redirector.name)
        )
        if owner_id is not None:
            if include_public:
                query = query.where(
                    or_(
                        Redirector.owner_id == owner_id,
                        Redirector.visibility == "public",
                    )
                )
            else:
                query = query.where(Redirector.owner_id == owner_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_redirector(self, redirector_id: str) -> Optional[Redirector]:
        """Return a redirector by ID with stream_configs and owner eager-loaded, or None."""
        result = await self.session.execute(
            select(Redirector)
            .options(
                selectinload(Redirector.stream_configs),
                selectinload(Redirector.owner),
            )
            .where(Redirector.id == redirector_id)
        )
        return result.scalar_one_or_none()

    async def get_redirector_by_name(self, name: str) -> Optional[Redirector]:
        result = await self.session.execute(
            select(Redirector).where(Redirector.name == name)
        )
        return result.scalar_one_or_none()

    async def get_redirector_by_instance_id(self, instance_id: int) -> Optional[Redirector]:
        """Return the redirector linked to a cloud instance, or None."""
        result = await self.session.execute(
            select(Redirector).where(Redirector.instance_id == instance_id)
        )
        return result.scalar_one_or_none()

    async def create_redirector(self, data: dict) -> Redirector:
        # CyberX redirectors (instance_id set) always use infrastructure key
        has_instance = data.get("instance_id") is not None
        use_infra = True if has_instance else data.get("use_infrastructure_key", False)
        redirector = Redirector(
            id=str(uuid.uuid4()),
            name=data["name"],
            current_ip=data["current_ip"],
            ssh_port=data.get("ssh_port", 22),
            ssh_username=data["ssh_username"],
            use_infrastructure_key=use_infra,
            ssh_private_key=encrypt_field(data["ssh_private_key"]) if data.get("ssh_private_key") else None,
            ssh_key_passphrase=encrypt_field(data.get("ssh_key_passphrase")) if data.get("ssh_key_passphrase") else None,
            nginx_stream_dir=data.get("nginx_stream_dir", "/etc/nginx/stream.d"),
            notes=data.get("notes"),
            owner_id=data.get("owner_id"),
            instance_id=data.get("instance_id"),
            visibility=data.get("visibility", "private"),
        )
        self.session.add(redirector)
        await self.session.commit()
        await self.session.refresh(redirector)
        # Refresh relationships so stream_count and owner are available
        await self.session.refresh(
            redirector, attribute_names=["stream_configs", "owner"]
        )
        return redirector

    async def clear_byod_key(self, redirector: Redirector) -> Redirector:
        """Clear BYOD SSH credentials and switch to infrastructure key.

        Called after successfully bootstrapping the infra key onto a BYOD redirector.
        """
        redirector.ssh_private_key = None
        redirector.ssh_key_passphrase = None
        redirector.use_infrastructure_key = True
        await self.session.commit()
        await self.session.refresh(redirector)
        return redirector

    async def update_redirector(self, redirector: Redirector, data: dict) -> Redirector:
        """
        Update a redirector from a dict of changed fields (from model_dump(exclude_unset=True)).
        SSH key fields: only updated when non-empty string is provided.
        """
        simple_fields = (
            "name", "current_ip", "ssh_port", "ssh_username",
            "nginx_stream_dir", "notes", "visibility",
        )
        for field in simple_fields:
            if field in data and data[field] is not None:
                setattr(redirector, field, data[field])

        # Update SSH key only when a non-empty value is provided
        if data.get("ssh_private_key"):
            redirector.ssh_private_key = encrypt_field(data["ssh_private_key"])

        # Update passphrase: explicit empty string clears it; non-empty updates it
        if "ssh_key_passphrase" in data:
            raw_pass = data["ssh_key_passphrase"]
            if raw_pass:
                redirector.ssh_key_passphrase = encrypt_field(raw_pass)
            else:
                redirector.ssh_key_passphrase = None

        await self.session.commit()
        await self.session.refresh(redirector)
        await self.session.refresh(
            redirector, attribute_names=["stream_configs", "owner"]
        )
        return redirector

    async def delete_redirector(self, redirector: Redirector) -> None:
        # Ensure stream_configs are loaded so ORM cascade="all, delete-orphan" works
        await self.session.refresh(redirector, attribute_names=["stream_configs"])
        await self.session.delete(redirector)
        await self.session.commit()

    def get_decrypted_key(self, redirector: Redirector) -> str:
        """
        Decrypt and return the SSH private key PEM.

        SECURITY: Treat the returned string as a short-lived local variable.
        Do not log, cache, store in response, or pass it outside the current
        request scope.
        """
        return decrypt_field(redirector.ssh_private_key)

    def get_decrypted_passphrase(self, redirector: Redirector) -> Optional[str]:
        """Decrypt and return the SSH key passphrase, or None if not set."""
        if not redirector.ssh_key_passphrase:
            return None
        return decrypt_field(redirector.ssh_key_passphrase)

    async def update_status(self, redirector: Redirector, status: str, *, os_info: dict | None = None) -> None:
        """Update connectivity status, last_tested_at, and optionally OS info."""
        redirector.status = status
        redirector.last_tested_at = datetime.now(timezone.utc)
        if os_info is not None:
            redirector.os_info = os_info
        await self.session.commit()

    async def update_deployed_at(self, redirector: Redirector) -> None:
        """Record a successful deploy timestamp."""
        redirector.last_deployed_at = datetime.now(timezone.utc)
        await self.session.commit()

    # -------------------------------------------------------------------------
    # StreamConfigs
    # -------------------------------------------------------------------------

    async def list_streams(self, redirector_id: str) -> List[StreamConfig]:
        result = await self.session.execute(
            select(StreamConfig)
            .where(StreamConfig.redirector_id == redirector_id)
            .order_by(StreamConfig.name)
        )
        return list(result.scalars().all())

    async def get_stream(
        self, stream_id: str, redirector_id: str
    ) -> Optional[StreamConfig]:
        result = await self.session.execute(
            select(StreamConfig).where(
                StreamConfig.id == stream_id,
                StreamConfig.redirector_id == redirector_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_stream(self, redirector_id: str, data: dict) -> StreamConfig:
        stream = StreamConfig(
            id=str(uuid.uuid4()),
            redirector_id=redirector_id,
            name=data["name"],
            protocol=data.get("protocol", "tcp"),
            listen_port=data["listen_port"],
            cs_ip=data["cs_ip"],
            cs_port=data["cs_port"],
            access_control_enabled=data.get("access_control_enabled", False),
            allowed_cidrs=data.get("allowed_cidrs"),
            ssl_enabled=data.get("ssl_enabled", False),
            ssl_cert_path=data.get("ssl_cert_path"),
            ssl_key_path=data.get("ssl_key_path"),
            ssl_protocols=data.get("ssl_protocols", "TLSv1.2 TLSv1.3"),
            ssl_ciphers=data.get("ssl_ciphers", "HIGH:!aNULL:!MD5"),
            enabled=data.get("enabled", False),
        )
        self.session.add(stream)
        await self.session.commit()
        await self.session.refresh(stream)
        return stream

    async def update_stream(self, stream: StreamConfig, data: dict) -> StreamConfig:
        """Update stream from a dict of changed fields (exclude_unset=True)."""
        simple_fields = (
            "name", "protocol", "listen_port", "cs_ip", "cs_port",
            "access_control_enabled", "ssl_enabled", "ssl_cert_path",
            "ssl_key_path", "ssl_protocols", "ssl_ciphers",
        )
        for field in simple_fields:
            if field in data and data[field] is not None:
                setattr(stream, field, data[field])

        # These can legitimately be falsy ([] or False) — handle separately
        if "allowed_cidrs" in data:
            stream.allowed_cidrs = data["allowed_cidrs"]
        if "enabled" in data and data["enabled"] is not None:
            stream.enabled = data["enabled"]
        if "deployed" in data and data["deployed"] is not None:
            stream.deployed = data["deployed"]

        await self.session.commit()
        await self.session.refresh(stream)
        return stream

    async def delete_stream(self, stream: StreamConfig) -> None:
        await self.session.delete(stream)
        await self.session.commit()
