"""Unit tests for redirector Pydantic schemas.

Tests validation logic including the infrastructure key mutual exclusion
and field validators for IP, username, and path safety.
"""
import pytest
from pydantic import ValidationError

from app.schemas.redirector import RedirectorCreate, RedirectorUpdate, RedirectorOut


VALID_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----"


@pytest.mark.unit
class TestRedirectorCreate:
    """Tests for RedirectorCreate schema validation."""

    def test_byod_valid(self):
        """BYOD mode: ssh_private_key required, use_infrastructure_key=False."""
        schema = RedirectorCreate(
            name="redir-01",
            current_ip="10.0.0.1",
            ssh_username="debian",
            ssh_private_key=VALID_PEM,
        )
        assert schema.use_infrastructure_key is False
        assert schema.ssh_private_key == VALID_PEM

    def test_infra_key_valid(self):
        """Infra key mode: no ssh_private_key, use_infrastructure_key=True."""
        schema = RedirectorCreate(
            name="redir-02",
            current_ip="10.0.0.2",
            ssh_username="debian",
            use_infrastructure_key=True,
        )
        assert schema.use_infrastructure_key is True
        assert schema.ssh_private_key is None

    def test_both_key_and_infra_flag_rejected(self):
        """Cannot provide ssh_private_key AND use_infrastructure_key=True."""
        with pytest.raises(ValidationError, match="Cannot provide ssh_private_key"):
            RedirectorCreate(
                name="redir-03",
                current_ip="10.0.0.3",
                ssh_username="debian",
                use_infrastructure_key=True,
                ssh_private_key=VALID_PEM,
            )

    def test_neither_key_nor_infra_flag_rejected(self):
        """Must provide either ssh_private_key OR use_infrastructure_key=True."""
        with pytest.raises(ValidationError, match="ssh_private_key is required"):
            RedirectorCreate(
                name="redir-04",
                current_ip="10.0.0.4",
                ssh_username="debian",
            )

    def test_invalid_ip_rejected(self):
        with pytest.raises(ValidationError):
            RedirectorCreate(
                name="redir-05",
                current_ip="not-an-ip",
                ssh_username="debian",
                ssh_private_key=VALID_PEM,
            )

    def test_unsafe_username_rejected(self):
        with pytest.raises(ValidationError, match="invalid characters"):
            RedirectorCreate(
                name="redir-06",
                current_ip="10.0.0.6",
                ssh_username="user;rm -rf",
                ssh_private_key=VALID_PEM,
            )

    def test_unsafe_stream_dir_rejected(self):
        with pytest.raises(ValidationError, match="safe characters"):
            RedirectorCreate(
                name="redir-07",
                current_ip="10.0.0.7",
                ssh_username="debian",
                ssh_private_key=VALID_PEM,
                nginx_stream_dir="../etc/passwd",
            )

    def test_defaults(self):
        schema = RedirectorCreate(
            name="redir-08",
            current_ip="10.0.0.8",
            ssh_username="debian",
            ssh_private_key=VALID_PEM,
        )
        assert schema.ssh_port == 22
        assert schema.nginx_stream_dir == "/etc/nginx/stream.d"
        assert schema.notes is None
        assert schema.ssh_key_passphrase is None


@pytest.mark.unit
class TestRedirectorUpdate:
    """Tests for RedirectorUpdate schema validation."""

    def test_switching_to_infra_with_key_rejected(self):
        """Cannot provide ssh_private_key when switching to infra mode."""
        with pytest.raises(ValidationError, match="Cannot provide ssh_private_key"):
            RedirectorUpdate(
                use_infrastructure_key=True,
                ssh_private_key=VALID_PEM,
            )

    def test_switching_to_infra_without_key_ok(self):
        schema = RedirectorUpdate(use_infrastructure_key=True)
        assert schema.use_infrastructure_key is True

    def test_switching_to_byod_with_key_ok(self):
        schema = RedirectorUpdate(
            use_infrastructure_key=False,
            ssh_private_key=VALID_PEM,
        )
        assert schema.use_infrastructure_key is False
        assert schema.ssh_private_key == VALID_PEM

    def test_all_fields_optional(self):
        schema = RedirectorUpdate()
        assert schema.name is None
        assert schema.use_infrastructure_key is None

    def test_invalid_ip_rejected(self):
        with pytest.raises(ValidationError):
            RedirectorUpdate(current_ip="bad-ip")


@pytest.mark.unit
class TestRedirectorOut:
    """Tests for RedirectorOut response schema."""

    def test_includes_use_infrastructure_key(self):
        out = RedirectorOut(
            id="abc",
            name="redir",
            current_ip="10.0.0.1",
            ssh_port=22,
            ssh_username="debian",
            use_infrastructure_key=True,
            nginx_stream_dir="/etc/nginx/stream.d",
            notes=None,
            status="online",
            last_deployed_at=None,
            last_tested_at=None,
            created_at="2026-01-01T00:00:00Z",
            updated_at=None,
        )
        assert out.use_infrastructure_key is True
        assert out.ssh_private_key == "**REDACTED**"

    def test_defaults_to_false(self):
        out = RedirectorOut(
            id="abc",
            name="redir",
            current_ip="10.0.0.1",
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
