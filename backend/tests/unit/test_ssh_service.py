"""Unit tests for SSHService with paramiko fully mocked.

Tests the logic of key loading, command construction, error mapping,
and infrastructure key deployment without any network I/O.
"""
import io
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from app.services.ssh_service import (
    SSHService,
    SSHConnectionError,
    SSHAuthError,
)


VALID_RSA_PEM = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8PbnGy0AHB7MhgHcTz6sEfN
-----END RSA PRIVATE KEY-----"""

VALID_ED25519_PEM = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAAB
-----END OPENSSH PRIVATE KEY-----"""


@pytest.mark.unit
class TestSSHServiceInit:
    """Test SSHService initialization."""

    def test_basic_init(self):
        svc = SSHService(
            hostname="10.0.0.1",
            port=22,
            username="debian",
            private_key_pem=VALID_ED25519_PEM,
        )
        assert svc.hostname == "10.0.0.1"
        assert svc.port == 22
        assert svc.username == "debian"

    def test_sudo_prefix_nonroot(self):
        svc = SSHService(
            hostname="10.0.0.1",
            port=22,
            username="debian",
            private_key_pem=VALID_ED25519_PEM,
        )
        assert svc._sudo_prefix == "sudo "

    def test_sudo_prefix_root(self):
        svc = SSHService(
            hostname="10.0.0.1",
            port=22,
            username="root",
            private_key_pem=VALID_ED25519_PEM,
        )
        assert svc._sudo_prefix == ""


@pytest.mark.unit
class TestSSHServiceConnect:
    """Test SSH connection logic with mocked paramiko."""

    @patch("app.services.ssh_service.paramiko.SSHClient")
    def test_connect_success(self, mock_ssh_class):
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        svc = SSHService(
            hostname="10.0.0.1",
            port=22,
            username="debian",
            private_key_pem=VALID_ED25519_PEM,
        )

        # Mock _load_key so that the fake PEM is not parsed by paramiko
        svc._load_key = MagicMock(return_value=MagicMock())

        # _connect calls paramiko.SSHClient().connect(...)
        client = svc._connect()
        assert mock_client.connect.called

    @patch("app.services.ssh_service.paramiko.SSHClient")
    def test_connect_auth_failure(self, mock_ssh_class):
        import paramiko
        mock_client = MagicMock()
        mock_client.connect.side_effect = paramiko.AuthenticationException("Bad key")
        mock_ssh_class.return_value = mock_client

        svc = SSHService(
            hostname="10.0.0.1",
            port=22,
            username="debian",
            private_key_pem=VALID_ED25519_PEM,
        )

        with pytest.raises(SSHAuthError):
            svc._connect()

    @patch("app.services.ssh_service.paramiko.SSHClient")
    def test_connect_network_failure(self, mock_ssh_class):
        mock_client = MagicMock()
        mock_client.connect.side_effect = OSError("Connection refused")
        mock_ssh_class.return_value = mock_client

        svc = SSHService(
            hostname="10.0.0.1",
            port=22,
            username="debian",
            private_key_pem=VALID_ED25519_PEM,
        )

        # Mock _load_key so that the fake PEM is not parsed by paramiko
        svc._load_key = MagicMock(return_value=MagicMock())

        with pytest.raises(SSHConnectionError):
            svc._connect()


@pytest.mark.unit
class TestSSHServiceDeployInfraKey:
    """Test infrastructure key deployment logic."""

    @patch("app.services.ssh_service.paramiko.SSHClient")
    def test_key_already_present(self, mock_ssh_class):
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        # Mock _exec to return code 0 (key found in grep)
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 0

        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""

        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        svc = SSHService(
            hostname="10.0.0.1",
            port=22,
            username="debian",
            private_key_pem=VALID_ED25519_PEM,
        )

        # Patch _connect and _exec directly for simpler testing
        svc._connect = MagicMock(return_value=mock_client)
        svc._exec = MagicMock(return_value=("", "", 0))

        result = svc.sync_deploy_infra_key("ssh-ed25519 AAAAC3... user@host")
        assert result["already_present"] is True
        assert result["deployed"] is False

    @patch("app.services.ssh_service.paramiko.SSHClient")
    def test_key_deployed_successfully(self, mock_ssh_class):
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp

        svc = SSHService(
            hostname="10.0.0.1",
            port=22,
            username="debian",
            private_key_pem=VALID_ED25519_PEM,
        )

        svc._connect = MagicMock(return_value=mock_client)

        # First call: grep check returns 1 (not found)
        # Subsequent calls: mkdir, chmod, cat, cp, rm, chmod - all succeed
        call_count = [0]
        def mock_exec(client, cmd):
            call_count[0] += 1
            if call_count[0] == 1:
                return ("", "", 1)  # grep: not found
            return ("", "", 0)  # everything else succeeds

        svc._exec = mock_exec

        result = svc.sync_deploy_infra_key("ssh-ed25519 AAAAC3... user@host")
        assert result["already_present"] is False
        assert result["deployed"] is True
        # SFTP should have been used to write the tmp file
        assert mock_sftp.putfo.called
