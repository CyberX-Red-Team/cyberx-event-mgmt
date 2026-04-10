"""Shared Cloudflare R2 client wrapper.

A thin synchronous boto3 wrapper used by services that need to read or write
objects in the Cloudflare R2 bucket configured via R2_* settings. Callers in
async code paths must offload these calls via ``asyncio.to_thread`` so the
event loop is not blocked.
"""
import logging
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class R2Client:
    """Synchronous Cloudflare R2 client.

    Wraps boto3 with R2-specific configuration. All methods are blocking and
    must be called via ``asyncio.to_thread(...)`` from async code.
    """

    def __init__(self, account_id: str, access_key_id: str, secret_access_key: str, bucket: str):
        self.account_id = account_id
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.bucket = bucket
        self._client = None

    @classmethod
    def from_settings(cls) -> "R2Client":
        """Build a client from the application settings."""
        settings = get_settings()
        return cls(
            account_id=settings.R2_ACCOUNT_ID,
            access_key_id=settings.R2_ACCESS_KEY_ID,
            secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            bucket=settings.R2_BUCKET,
        )

    def _get_boto_client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config as BotoConfig
            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=BotoConfig(signature_version="s3v4"),
            )
        return self._client

    def put_object(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> bool:
        """Upload bytes to R2. Returns True on success."""
        try:
            self._get_boto_client().put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
            )
            return True
        except Exception as e:
            logger.error("R2 put_object failed for %s: %s", key, e)
            return False

    def get_object(self, key: str) -> Optional[bytes]:
        """Download an R2 object as bytes. Returns None on failure."""
        try:
            response = self._get_boto_client().get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except Exception as e:
            logger.error("R2 get_object failed for %s: %s", key, e)
            return None

    def delete_object(self, key: str) -> bool:
        """Delete an R2 object. Returns True on success."""
        try:
            self._get_boto_client().delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            logger.error("R2 delete_object failed for %s: %s", key, e)
            return False
