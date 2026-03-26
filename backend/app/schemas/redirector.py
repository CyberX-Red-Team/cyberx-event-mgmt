"""Pydantic schemas for redirector and stream config management.

Security note: ssh_private_key is ALWAYS returned as "**REDACTED**" in output
schemas. The key is never serialized in API responses, regardless of what is
stored in the database.
"""
import ipaddress
import re
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared validation constants
# ---------------------------------------------------------------------------

_SAFE_PATH_RE = re.compile(r"^/[a-zA-Z0-9_./-]+$")
_SAFE_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
_SAFE_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_SAFE_CIPHER_RE = re.compile(r"^[a-zA-Z0-9_:!+\-@.]+$")
_ALLOWED_SSL_PROTOCOLS = {"TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3"}
_UNSAFE_NGINX_CHARS = re.compile(r"[;\n\r{}]")


# ---------------------------------------------------------------------------
# Redirector schemas
# ---------------------------------------------------------------------------

class RedirectorCreate(BaseModel):
    name: str = Field(..., max_length=255)
    current_ip: str = Field(..., max_length=45)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_username: str = Field(..., max_length=255)
    ssh_private_key: str = Field(..., min_length=1)   # Full PEM content
    ssh_key_passphrase: Optional[str] = None
    nginx_stream_dir: str = Field(default="/etc/nginx/stream.d", max_length=500)
    notes: Optional[str] = None

    @field_validator("current_ip")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        ipaddress.ip_address(v)
        return v

    @field_validator("ssh_username")
    @classmethod
    def validate_ssh_username(cls, v: str) -> str:
        if not _SAFE_USERNAME_RE.match(v):
            raise ValueError("ssh_username contains invalid characters (allowed: a-z A-Z 0-9 _ . -)")
        return v

    @field_validator("nginx_stream_dir")
    @classmethod
    def validate_stream_dir(cls, v: str) -> str:
        if not _SAFE_PATH_RE.match(v):
            raise ValueError("nginx_stream_dir must be an absolute path with safe characters only")
        return v


class RedirectorUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    current_ip: Optional[str] = Field(None, max_length=45)
    ssh_port: Optional[int] = Field(None, ge=1, le=65535)
    ssh_username: Optional[str] = Field(None, max_length=255)
    # Empty string or None → keep existing key; non-empty string → update key
    ssh_private_key: Optional[str] = None
    ssh_key_passphrase: Optional[str] = None
    nginx_stream_dir: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = None

    @field_validator("current_ip")
    @classmethod
    def validate_ip(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            ipaddress.ip_address(v)
        return v

    @field_validator("ssh_username")
    @classmethod
    def validate_ssh_username(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _SAFE_USERNAME_RE.match(v):
            raise ValueError("ssh_username contains invalid characters (allowed: a-z A-Z 0-9 _ . -)")
        return v

    @field_validator("nginx_stream_dir")
    @classmethod
    def validate_stream_dir(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _SAFE_PATH_RE.match(v):
            raise ValueError("nginx_stream_dir must be an absolute path with safe characters only")
        return v


class RedirectorOut(BaseModel):
    id: str
    name: str
    current_ip: str
    ssh_port: int
    ssh_username: str
    ssh_private_key: str = "**REDACTED**"
    ssh_key_passphrase: Optional[str] = None  # populated as "**REDACTED**" or None
    nginx_stream_dir: str
    notes: Optional[str]
    status: str
    os_info: Optional[dict] = None
    last_deployed_at: Optional[datetime]
    last_tested_at: Optional[datetime]
    stream_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime]
    owner_id: Optional[int] = None

    model_config = {"from_attributes": True}


class RedirectorListOut(BaseModel):
    redirectors: List[RedirectorOut]
    total: int


# ---------------------------------------------------------------------------
# StreamConfig schemas
# ---------------------------------------------------------------------------

class StreamConfigCreate(BaseModel):
    name: str = Field(..., max_length=255)
    protocol: str = Field(default="tcp", pattern="^(tcp|udp|dns)$")
    listen_port: int = Field(..., ge=1, le=65535)
    cs_ip: str = Field(..., max_length=255)
    cs_port: int = Field(..., ge=1, le=65535)
    access_control_enabled: bool = False
    allowed_cidrs: Optional[List[str]] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if _UNSAFE_NGINX_CHARS.search(v):
            raise ValueError("name must not contain semicolons, newlines, or braces")
        return v

    @field_validator("cs_ip")
    @classmethod
    def validate_cs_ip(cls, v: str) -> str:
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            pass
        if not _SAFE_HOSTNAME_RE.match(v):
            raise ValueError("cs_ip must be a valid IP address or hostname")
        return v

    @field_validator("allowed_cidrs")
    @classmethod
    def validate_cidrs(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        for cidr in v:
            try:
                ipaddress.ip_network(cidr.strip(), strict=False)
            except ValueError:
                raise ValueError(f"Invalid CIDR notation: {cidr!r}")
        return v

    ssl_enabled: bool = False
    ssl_cert_path: Optional[str] = Field(None, max_length=500)
    ssl_key_path: Optional[str] = Field(None, max_length=500)
    ssl_protocols: str = Field(default="TLSv1.2 TLSv1.3", max_length=100)
    ssl_ciphers: str = Field(default="HIGH:!aNULL:!MD5", max_length=200)
    enabled: bool = True

    @field_validator("ssl_cert_path", "ssl_key_path")
    @classmethod
    def validate_ssl_path(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _SAFE_PATH_RE.match(v):
            raise ValueError("SSL path must be an absolute path with safe characters only")
        return v

    @field_validator("ssl_protocols")
    @classmethod
    def validate_ssl_protocols(cls, v: str) -> str:
        for token in v.split():
            if token not in _ALLOWED_SSL_PROTOCOLS:
                raise ValueError(f"Unknown SSL protocol: {token!r}")
        return v

    @field_validator("ssl_ciphers")
    @classmethod
    def validate_ssl_ciphers(cls, v: str) -> str:
        if not _SAFE_CIPHER_RE.match(v):
            raise ValueError("ssl_ciphers contains invalid characters")
        return v


class StreamConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    protocol: Optional[str] = Field(None, pattern="^(tcp|udp|dns)$")
    listen_port: Optional[int] = Field(None, ge=1, le=65535)
    cs_ip: Optional[str] = Field(None, max_length=255)
    cs_port: Optional[int] = Field(None, ge=1, le=65535)
    access_control_enabled: Optional[bool] = None
    allowed_cidrs: Optional[List[str]] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and _UNSAFE_NGINX_CHARS.search(v):
            raise ValueError("name must not contain semicolons, newlines, or braces")
        return v

    @field_validator("cs_ip")
    @classmethod
    def validate_cs_ip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            pass
        if not _SAFE_HOSTNAME_RE.match(v):
            raise ValueError("cs_ip must be a valid IP address or hostname")
        return v

    @field_validator("allowed_cidrs")
    @classmethod
    def validate_cidrs(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        for cidr in v:
            try:
                ipaddress.ip_network(cidr.strip(), strict=False)
            except ValueError:
                raise ValueError(f"Invalid CIDR notation: {cidr!r}")
        return v

    ssl_enabled: Optional[bool] = None
    ssl_cert_path: Optional[str] = Field(None, max_length=500)
    ssl_key_path: Optional[str] = Field(None, max_length=500)
    ssl_protocols: Optional[str] = Field(None, max_length=100)
    ssl_ciphers: Optional[str] = Field(None, max_length=200)
    enabled: Optional[bool] = None

    @field_validator("ssl_cert_path", "ssl_key_path")
    @classmethod
    def validate_ssl_path(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _SAFE_PATH_RE.match(v):
            raise ValueError("SSL path must be an absolute path with safe characters only")
        return v

    @field_validator("ssl_protocols")
    @classmethod
    def validate_ssl_protocols(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            for token in v.split():
                if token not in _ALLOWED_SSL_PROTOCOLS:
                    raise ValueError(f"Unknown SSL protocol: {token!r}")
        return v

    @field_validator("ssl_ciphers")
    @classmethod
    def validate_ssl_ciphers(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _SAFE_CIPHER_RE.match(v):
            raise ValueError("ssl_ciphers contains invalid characters")
        return v


class StreamConfigOut(BaseModel):
    id: str
    redirector_id: str
    name: str
    protocol: str
    listen_port: int
    cs_ip: str
    cs_port: int
    access_control_enabled: bool
    allowed_cidrs: Optional[List[str]]
    ssl_enabled: bool
    ssl_cert_path: Optional[str]
    ssl_key_path: Optional[str]
    ssl_protocols: str
    ssl_ciphers: str
    enabled: bool
    deployed: bool
    filename: str
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# SSH operation request/result schemas
# ---------------------------------------------------------------------------

class CheckPortRequest(BaseModel):
    """Typed request body for the check-port endpoint (replaces untyped dict)."""
    port: int = Field(..., ge=1, le=65535)
    protocol: str = Field(default="tcp", pattern="^(tcp|udp|dns)$")


class DeployResult(BaseModel):
    success: bool
    nginx_test_output: str = ""
    nginx_reload_output: str = ""
    stream_module_present: bool = True
    files_written: List[str] = []
    files_deleted: List[str] = []
    message: str = ""


class TestConnectionResult(BaseModel):
    success: bool
    status: str          # "online" | "offline"
    message: str
    stream_module_present: bool = False
    rtt_ms: Optional[float] = None


class ConfigPreview(BaseModel):
    filename: str
    content: str
