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
from app.services.nginx_config_service import (
    SNI_BRIDGE_PORT_MIN,
    SNI_BRIDGE_PORT_MAX,
)
from app.utils.encryption import encrypt_field, decrypt_field


class StreamSniCollisionError(ValueError):
    """Raised when SNI/legacy streams can't co-exist on a (redirector, listen_port).

    A given listen_port on a redirector is either:
      - hosting exactly one legacy (non-SNI) stream, or
      - hosting N SNI-routed streams (each with a distinct sni_hostname).
    Trying to mix the two is rejected before any DB write.
    """


class NoBridgePortAvailableError(RuntimeError):
    """Raised when the SNI bridge port pool for a redirector is exhausted."""


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
        sponsored_owner_ids: Optional[List[int]] = None,
    ) -> List[Redirector]:
        """Return redirectors ordered by name, with stream_configs and owner eager-loaded.

        Scoping:
          - owner_id=None → all redirectors (admin view).
          - owner_id set, include_public=False → only this user's redirectors.
          - owner_id set, include_public=True → user's own + visibility='public'.
          - sponsored_owner_ids provided → also include redirectors owned by
            those users (used for sponsors who see all their invitees' rows).
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
            clauses = [Redirector.owner_id == owner_id]
            if include_public:
                clauses.append(Redirector.visibility == "public")
            if sponsored_owner_ids:
                clauses.append(Redirector.owner_id.in_(sponsored_owner_ids))
            query = query.where(or_(*clauses))
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
        sni_hostname = data.get("sni_hostname")
        listen_port = data["listen_port"]

        # Enforce SNI/legacy collision rule BEFORE allocating a bridge port —
        # so a rejected create doesn't burn a port slot.
        await self._check_sni_collision(
            redirector_id=redirector_id,
            listen_port=listen_port,
            sni_hostname=sni_hostname,
            excluded_stream_id=None,
        )

        internal_bridge_port: Optional[int] = None
        if sni_hostname:
            internal_bridge_port = await self._allocate_bridge_port(redirector_id)
            # SNI streams require TLS — enforce here instead of silently
            # producing an inner terminator that nginx would reject.
            if not data.get("ssl_enabled"):
                raise ValueError("SNI-routed streams must have ssl_enabled=True.")
            if not (data.get("ssl_cert_path") and data.get("ssl_key_path")):
                raise ValueError(
                    "SNI-routed streams must have ssl_cert_path and ssl_key_path."
                )

        stream = StreamConfig(
            id=str(uuid.uuid4()),
            redirector_id=redirector_id,
            name=data["name"],
            protocol=data.get("protocol", "tcp"),
            listen_port=listen_port,
            cs_ip=data["cs_ip"],
            cs_port=data["cs_port"],
            sni_hostname=sni_hostname,
            internal_bridge_port=internal_bridge_port,
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

    # -------------------------------------------------------------------------
    # SNI routing helpers
    # -------------------------------------------------------------------------

    async def _check_sni_collision(
        self,
        *,
        redirector_id: str,
        listen_port: int,
        sni_hostname: Optional[str],
        excluded_stream_id: Optional[str],
    ) -> None:
        """Enforce: a port is either legacy-only or SNI-only on a redirector.

        - legacy new on legacy-occupied port → reject
        - legacy new on SNI-occupied port    → reject
        - SNI new on legacy-occupied port    → reject
        - SNI new on SNI-occupied port       → OK (duplicate-hostname caught
          by the DB unique constraint)
        """
        result = await self.session.execute(
            select(StreamConfig).where(
                StreamConfig.redirector_id == redirector_id,
                StreamConfig.listen_port == listen_port,
            )
        )
        existing = [
            s for s in result.scalars().all()
            if excluded_stream_id is None or s.id != excluded_stream_id
        ]
        if not existing:
            return

        existing_has_legacy = any(s.sni_hostname is None for s in existing)
        existing_has_sni = any(s.sni_hostname is not None for s in existing)

        if sni_hostname is None:
            # New stream is legacy
            if existing_has_sni:
                raise StreamSniCollisionError(
                    f"Port {listen_port} is already hosting SNI-routed streams on "
                    f"this redirector. Use a different port or add an SNI hostname "
                    f"to share the port."
                )
            if existing_has_legacy:
                raise StreamSniCollisionError(
                    f"Port {listen_port} is already in use by a legacy stream."
                )
        else:
            # New stream is SNI
            if existing_has_legacy:
                raise StreamSniCollisionError(
                    f"Port {listen_port} is already in use by a non-SNI stream "
                    f"on this redirector. Remove it first or pick a different port."
                )

    async def _allocate_bridge_port(self, redirector_id: str) -> int:
        """Pick the lowest free bridge port in [SNI_BRIDGE_PORT_MIN, SNI_BRIDGE_PORT_MAX]
        for this redirector. Raises NoBridgePortAvailableError if exhausted.
        """
        result = await self.session.execute(
            select(StreamConfig.internal_bridge_port).where(
                StreamConfig.redirector_id == redirector_id,
                StreamConfig.internal_bridge_port.is_not(None),
            )
        )
        used = {row[0] for row in result.all()}
        for candidate in range(SNI_BRIDGE_PORT_MIN, SNI_BRIDGE_PORT_MAX + 1):
            if candidate not in used:
                return candidate
        raise NoBridgePortAvailableError(
            f"No free SNI bridge ports remain on redirector {redirector_id} "
            f"(range {SNI_BRIDGE_PORT_MIN}-{SNI_BRIDGE_PORT_MAX} exhausted)."
        )

    async def update_stream(self, stream: StreamConfig, data: dict) -> StreamConfig:
        """Update stream from a dict of changed fields (exclude_unset=True).

        SNI rules:
          - You can rename sni_hostname on an already-SNI stream (changes the
            map entry in the outer router; no port realloc).
          - You cannot toggle a stream between legacy and SNI via update —
            it's a structural change with port-allocation and cert implications.
            Delete + recreate is the supported path.
          - Changing listen_port triggers the same SNI/legacy collision check
            the create path uses.
        """
        # Structural toggle guard
        if "sni_hostname" in data:
            new_sni = data["sni_hostname"]
            current_sni = stream.sni_hostname
            if (current_sni is None) != (new_sni is None):
                raise StreamSniCollisionError(
                    "Cannot toggle a stream between legacy and SNI routing via "
                    "update. Delete this stream and create a new one with the "
                    "desired routing mode."
                )

        # Collision check if listen_port is changing OR sni_hostname changes
        # to a value that might conflict (same hostname would hit the DB
        # unique constraint anyway, but we surface a clearer error first).
        effective_listen_port = data.get("listen_port", stream.listen_port)
        effective_sni = data.get("sni_hostname", stream.sni_hostname)
        if (
            "listen_port" in data and data["listen_port"] != stream.listen_port
        ) or (
            "sni_hostname" in data and data["sni_hostname"] != stream.sni_hostname
        ):
            await self._check_sni_collision(
                redirector_id=stream.redirector_id,
                listen_port=effective_listen_port,
                sni_hostname=effective_sni,
                excluded_stream_id=stream.id,
            )

        simple_fields = (
            "name", "protocol", "listen_port", "cs_ip", "cs_port",
            "access_control_enabled", "ssl_enabled", "ssl_cert_path",
            "ssl_key_path", "ssl_protocols", "ssl_ciphers",
        )
        for field in simple_fields:
            if field in data and data[field] is not None:
                setattr(stream, field, data[field])

        # These can legitimately be falsy ([] or False/None) — handle separately
        if "allowed_cidrs" in data:
            stream.allowed_cidrs = data["allowed_cidrs"]
        if "enabled" in data and data["enabled"] is not None:
            stream.enabled = data["enabled"]
        if "deployed" in data and data["deployed"] is not None:
            stream.deployed = data["deployed"]
        # custom_config_override: None means "reset to generated" (clear),
        # non-empty string means "install override". Use a distinct sentinel
        # key in data to allow both operations.
        if "custom_config_override" in data:
            stream.custom_config_override = data["custom_config_override"]
        # sni_hostname rename (same-polarity per structural guard above)
        if "sni_hostname" in data:
            stream.sni_hostname = data["sni_hostname"]

        await self.session.commit()
        await self.session.refresh(stream)
        return stream

    async def delete_stream(self, stream: StreamConfig) -> None:
        await self.session.delete(stream)
        await self.session.commit()
