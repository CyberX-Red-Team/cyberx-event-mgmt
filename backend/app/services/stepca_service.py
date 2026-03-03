"""step-ca integration service for TLS certificate management.

Handles step-ca sidecar lifecycle (create, start, stop) and certificate
operations (CSR generation, signing, revocation) via step-ca's API.
"""
import base64
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.keywrap import aes_key_unwrap
from cryptography.x509.oid import NameOID
from jose import jwt as jose_jwt
from jose.constants import Algorithms

from app.config import get_settings
from app.services.render_service import RenderServiceManager
from app.utils.encryption import encrypt_field, decrypt_field

logger = logging.getLogger(__name__)


def _base64url_decode(data: str) -> bytes:
    """Decode base64url string (no padding required)."""
    # Add padding if needed
    rem = len(data) % 4
    if rem:
        data += "=" * (4 - rem)
    return base64.urlsafe_b64decode(data)


def _base64url_encode(data: bytes) -> str:
    """Encode bytes as base64url string (no padding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decrypt_jwe_pbes2(jwe_compact: str, password: str) -> bytes:
    """Decrypt a JWE compact serialization encrypted with PBES2-HS256+A128KW + A256GCM.

    This implements the decryption manually using the `cryptography` library,
    bypassing jwcrypto's PBKDF2 iteration limit which blocks step-ca's p2c=100000.

    Args:
        jwe_compact: JWE compact serialization string (5 base64url parts separated by dots)
        password: Password used to derive the key encryption key

    Returns:
        Decrypted plaintext bytes.
    """
    parts = jwe_compact.split(".")
    if len(parts) != 5:
        raise ValueError(f"Invalid JWE compact serialization: expected 5 parts, got {len(parts)}")

    header_b64, ek_b64, iv_b64, ct_b64, tag_b64 = parts

    # Decode header
    header = json.loads(_base64url_decode(header_b64))
    alg = header.get("alg", "")
    enc = header.get("enc", "")
    p2c = header.get("p2c", 0)
    p2s_b64 = header.get("p2s", "")

    if alg != "PBES2-HS256+A128KW":
        raise ValueError(f"Unsupported JWE algorithm: {alg}")
    if enc != "A256GCM":
        raise ValueError(f"Unsupported JWE encryption: {enc}")

    # Decode the JWE parts
    encrypted_key = _base64url_decode(ek_b64)
    iv = _base64url_decode(iv_b64)
    ciphertext = _base64url_decode(ct_b64)
    tag = _base64url_decode(tag_b64)
    p2s = _base64url_decode(p2s_b64)

    # Derive KEK using PBKDF2 (RFC 7518 Section 4.8.1.1)
    # Salt = UTF8(alg) || 0x00 || p2s
    salt = alg.encode("utf-8") + b"\x00" + p2s

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=16,  # 128 bits for A128KW
        salt=salt,
        iterations=p2c,
    )
    kek = kdf.derive(password.encode("utf-8"))

    # Unwrap CEK using AES Key Wrap (RFC 3394)
    cek = aes_key_unwrap(kek, encrypted_key)

    # Decrypt ciphertext using AES-256-GCM
    # AAD = ASCII bytes of the base64url-encoded header (NOT decoded)
    aad = header_b64.encode("ascii")
    aesgcm = AESGCM(cek)
    plaintext = aesgcm.decrypt(iv, ciphertext + tag, aad)

    return plaintext


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
    def parse_pem_chain(chain_pem: bytes) -> list[x509.Certificate]:
        """Parse a PEM file containing one or more concatenated certificates.

        Returns list of certificates in order (first cert in file = first element).
        Raises ValueError if no valid certificates found.
        """
        from cryptography.x509 import load_pem_x509_certificate

        certs = []
        pem_str = chain_pem.decode("utf-8", errors="replace")
        # Split on BEGIN markers
        parts = pem_str.split("-----BEGIN CERTIFICATE-----")
        for part in parts[1:]:  # skip empty first split
            end_idx = part.find("-----END CERTIFICATE-----")
            if end_idx == -1:
                continue
            pem_block = "-----BEGIN CERTIFICATE-----" + part[:end_idx + len("-----END CERTIFICATE-----")]
            try:
                cert = load_pem_x509_certificate(pem_block.encode())
                certs.append(cert)
            except Exception:
                continue

        if not certs:
            raise ValueError("No valid PEM certificates found in chain file")
        return certs

    @staticmethod
    def _verify_cert_signature(child_cert: x509.Certificate, issuer_cert: x509.Certificate) -> None:
        """Verify that child_cert was signed by issuer_cert.

        Handles both RSA and EC key types (different verify() signatures).
        Raises an exception if verification fails.
        """
        pub_key = issuer_cert.public_key()
        sig = child_cert.signature
        data = child_cert.tbs_certificate_bytes
        algo = child_cert.signature_hash_algorithm

        if isinstance(pub_key, rsa.RSAPublicKey):
            pub_key.verify(sig, data, padding.PKCS1v15(), algo)
        elif isinstance(pub_key, ec.EllipticCurvePublicKey):
            pub_key.verify(sig, data, ec.ECDSA(algo))
        else:
            # Fallback for other key types (Ed25519, etc.)
            pub_key.verify(sig, data)

    @staticmethod
    def validate_signing_chain(signing_cert_pem: bytes, chain_pem: bytes) -> bool:
        """Validate that the signing cert chains to the certs in chain_pem.

        The chain file should contain certs from the signing cert's issuer
        up to the root. If the chain file's first cert IS the signing cert
        itself (common with full-chain PEM files), it is automatically skipped.

        Raises ValueError if validation fails.
        """
        try:
            signing_cert = x509.load_pem_x509_certificate(signing_cert_pem)
            chain_certs = StepCAService.parse_pem_chain(chain_pem)

            # If the first cert in the chain is the signing cert itself, skip it.
            # This handles full-chain PEM files that include the signing cert.
            if chain_certs[0].subject == signing_cert.subject:
                try:
                    # Double-check by comparing the public key
                    if (chain_certs[0].public_key().public_bytes(
                            serialization.Encoding.PEM,
                            serialization.PublicFormat.SubjectPublicKeyInfo)
                        == signing_cert.public_key().public_bytes(
                            serialization.Encoding.PEM,
                            serialization.PublicFormat.SubjectPublicKeyInfo)):
                        chain_certs = chain_certs[1:]
                except Exception:
                    pass

            if not chain_certs:
                raise ValueError(
                    "CA chain file must contain at least one certificate above "
                    "the signing cert (the issuing CA or root)"
                )

            # The first cert in the chain should be the signing cert's issuer
            issuer_cert = chain_certs[0]
            if signing_cert.issuer != issuer_cert.subject:
                raise ValueError(
                    f"Signing certificate issuer ({signing_cert.issuer.rfc4514_string()}) "
                    f"does not match first certificate in chain "
                    f"({issuer_cert.subject.rfc4514_string()})"
                )

            # Verify signature
            StepCAService._verify_cert_signature(signing_cert, issuer_cert)

            # Validate the rest of the chain (each cert signed by the next)
            for i in range(len(chain_certs) - 1):
                child = chain_certs[i]
                parent = chain_certs[i + 1]
                if child.issuer != parent.subject:
                    raise ValueError(
                        f"Chain broken: cert {i} issuer "
                        f"({child.issuer.rfc4514_string()}) does not match "
                        f"cert {i+1} subject ({parent.subject.rfc4514_string()})"
                    )
                StepCAService._verify_cert_signature(child, parent)

            return True
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Chain validation failed: {e}")

    @staticmethod
    def strip_signing_cert_from_chain(signing_cert_pem: bytes, chain_pem: bytes) -> bytes:
        """Remove the signing cert from the chain if it's the first cert.

        Returns normalized chain PEM containing only certs above the signing cert.
        If the signing cert is not in the chain, returns the original chain unchanged.
        """
        signing_cert = x509.load_pem_x509_certificate(signing_cert_pem)
        chain_certs = StepCAService.parse_pem_chain(chain_pem)

        if chain_certs and chain_certs[0].subject == signing_cert.subject:
            if (chain_certs[0].public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo)
                == signing_cert.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo)):
                chain_certs = chain_certs[1:]

        if not chain_certs:
            return chain_pem  # Return original if nothing left

        return b"".join(
            cert.public_bytes(serialization.Encoding.PEM) for cert in chain_certs
        )

    @staticmethod
    def extract_root_cert(chain_pem: bytes) -> bytes:
        """Extract the root (last/self-signed) certificate from a chain PEM.

        Returns PEM bytes of the root certificate.
        """
        certs = StepCAService.parse_pem_chain(chain_pem)
        # The root is the last cert (self-signed: issuer == subject)
        root = certs[-1]
        return root.public_bytes(serialization.Encoding.PEM)

    # -------------------------------------------------------------------------
    # Sidecar Lifecycle Management
    # -------------------------------------------------------------------------

    async def initialize_ca_chain(
        self,
        ca_chain,
        signing_cert_bytes: bytes,
        signing_key_bytes: bytes,
        ca_chain_bytes: bytes,
        db,
    ) -> bool:
        """Create a new Render private service for this CA chain.

        Base64-encodes the CA files and passes them as env vars
        to a new step-ca Render service.

        Args:
            ca_chain: CAChain model instance
            signing_cert_bytes: PEM bytes for the signing CA certificate
            signing_key_bytes: PEM bytes for the signing CA private key
            ca_chain_bytes: PEM bytes for the chain above the signing cert (up to root)
            db: Database session

        Returns:
            True if service was created and deployed successfully.
        """
        provisioner_password = self.settings.STEPCA_PROVISIONER_PASSWORD
        if not provisioner_password:
            logger.error("STEPCA_PROVISIONER_PASSWORD not configured")
            return False

        # Extract root cert from chain for step-ca trust anchor
        root_cert_bytes = self.extract_root_cert(ca_chain_bytes)

        # Base64 encode CA files for env vars
        # Build service name from signing cert CN (e.g. "cyberx-stepca-chiton")
        try:
            signing_cert = x509.load_pem_x509_certificate(signing_cert_bytes)
            cn_attr = signing_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            cn = cn_attr[0].value if cn_attr else str(ca_chain.id)
        except Exception:
            cn = str(ca_chain.id)
        # Sanitize for Render service name: lowercase, alphanumeric + hyphens, max 63 chars
        cn_slug = re.sub(r'[^a-z0-9]+', '-', cn.lower()).strip('-')[:40]
        service_name = f"cyberx-stepca-{cn_slug}"

        env_vars = [
            {"key": "STEPCA_ROOT_CERT_B64", "value": base64.b64encode(root_cert_bytes).decode()},
            {"key": "STEPCA_SIGNING_CERT_B64", "value": base64.b64encode(signing_cert_bytes).decode()},
            {"key": "STEPCA_SIGNING_KEY_B64", "value": base64.b64encode(signing_key_bytes).decode()},
            {"key": "STEPCA_PROVISIONER_PASSWORD", "value": provisioner_password},
            {"key": "STEPCA_PROVISIONER_NAME", "value": ca_chain.step_ca_provisioner or "cyberx"},
            {"key": "STEPCA_SERVICE_NAME", "value": service_name},
        ]

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
        # Render private services use the PORT env var (default 10000 for Docker)
        # and are accessible via https://{service-name}:{port} on the private network
        ca_chain.step_ca_url = f"https://{service_name}:10000"
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

        Authenticates using the JWK provisioner's encrypted key (decrypted with
        the provisioner password) to generate a signed JWT one-time token (OTT).

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

        # Parse CSR to extract CN and SANs for the token
        try:
            csr = x509.load_pem_x509_csr(csr_pem.encode())
            cn_attrs = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            cn = cn_attrs[0].value if cn_attrs else ""
            sans = []
            try:
                san_ext = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName)
                sans = san_ext.value.get_values_for_type(x509.DNSName)
            except x509.ExtensionNotFound:
                pass
            if not sans:
                sans = [cn] if cn else []
        except Exception as e:
            logger.error(f"Failed to parse CSR: {e}")
            return None

        sign_url = f"{ca_chain.step_ca_url}/1.0/sign"

        ott = await self._get_provisioner_token(
            ca_chain, provisioner_name, provisioner_password, cn, sans
        )
        if not ott:
            logger.error("Failed to generate provisioner token")
            return None

        payload = {
            "csr": csr_pem,
            "ott": ott,
            "notAfter": duration,
        }

        try:
            async with httpx.AsyncClient(verify=False) as client:
                resp = await client.post(
                    sign_url,
                    json=payload,
                    timeout=30.0,
                )
                if resp.status_code in (200, 201):
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
        self,
        ca_chain,
        provisioner_name: str,
        password: str,
        common_name: str,
        sans: list[str],
    ) -> str:
        """Generate a signed JWT one-time token for step-ca's /sign endpoint.

        Flow:
        1. Fetch provisioner list from step-ca to get the encrypted JWK key
        2. Decrypt the JWK private key using the provisioner password (PBES2-HS256+A128KW)
        3. Fetch root CA cert and compute SHA-256 fingerprint
        4. Build and sign a JWT with required claims (iss, sub, aud, sha, sans, etc.)
        """
        base_url = ca_chain.step_ca_url

        try:
            async with httpx.AsyncClient(verify=False) as client:
                # Step 1: Get provisioner info (public key + encrypted private key)
                resp = await client.get(f"{base_url}/1.0/provisioners", timeout=10.0)
                if resp.status_code != 200:
                    logger.error(f"Failed to get provisioners: {resp.status_code}")
                    return ""

                provisioners_data = resp.json()

                # step-ca returns {"provisioners": [...], "nextCursor": "..."}
                provisioners_data = provisioners_data if isinstance(provisioners_data, dict) else {}
                provisioners = provisioners_data.get("provisioners") or []

                # Follow pagination cursor if present
                next_cursor = provisioners_data.get("nextCursor", "")
                while next_cursor:
                    page_resp = await client.get(
                        f"{base_url}/1.0/provisioners?cursor={next_cursor}",
                        timeout=10.0,
                    )
                    if page_resp.status_code != 200:
                        break
                    page_data = page_resp.json()
                    page_items = page_data.get("provisioners") or []
                    provisioners.extend(page_items)
                    next_cursor = page_data.get("nextCursor", "")
                    if not page_items:
                        break

                logger.debug(f"Found {len(provisioners)} provisioner(s)")

                # Find our JWK provisioner by name
                provisioner = None
                for p in provisioners:
                    if isinstance(p, dict) and p.get("type") == "JWK" and p.get("name") == provisioner_name:
                        provisioner = p
                        break

                if not provisioner:
                    names = [p.get('name') for p in provisioners if isinstance(p, dict)]
                    logger.error(f"JWK provisioner '{provisioner_name}' not found. "
                                 f"Available: {names}")
                    return ""

                pub_jwk = provisioner.get("key", {})
                encrypted_key = provisioner.get("encryptedKey", "")
                kid = pub_jwk.get("kid", "")

                if not encrypted_key:
                    logger.error("Provisioner has no encryptedKey")
                    return ""

                # Step 2: Decrypt the JWK private key using provisioner password
                # Uses manual PBES2-HS256+A128KW + A256GCM decryption via cryptography
                # to avoid jwcrypto's PBKDF2 iteration limit (step-ca uses p2c=100000).
                try:
                    decrypted = _decrypt_jwe_pbes2(encrypted_key, password)
                    private_jwk_dict = json.loads(decrypted)
                except Exception as e:
                    logger.error(f"Failed to decrypt provisioner key: {e}")
                    return ""

                # Step 3: Get root CA fingerprint (SHA-256 of DER-encoded root cert)
                root_fingerprint = await self._get_root_fingerprint(client, base_url, ca_chain)
                if not root_fingerprint:
                    logger.error("Failed to get root CA fingerprint")
                    return ""

                # Step 4: Build JWT claims
                now = int(time.time())
                alg = private_jwk_dict.get("alg", pub_jwk.get("alg", "ES256"))
                claims = {
                    "iss": provisioner_name,
                    "sub": common_name,
                    "aud": f"{base_url}/1.0/sign",
                    "iat": now,
                    "nbf": now,
                    "exp": now + 300,  # 5 minute validity
                    "jti": str(uuid.uuid4()),
                    "sha": root_fingerprint,
                    "sans": sans if sans else [common_name],
                }

                # Step 5: Sign the JWT using python-jose with the decrypted JWK
                jose_alg = {"ES256": Algorithms.ES256, "ES384": Algorithms.ES384,
                            "ES512": Algorithms.ES512, "RS256": Algorithms.RS256,
                            }.get(alg, Algorithms.ES256)
                headers = {"kid": kid, "typ": "JWT"}
                ott = jose_jwt.encode(claims, private_jwk_dict, algorithm=jose_alg, headers=headers)

                logger.info(f"Generated OTT for provisioner '{provisioner_name}', "
                            f"sub='{common_name}', alg={alg}")
                return ott

        except Exception as e:
            logger.error(f"Failed to generate provisioner token: {e}")
            return ""

    async def _get_root_fingerprint(
        self, client: httpx.AsyncClient, base_url: str, ca_chain=None
    ) -> str:
        """Get SHA-256 fingerprint of the root CA certificate from step-ca.

        Tries multiple methods in order:
        1. /1.0/roots JSON endpoint
        2. /roots.pem PEM endpoint
        3. Root cert from R2 storage (via ca_chain record)
        Returns hex-encoded fingerprint or empty string on failure.
        """
        # Try JSON endpoint first
        try:
            resp = await client.get(f"{base_url}/1.0/roots", timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                root_certs = data.get("crts", [])
                if root_certs:
                    root_cert = x509.load_pem_x509_certificate(root_certs[0].encode())
                    return hashlib.sha256(
                        root_cert.public_bytes(serialization.Encoding.DER)
                    ).hexdigest()
        except Exception as e:
            logger.debug(f"/1.0/roots JSON failed: {e}")

        # Fallback to PEM endpoint
        try:
            resp = await client.get(f"{base_url}/roots.pem", timeout=10.0)
            if resp.status_code == 200:
                root_cert = x509.load_pem_x509_certificate(resp.content)
                return hashlib.sha256(
                    root_cert.public_bytes(serialization.Encoding.DER)
                ).hexdigest()
        except Exception as e:
            logger.debug(f"/roots.pem failed: {e}")

        # Fallback: compute from CA chain files in R2
        if ca_chain and ca_chain.ca_chain_r2_key:
            try:
                chain_bytes = self.download_from_r2(ca_chain.ca_chain_r2_key)
                if chain_bytes:
                    root_pem = self.extract_root_cert(chain_bytes)
                    root_cert = x509.load_pem_x509_certificate(root_pem)
                    return hashlib.sha256(
                        root_cert.public_bytes(serialization.Encoding.DER)
                    ).hexdigest()
            except Exception as e:
                logger.debug(f"R2 root cert fallback failed: {e}")

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
