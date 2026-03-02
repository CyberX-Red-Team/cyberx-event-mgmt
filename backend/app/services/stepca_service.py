"""step-ca integration service for TLS certificate management.

Handles step-ca sidecar lifecycle (create, start, stop) and certificate
operations (CSR generation, signing, revocation) via step-ca's API.
"""
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.config import get_settings
from app.services.render_service import RenderServiceManager
from app.utils.encryption import encrypt_field, decrypt_field

logger = logging.getLogger(__name__)


class StepCAService:
    """Manages step-ca instances and certificate signing operations."""

    def __init__(self):
        self.settings = get_settings()
        self.render = RenderServiceManager()

    # -------------------------------------------------------------------------
    # CSR and Key Generation
    # -------------------------------------------------------------------------

    @staticmethod
    def generate_csr(common_name: str, sans: list[str]) -> tuple[str, str]:
        """Generate a CSR and private key for the given CN and SANs.

        Args:
            common_name: Primary domain name (e.g. 'web.example.com')
            sans: Additional Subject Alternative Names

        Returns:
            Tuple of (csr_pem, private_key_pem) as strings.
        """
        # Generate RSA key
        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Build SAN list (always include CN)
        all_sans = set()
        all_sans.add(common_name)
        for san in sans:
            if san:
                all_sans.add(san)

        san_names = []
        for name in all_sans:
            if name.startswith("*."):
                san_names.append(x509.DNSName(name))
            else:
                san_names.append(x509.DNSName(name))

        # Build CSR
        builder = x509.CertificateSigningRequestBuilder()
        builder = builder.subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]))
        builder = builder.add_extension(
            x509.SubjectAlternativeName(san_names),
            critical=False,
        )

        csr = builder.sign(key, hashes.SHA256())

        # Serialize
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")
        key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        return csr_pem, key_pem

    # -------------------------------------------------------------------------
    # PEM Validation
    # -------------------------------------------------------------------------

    @staticmethod
    def validate_pem_certificate(pem_data: bytes) -> x509.Certificate:
        """Parse and validate a PEM-encoded certificate.

        Raises ValueError if invalid.
        """
        try:
            cert = x509.load_pem_x509_certificate(pem_data)
            return cert
        except Exception as e:
            raise ValueError(f"Invalid PEM certificate: {e}")

    @staticmethod
    def validate_pem_private_key(pem_data: bytes) -> bool:
        """Validate that PEM data contains a valid private key.

        Raises ValueError if invalid.
        """
        try:
            serialization.load_pem_private_key(pem_data, password=None)
            return True
        except Exception as e:
            raise ValueError(f"Invalid PEM private key: {e}")

    @staticmethod
    def validate_chain(root_pem: bytes, intermediate_pem: bytes) -> bool:
        """Validate that the intermediate cert is signed by the root cert.

        Raises ValueError if the chain is invalid.
        """
        try:
            root = x509.load_pem_x509_certificate(root_pem)
            intermediate = x509.load_pem_x509_certificate(intermediate_pem)

            # Check issuer matches
            if intermediate.issuer != root.subject:
                raise ValueError(
                    "Intermediate certificate issuer does not match root certificate subject"
                )

            # Verify the intermediate cert's signature using the root's public key
            root.public_key().verify(
                intermediate.signature,
                intermediate.tbs_certificate_bytes,
                intermediate.signature_hash_algorithm,
            )
            return True
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Chain validation failed: {e}")

    # -------------------------------------------------------------------------
    # Sidecar Lifecycle Management
    # -------------------------------------------------------------------------

    async def initialize_ca_chain(
        self,
        ca_chain,
        root_cert_bytes: bytes,
        root_key_bytes: bytes,
        intermediate_cert_bytes: bytes,
        intermediate_key_bytes: bytes,
        db,
    ) -> bool:
        """Create a new Render private service for this CA chain.

        Downloads CA files, base64-encodes them, and passes as env vars
        to a new step-ca Render service.

        Args:
            ca_chain: CAChain model instance
            root_cert_bytes: Raw PEM bytes for root certificate
            root_key_bytes: Raw PEM bytes for root private key
            intermediate_cert_bytes: Raw PEM bytes for intermediate certificate
            intermediate_key_bytes: Raw PEM bytes for intermediate private key
            db: Database session

        Returns:
            True if service was created and deployed successfully.
        """
        provisioner_password = self.settings.STEPCA_PROVISIONER_PASSWORD
        if not provisioner_password:
            logger.error("STEPCA_PROVISIONER_PASSWORD not configured")
            return False

        # Base64 encode CA files for env vars
        env_vars = [
            {"key": "STEPCA_ROOT_CERT_B64", "value": base64.b64encode(root_cert_bytes).decode()},
            {"key": "STEPCA_ROOT_KEY_B64", "value": base64.b64encode(root_key_bytes).decode()},
            {"key": "STEPCA_INTERMEDIATE_CERT_B64", "value": base64.b64encode(intermediate_cert_bytes).decode()},
            {"key": "STEPCA_INTERMEDIATE_KEY_B64", "value": base64.b64encode(intermediate_key_bytes).decode()},
            {"key": "STEPCA_PROVISIONER_PASSWORD", "value": provisioner_password},
            {"key": "STEPCA_PROVISIONER_NAME", "value": ca_chain.step_ca_provisioner or "cyberx"},
        ]

        service_name = f"cyberx-stepca-{ca_chain.id}"

        # Update status
        ca_chain.step_ca_status = "starting"
        await db.commit()

        # Create the Render service
        service = await self.render.create_private_service(
            name=service_name,
            dockerfile_path="./Dockerfile.stepca",
            env_vars=env_vars,
            plan="starter",
        )

        if not service:
            ca_chain.step_ca_status = "error"
            await db.commit()
            return False

        service_id = service.get("id")
        ca_chain.render_service_id = service_id
        ca_chain.step_ca_url = f"https://{service_name}:9000"
        await db.commit()

        # Wait for deploy
        deploy_live = await self.render.wait_for_deploy_live(service_id, timeout=300, interval=10)
        if not deploy_live:
            ca_chain.step_ca_status = "error"
            await db.commit()
            return False

        # Wait for step-ca health
        health_url = f"{ca_chain.step_ca_url}/health"
        healthy = await self.render.wait_for_service_health(health_url, timeout=120, interval=5)

        ca_chain.step_ca_status = "running" if healthy else "error"
        await db.commit()
        return healthy

    async def start_instance(self, ca_chain, db) -> bool:
        """Resume the step-ca Render service for this CA chain."""
        if not ca_chain.render_service_id:
            logger.error(f"CA chain {ca_chain.id} has no Render service ID")
            return False

        ca_chain.step_ca_status = "starting"
        await db.commit()

        success = await self.render.start_service(
            service_id=ca_chain.render_service_id,
            health_url=f"{ca_chain.step_ca_url}/health",
            plan="starter",
        )

        ca_chain.step_ca_status = "running" if success else "error"
        await db.commit()
        return success

    async def stop_instance(self, ca_chain, db) -> bool:
        """Suspend the step-ca Render service."""
        if not ca_chain.render_service_id:
            logger.error(f"CA chain {ca_chain.id} has no Render service ID")
            return False

        success = await self.render.stop_service(ca_chain.render_service_id)
        ca_chain.step_ca_status = "stopped" if success else "error"
        await db.commit()
        return success

    async def get_instance_status(self, ca_chain) -> str:
        """Check the actual status of the step-ca Render service."""
        if not ca_chain.render_service_id:
            return "stopped"

        info = await self.render.get_service_info(ca_chain.render_service_id)
        if not info:
            return "error"

        service = info.get("service", info)
        suspended = service.get("suspended", "not_suspended")
        if suspended == "suspended":
            return "stopped"
        return "running"

    async def delete_instance(self, ca_chain, db) -> bool:
        """Delete the Render service for this CA chain."""
        if ca_chain.render_service_id:
            await self.render.delete_service(ca_chain.render_service_id)
            ca_chain.render_service_id = None
            ca_chain.step_ca_url = None

        ca_chain.step_ca_status = "stopped"
        await db.commit()
        return True

    # -------------------------------------------------------------------------
    # Certificate Signing
    # -------------------------------------------------------------------------

    async def sign_certificate(
        self,
        ca_chain,
        csr_pem: str,
        duration: str = "2160h",
    ) -> Optional[dict]:
        """Sign a CSR via step-ca's /sign endpoint.

        Args:
            ca_chain: CAChain model instance
            csr_pem: PEM-encoded CSR string
            duration: Certificate duration (e.g. '2160h' for 90 days)

        Returns:
            Dict with 'crt' (leaf cert PEM) and 'ca' (intermediate cert PEM),
            or None on failure.
        """
        if not ca_chain.step_ca_url:
            logger.error(f"CA chain {ca_chain.id} has no step-ca URL")
            return None

        provisioner_password = self.settings.STEPCA_PROVISIONER_PASSWORD
        provisioner_name = ca_chain.step_ca_provisioner or "cyberx"

        # step-ca /sign requires a token from the provisioner
        # First get a token, then sign
        sign_url = f"{ca_chain.step_ca_url}/1.0/sign"

        payload = {
            "csr": csr_pem,
            "ott": await self._get_provisioner_token(
                ca_chain, provisioner_name, provisioner_password
            ),
            "notAfter": duration,
        }

        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.post(
                    sign_url,
                    json=payload,
                    timeout=30.0,
                )
                if resp.status_code == 200 or resp.status_code == 201:
                    data = resp.json()
                    return {
                        "crt": data.get("crt", ""),
                        "ca": data.get("ca", ""),
                        "serial_number": data.get("serialNumber", ""),
                    }
                else:
                    logger.error(f"step-ca /sign failed: {resp.status_code} {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"step-ca sign error: {e}")
            return None

    async def _get_provisioner_token(
        self, ca_chain, provisioner_name: str, password: str
    ) -> str:
        """Get a one-time token from step-ca for signing.

        Uses the /provisioners endpoint to get the provisioner's encrypted key,
        then generates a token locally.
        """
        # For JWK provisioners, we need to call the step CLI or use the API
        # The simplest approach is to use step-ca's /1.0/sign with inline credentials
        # step-ca supports password-based provisioner auth
        token_url = f"{ca_chain.step_ca_url}/1.0/provisioners"

        try:
            async with httpx.AsyncClient(verify=False) as client:
                # Get provisioner info
                resp = await client.get(token_url, timeout=10.0)
                if resp.status_code != 200:
                    logger.error(f"Failed to get provisioners: {resp.status_code}")
                    return ""

                # For now, use empty OTT — step-ca may accept direct CSR signing
                # with provisioner password in the request
                # TODO: Implement proper JWK token generation
                return password

        except Exception as e:
            logger.error(f"Failed to get provisioner token: {e}")
            return ""

    async def revoke_certificate(
        self, ca_chain, serial_number: str, reason: str = ""
    ) -> bool:
        """Revoke a certificate via step-ca's /revoke endpoint.

        Args:
            ca_chain: CAChain model instance
            serial_number: Certificate serial number to revoke
            reason: Revocation reason

        Returns:
            True if revocation was successful.
        """
        if not ca_chain.step_ca_url:
            logger.error(f"CA chain {ca_chain.id} has no step-ca URL")
            return False

        revoke_url = f"{ca_chain.step_ca_url}/1.0/revoke"

        payload = {
            "serial": serial_number,
            "reasonCode": 0,  # unspecified
            "reason": reason,
            "passive": True,
        }

        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.post(
                    revoke_url,
                    json=payload,
                    timeout=15.0,
                )
                if resp.status_code in (200, 201):
                    logger.info(f"Revoked certificate {serial_number}")
                    return True
                else:
                    logger.error(f"step-ca revoke failed: {resp.status_code} {resp.text}")
                    return False
        except Exception as e:
            logger.error(f"step-ca revoke error: {e}")
            return False

    # -------------------------------------------------------------------------
    # R2 Storage Helpers
    # -------------------------------------------------------------------------

    def _get_r2_client(self):
        """Get an S3 client configured for Cloudflare R2."""
        import boto3
        from botocore.config import Config as BotoConfig

        return boto3.client(
            "s3",
            endpoint_url=f"https://{self.settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=self.settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=self.settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
            config=BotoConfig(signature_version="s3v4"),
        )

    def upload_to_r2(self, key: str, data: bytes, content_type: str = "application/x-pem-file") -> bool:
        """Upload data to R2."""
        try:
            s3 = self._get_r2_client()
            s3.put_object(
                Bucket=self.settings.R2_BUCKET,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            logger.info(f"Uploaded to R2: {key}")
            return True
        except Exception as e:
            logger.error(f"R2 upload failed for {key}: {e}")
            return False

    def download_from_r2(self, key: str) -> Optional[bytes]:
        """Download data from R2."""
        try:
            s3 = self._get_r2_client()
            response = s3.get_object(Bucket=self.settings.R2_BUCKET, Key=key)
            return response["Body"].read()
        except Exception as e:
            logger.error(f"R2 download failed for {key}: {e}")
            return None

    def delete_from_r2(self, key: str) -> bool:
        """Delete an object from R2."""
        try:
            s3 = self._get_r2_client()
            s3.delete_object(Bucket=self.settings.R2_BUCKET, Key=key)
            return True
        except Exception as e:
            logger.error(f"R2 delete failed for {key}: {e}")
            return False

    def get_ca_files_r2_prefix(self, chain_id: int) -> str:
        """Get the R2 key prefix for a CA chain's files."""
        prefix = self.settings.STEPCA_CA_FILES_R2_PREFIX or "tls/ca-chains"
        return f"{prefix}/{chain_id}"
