"""Unit tests for redirector Pydantic schemas.

Tests BYOD create validation, from-instance schema, update schema,
and output schema including the instance_id field.
"""
import pytest
from pydantic import ValidationError

from app.schemas.redirector import (
    RedirectorCreate, RedirectorUpdate, RedirectorOut,
    RedirectorFromInstance,
)


VALID_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----"


@pytest.mark.unit
class TestRedirectorCreate:
    """Tests for RedirectorCreate schema validation (BYOD path)."""

    def test_byod_valid(self):
        """BYOD mode: ssh_private_key is required."""
        schema = RedirectorCreate(
            name="redir-01",
            current_ip="198.51.100.1",
            ssh_username="debian",
            ssh_private_key=VALID_PEM,
        )
        assert schema.ssh_private_key == VALID_PEM

    def test_missing_key_rejected(self):
        """Must provide ssh_private_key."""
        with pytest.raises(ValidationError):
            RedirectorCreate(
                name="redir-04",
                current_ip="198.51.100.4",
                ssh_username="debian",
            )

    def test_invalid_host_rejected(self):
        """Hosts with whitespace or shell metacharacters must be rejected."""
        for bad in ("not an ip", "host;rm", "10.0.0.1 | whoami", "bad$host"):
            with pytest.raises(ValidationError, match="not a valid IP address or hostname"):
                RedirectorCreate(
                    name="redir-05",
                    current_ip=bad,
                    ssh_username="debian",
                    ssh_private_key=VALID_PEM,
                )

    def test_fqdn_accepted(self):
        """FQDNs are allowed so redirectors can be reached via DNS."""
        schema = RedirectorCreate(
            name="redir-fqdn",
            current_ip="redir.lab.example.com",
            ssh_username="root",
            ssh_private_key=VALID_PEM,
        )
        assert schema.current_ip == "redir.lab.example.com"

    def test_private_ip_accepted(self):
        """RFC 1918 and loopback addresses are allowed for lab/internal use."""
        for ip in ("10.0.0.1", "192.168.1.1", "172.16.0.1", "127.0.0.1"):
            schema = RedirectorCreate(
                name="redir-priv",
                current_ip=ip,
                ssh_username="debian",
                ssh_private_key=VALID_PEM,
            )
            assert schema.current_ip == ip

    def test_unsafe_username_rejected(self):
        with pytest.raises(ValidationError, match="invalid characters"):
            RedirectorCreate(
                name="redir-06",
                current_ip="198.51.100.6",
                ssh_username="user;rm -rf",
                ssh_private_key=VALID_PEM,
            )

    def test_unsafe_stream_dir_rejected(self):
        with pytest.raises(ValidationError, match="safe characters"):
            RedirectorCreate(
                name="redir-07",
                current_ip="198.51.100.7",
                ssh_username="debian",
                ssh_private_key=VALID_PEM,
                nginx_stream_dir="../etc/passwd",
            )

    def test_defaults(self):
        schema = RedirectorCreate(
            name="redir-08",
            current_ip="198.51.100.8",
            ssh_username="debian",
            ssh_private_key=VALID_PEM,
        )
        assert schema.ssh_port == 22
        assert schema.nginx_stream_dir == "/etc/nginx/stream.d"
        assert schema.notes is None
        assert schema.ssh_key_passphrase is None


@pytest.mark.unit
class TestRedirectorFromInstance:
    """Tests for RedirectorFromInstance schema validation (CyberX path)."""

    def test_valid_minimal(self):
        schema = RedirectorFromInstance(instance_id=42)
        assert schema.instance_id == 42
        assert schema.name is None
        assert schema.nginx_stream_dir == "/etc/nginx/stream.d"

    def test_valid_with_name(self):
        schema = RedirectorFromInstance(instance_id=1, name="my-redir")
        assert schema.name == "my-redir"

    def test_unsafe_stream_dir_rejected(self):
        with pytest.raises(ValidationError, match="safe characters"):
            RedirectorFromInstance(
                instance_id=1,
                nginx_stream_dir="../etc/passwd",
            )


@pytest.mark.unit
class TestRedirectorUpdate:
    """Tests for RedirectorUpdate schema validation."""

    def test_all_fields_optional(self):
        schema = RedirectorUpdate()
        assert schema.name is None

    def test_invalid_ip_rejected(self):
        with pytest.raises(ValidationError):
            RedirectorUpdate(current_ip="bad ip with space")

    def test_update_key_ok(self):
        schema = RedirectorUpdate(ssh_private_key=VALID_PEM)
        assert schema.ssh_private_key == VALID_PEM


@pytest.mark.unit
class TestRedirectorOut:
    """Tests for RedirectorOut response schema."""

    def test_includes_instance_id(self):
        out = RedirectorOut(
            id="abc",
            name="redir",
            current_ip="198.51.100.1",
            ssh_port=22,
            ssh_username="debian",
            use_infrastructure_key=True,
            instance_id=42,
            nginx_stream_dir="/etc/nginx/stream.d",
            notes=None,
            status="online",
            last_deployed_at=None,
            last_tested_at=None,
            created_at="2026-01-01T00:00:00Z",
            updated_at=None,
        )
        assert out.use_infrastructure_key is True
        assert out.instance_id == 42
        assert out.ssh_private_key == "**REDACTED**"

    def test_defaults(self):
        out = RedirectorOut(
            id="abc",
            name="redir",
            current_ip="198.51.100.1",
            ssh_port=22,
            ssh_username="debian",
            nginx_stream_dir="/etc/nginx/stream.d",
            notes=None,
            status="online",
            last_deployed_at=None,
            last_tested_at=None,
            created_at="2026-01-01T00:00:00Z",
            updated_at=None,
        )
        assert out.use_infrastructure_key is False
        assert out.instance_id is None
