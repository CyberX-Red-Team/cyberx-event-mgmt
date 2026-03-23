"""Pydantic schemas for redirector and stream config management.

Security note: ssh_private_key is ALWAYS returned as "**REDACTED**" in output
schemas. The key is never serialized in API responses, regardless of what is
stored in the database.
"""
import ipaddress
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


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
    last_deployed_at: Optional[datetime]
    last_tested_at: Optional[datetime]
    stream_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime]

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


class StreamConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    protocol: Optional[str] = Field(None, pattern="^(tcp|udp|dns)$")
    listen_port: Optional[int] = Field(None, ge=1, le=65535)
    cs_ip: Optional[str] = Field(None, max_length=255)
    cs_port: Optional[int] = Field(None, ge=1, le=65535)
    access_control_enabled: Optional[bool] = None
    allowed_cidrs: Optional[List[str]] = None

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
    filename: str
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# SSH operation result schemas
# ---------------------------------------------------------------------------

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
