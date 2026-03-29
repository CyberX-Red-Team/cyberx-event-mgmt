"""Integration tests for SSHService against a real Docker mock-redirector.

Requires the mock-redirector Docker container to be running on localhost:2222.
Run via: bash tests/docker/run_tests.sh

Environment variables:
    TEST_SSH_KEY_PATH  — path to the test private key (default: /tmp/test_ssh_key)
    TEST_SSH_HOST      — hostname of mock redirector (default: localhost)
    TEST_SSH_PORT      — SSH port (default: 2222)
    TEST_SSH_USER      — SSH username (default: cyberx)
"""
import os
import pytest

from app.services.ssh_service import SSHService


# Read config from environment
SSH_KEY_PATH = os.environ.get("TEST_SSH_KEY_PATH", "/tmp/test_ssh_key")
SSH_HOST = os.environ.get("TEST_SSH_HOST", "localhost")
SSH_PORT = int(os.environ.get("TEST_SSH_PORT", "2222"))
SSH_USER = os.environ.get("TEST_SSH_USER", "cyberx")


def _read_key():
    """Read the test SSH private key from disk."""
    with open(SSH_KEY_PATH, "r") as f:
        return f.read()


def _make_service():
    """Create an SSHService pointing at the Docker mock-redirector."""
    return SSHService(
        hostname=SSH_HOST,
        port=SSH_PORT,
        username=SSH_USER,
        private_key_pem=_read_key(),
    )


@pytest.mark.integration
@pytest.mark.ssh
class TestRealSSHConnection:
    """Tests that require a running mock-redirector Docker container."""

    def test_test_connection(self):
        ssh = _make_service()
        result = ssh.sync_test_connection()
        assert result["success"] is True
        assert result["status"] == "online"
        assert "os_info" in result

    def test_deploy_infra_key(self):
        ssh = _make_service()
        # Use a unique dummy key to avoid conflicts
        dummy_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestInfraKeyForIntegration test@integration"
        result = ssh.sync_deploy_infra_key(dummy_key)
        assert result["deployed"] is True or result["already_present"] is True

    def test_deploy_infra_key_idempotent(self):
        ssh = _make_service()
        dummy_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIdempotentTestKey test@idempotent"
        # Deploy once
        result1 = ssh.sync_deploy_infra_key(dummy_key)
        assert result1["deployed"] is True or result1["already_present"] is True
        # Deploy again — should be already_present
        result2 = ssh.sync_deploy_infra_key(dummy_key)
        assert result2["already_present"] is True

    def test_check_port_not_in_use(self):
        ssh = _make_service()
        result = ssh.sync_check_port(59999, "tcp")
        assert result["in_use"] is False

    def test_check_nginx_setup(self):
        ssh = _make_service()
        result = ssh.sync_check_nginx_setup()
        assert "stream_block" in result or "checks" in result

    def test_check_prereqs(self):
        ssh = _make_service()
        result = ssh.sync_check_prereqs("/etc/nginx/stream.d")
        assert isinstance(result, dict)
