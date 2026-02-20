"""Signed download URL generation service.

Generates time-limited signed URLs for internal use (e.g., embedding in cloud-init configs).
Supports Cloudflare R2 (S3-compatible) and nginx secure_link backends.
"""
import base64
import hashlib
import logging
import time

from app.config import get_settings

logger = logging.getLogger(__name__)


class DownloadService:
    """Generates signed download URLs. No DB dependency — pure utility."""

    def __init__(self):
        self.settings = get_settings()

    def generate_link(self, filename: str, expires_in: int | None = None) -> str:
        """Generate a signed download URL using the configured backend.

        Args:
            filename: Object key (R2) or file path (nginx) to generate a link for.
            expires_in: Link lifetime in seconds. Defaults to DOWNLOAD_LINK_EXPIRY.

        Returns:
            Signed URL string.

        Raises:
            ValueError: If required configuration is missing.
        """
        if expires_in is None:
            expires_in = self.settings.DOWNLOAD_LINK_EXPIRY

        mode = self.settings.DOWNLOAD_LINK_MODE
        if mode == "nginx":
            return self._generate_nginx_link(filename, expires_in)
        return self._generate_r2_link(filename, expires_in)

    def _generate_r2_link(self, filename: str, expires_in: int) -> str:
        """Generate a Cloudflare R2 pre-signed GET URL."""
        import boto3
        from botocore.config import Config

        account_id = self.settings.R2_ACCOUNT_ID
        access_key_id = self.settings.R2_ACCESS_KEY_ID
        secret_access_key = self.settings.R2_SECRET_ACCESS_KEY
        bucket = self.settings.R2_BUCKET

        if not all([account_id, access_key_id, secret_access_key, bucket]):
            raise ValueError(
                "R2 download links require R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, and R2_BUCKET to be configured"
            )

        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": filename},
            ExpiresIn=expires_in,
        )

        # Replace R2 endpoint with custom domain if configured
        custom_domain = self.settings.R2_CUSTOM_DOMAIN
        if custom_domain:
            url = url.replace(
                f"{endpoint_url}/{bucket}", custom_domain.rstrip("/"), 1
            )

        logger.info("Generated R2 download link for %s (expires in %ds)", filename, expires_in)
        return url

    def _generate_nginx_link(self, filename: str, expires_in: int) -> str:
        """Generate an nginx secure_link signed URL."""
        secret = self.settings.DOWNLOAD_SECRET
        base_url = self.settings.DOWNLOAD_BASE_URL

        if not secret or not base_url:
            raise ValueError(
                "nginx download links require DOWNLOAD_SECRET and DOWNLOAD_BASE_URL"
            )

        expires = int(time.time()) + expires_in
        uri = f"/dl/{filename}"

        # nginx secure_link_md5: MD5(secret + uri + expires) -> binary -> base64url
        raw = f"{secret}{uri}{expires}"
        md5_binary = hashlib.md5(raw.encode()).digest()
        hash_b64 = base64.urlsafe_b64encode(md5_binary).rstrip(b"=").decode()

        logger.info("Generated nginx download link for %s (expires in %ds)", filename, expires_in)
        return f"{base_url}{uri}?hash={hash_b64}&expires={expires}"
