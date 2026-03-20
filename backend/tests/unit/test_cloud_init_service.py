"""
Unit tests for CloudInitService.

Tests template rendering and R2 URL placeholder resolution.
"""

import pytest
from unittest.mock import patch, MagicMock

from app.services.cloud_init_service import CloudInitService


class TestRenderTemplate:
    """Tests for CloudInitService.render_template (sync, no DB needed)."""

    def _make_service(self):
        """Create a CloudInitService with a mock session (not used by render_template)."""
        return CloudInitService(session=MagicMock())

    def test_simple_substitution(self):
        svc = self._make_service()
        content = "#cloud-config\nhostname: {{hostname}}"
        result = svc.render_template(content, {"hostname": "test-box"})
        assert "hostname: test-box" in result

    def test_multiple_variables(self):
        svc = self._make_service()
        content = "hostname: {{hostname}}\ntoken: {{license_token}}"
        result = svc.render_template(content, {
            "hostname": "box1",
            "license_token": "abc123",
        })
        assert "hostname: box1" in result
        assert "token: abc123" in result

    def test_unsubstituted_placeholder_warns(self, caplog):
        svc = self._make_service()
        content = "hostname: {{hostname}}\nkey: {{missing_var}}"
        result = svc.render_template(content, {"hostname": "box1"})
        assert "hostname: box1" in result
        assert "Unsubstituted placeholders" in caplog.text
        assert "missing_var" in caplog.text

    def test_removes_empty_list_items(self):
        svc = self._make_service()
        content = "ssh_authorized_keys:\n  - {{ssh_public_key}}"
        result = svc.render_template(content, {})
        # Both the empty list item and its parent key should be removed
        assert "ssh_authorized_keys" not in result

    def test_r2_url_placeholder_not_flagged_as_unsubstituted(self, caplog):
        """{{r2_url:...}} uses a colon, so it should NOT match the \\w+ warning regex."""
        svc = self._make_service()
        content = "url: {{r2_url:tools/agent.tar.gz}}"
        svc.render_template(content, {})
        assert "Unsubstituted placeholders" not in caplog.text


class TestResolveR2UrlPlaceholders:
    """Tests for CloudInitService.resolve_r2_url_placeholders (static method)."""

    @patch("app.services.download_service.DownloadService")
    @patch("app.config.get_settings")
    def test_single_placeholder(self, mock_settings, mock_dl_cls):
        mock_settings.return_value.CLOUD_INIT_LINK_EXPIRY = 14400
        mock_dl = mock_dl_cls.return_value
        mock_dl.generate_link.return_value = "https://r2.example.com/signed/agent.deb"

        content = 'curl -o /tmp/agent.deb "{{r2_url:packages/agent.deb}}"'
        result = CloudInitService.resolve_r2_url_placeholders(content)

        assert "https://r2.example.com/signed/agent.deb" in result
        assert "{{r2_url:" not in result
        mock_dl.generate_link.assert_called_once_with("packages/agent.deb", 14400)

    @patch("app.services.download_service.DownloadService")
    @patch("app.config.get_settings")
    def test_multiple_placeholders(self, mock_settings, mock_dl_cls):
        mock_settings.return_value.CLOUD_INIT_LINK_EXPIRY = 14400
        mock_dl = mock_dl_cls.return_value
        mock_dl.generate_link.side_effect = lambda key, _: f"https://signed/{key}"

        content = (
            'curl "{{r2_url:tools/linux/agent.tar.gz}}"\n'
            'curl "{{r2_url:scripts/setup.sh}}"'
        )
        result = CloudInitService.resolve_r2_url_placeholders(content)

        assert "https://signed/tools/linux/agent.tar.gz" in result
        assert "https://signed/scripts/setup.sh" in result
        assert "{{r2_url:" not in result
        assert mock_dl.generate_link.call_count == 2

    @patch("app.services.download_service.DownloadService")
    @patch("app.config.get_settings")
    def test_duplicate_paths_cached(self, mock_settings, mock_dl_cls):
        mock_settings.return_value.CLOUD_INIT_LINK_EXPIRY = 14400
        mock_dl = mock_dl_cls.return_value
        mock_dl.generate_link.return_value = "https://signed/agent.deb"

        content = (
            'curl "{{r2_url:packages/agent.deb}}"\n'
            'echo "{{r2_url:packages/agent.deb}}"'
        )
        result = CloudInitService.resolve_r2_url_placeholders(content)

        assert result.count("https://signed/agent.deb") == 2
        # generate_link should only be called once for the same key
        mock_dl.generate_link.assert_called_once()

    def test_no_placeholders_passthrough(self):
        content = "hostname: test-box\nruncmd:\n  - echo hello"
        result = CloudInitService.resolve_r2_url_placeholders(content)

        assert result == content

    @patch("app.services.download_service.DownloadService")
    @patch("app.config.get_settings")
    def test_missing_r2_config_leaves_placeholder(self, mock_settings, mock_dl_cls, caplog):
        mock_settings.return_value.CLOUD_INIT_LINK_EXPIRY = 14400
        mock_dl = mock_dl_cls.return_value
        mock_dl.generate_link.side_effect = ValueError("R2 not configured")

        content = 'curl "{{r2_url:packages/agent.deb}}"'
        result = CloudInitService.resolve_r2_url_placeholders(content)

        # Placeholder should remain since URL generation failed
        assert "{{r2_url:packages/agent.deb}}" in result
        assert "Failed to generate presigned URL" in caplog.text

    @patch("app.services.download_service.DownloadService")
    @patch("app.config.get_settings")
    def test_custom_expiry(self, mock_settings, mock_dl_cls):
        mock_settings.return_value.CLOUD_INIT_LINK_EXPIRY = 14400
        mock_dl = mock_dl_cls.return_value
        mock_dl.generate_link.return_value = "https://signed/file"

        content = 'curl "{{r2_url:file.tar.gz}}"'
        CloudInitService.resolve_r2_url_placeholders(content, expires_in=7200)

        mock_dl.generate_link.assert_called_once_with("file.tar.gz", 7200)

    @patch("app.services.download_service.DownloadService")
    @patch("app.config.get_settings")
    def test_nested_directory_path(self, mock_settings, mock_dl_cls):
        """Ensure deeply nested R2 keys work (slashes in path)."""
        mock_settings.return_value.CLOUD_INIT_LINK_EXPIRY = 14400
        mock_dl = mock_dl_cls.return_value
        mock_dl.generate_link.return_value = "https://signed/deep/path"

        content = 'curl "{{r2_url:events/cyberx-2026/tools/linux/amd64/agent.tar.gz}}"'
        result = CloudInitService.resolve_r2_url_placeholders(content)

        assert "https://signed/deep/path" in result
        mock_dl.generate_link.assert_called_once_with(
            "events/cyberx-2026/tools/linux/amd64/agent.tar.gz", 14400
        )

    @patch("app.services.download_service.DownloadService")
    @patch("app.config.get_settings")
    def test_partial_failure_resolves_successful_ones(self, mock_settings, mock_dl_cls, caplog):
        """If one URL fails, others should still resolve."""
        mock_settings.return_value.CLOUD_INIT_LINK_EXPIRY = 14400
        mock_dl = mock_dl_cls.return_value

        def side_effect(key, _):
            if key == "bad/file":
                raise ValueError("not found")
            return f"https://signed/{key}"

        mock_dl.generate_link.side_effect = side_effect

        content = (
            'curl "{{r2_url:good/file}}"\n'
            'curl "{{r2_url:bad/file}}"'
        )
        result = CloudInitService.resolve_r2_url_placeholders(content)

        assert "https://signed/good/file" in result
        assert "{{r2_url:bad/file}}" in result  # Failed one stays
        assert "Failed to generate presigned URL" in caplog.text
