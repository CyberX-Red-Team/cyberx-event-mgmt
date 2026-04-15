"""Unit tests for nginx stream config text generator.

These are pure-Python tests — no DB, no SSH. The generator is called with
a lightweight stand-in object that exposes the same attributes as the
StreamConfig ORM model.
"""
from types import SimpleNamespace

import pytest

from app.services.nginx_config_service import (
    generate_stream_config,
    validate_custom_override,
)


def _make_stream(**overrides):
    """Build a minimal StreamConfig-shaped object for the generator."""
    defaults = dict(
        id="abc123",
        name="test-stream",
        protocol="tcp",
        listen_port=443,
        cs_ip="10.0.0.5",
        cs_port=443,
        access_control_enabled=False,
        allowed_cidrs=None,
        ssl_enabled=False,
        ssl_cert_path=None,
        ssl_key_path=None,
        ssl_protocols="TLSv1.2 TLSv1.3",
        ssl_ciphers="HIGH:!aNULL:!MD5",
        custom_config_override=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
class TestGeneratorPlainTcp:
    def test_plain_tcp_has_proxy_pass_and_no_ssl(self):
        s = _make_stream(listen_port=8080, cs_port=8080)
        out = generate_stream_config(s)
        assert "listen 8080;" in out
        assert "proxy_pass 10.0.0.5:8080;" in out
        assert "ssl_certificate" not in out
        assert "proxy_ssl" not in out
        assert out.startswith("# CyberX Managed - test-stream")
        assert out.endswith("\n")


@pytest.mark.unit
class TestGeneratorTlsBridging:
    def test_tls_bridging_emits_proxy_ssl_on(self):
        """Regression: bridging requires proxy_ssl on; to re-encrypt upstream.

        Without this directive nginx sends plaintext to the upstream TLS
        listener and the connection is dropped immediately.
        """
        s = _make_stream(
            ssl_enabled=True,
            ssl_cert_path="/etc/ssl/certs/legit.pem",
            ssl_key_path="/etc/ssl/private/legit.key",
        )
        out = generate_stream_config(s)
        assert "listen 443 ssl;" in out
        assert "ssl_certificate /etc/ssl/certs/legit.pem;" in out
        assert "ssl_certificate_key /etc/ssl/private/legit.key;" in out
        assert "proxy_ssl on;" in out
        assert "proxy_ssl_verify off;" in out

    def test_ssl_enabled_without_paths_falls_back_to_plain_tcp(self):
        s = _make_stream(ssl_enabled=True, ssl_cert_path=None, ssl_key_path=None)
        out = generate_stream_config(s)
        assert "listen 443;" in out
        assert "ssl" not in out.lower().replace("# cyberx", "")

    def test_udp_ignores_ssl_block(self):
        s = _make_stream(
            protocol="udp",
            listen_port=500,
            cs_port=500,
            ssl_enabled=True,
            ssl_cert_path="/etc/ssl/certs/x.pem",
            ssl_key_path="/etc/ssl/private/x.key",
        )
        out = generate_stream_config(s)
        assert "listen 500 udp reuseport;" in out
        assert "ssl_certificate" not in out
        assert "proxy_ssl" not in out


@pytest.mark.unit
class TestGeneratorDnsAndAcl:
    def test_dns_adds_proxy_responses(self):
        s = _make_stream(protocol="dns", listen_port=53, cs_port=53)
        out = generate_stream_config(s)
        assert "listen 53 udp reuseport;" in out
        assert "proxy_responses 1;" in out

    def test_acl_emits_allow_and_deny(self):
        s = _make_stream(
            access_control_enabled=True,
            allowed_cidrs=["10.0.0.0/8", "192.168.1.42"],
        )
        out = generate_stream_config(s)
        assert "allow 10.0.0.0/8;" in out
        assert "allow 192.168.1.42;" in out
        assert "deny all;" in out


@pytest.mark.unit
class TestGeneratorCustomOverride:
    def test_override_returned_verbatim(self):
        body = "server {\n    listen 9999;\n    proxy_pass 1.2.3.4:9999;\n}\n"
        s = _make_stream(custom_config_override=body)
        out = generate_stream_config(s)
        assert out == body  # exact match, no wrapping, no timestamps

    def test_override_gets_trailing_newline_if_missing(self):
        body = "server { listen 9999; proxy_pass 1.2.3.4:9999; }"  # no \n
        s = _make_stream(custom_config_override=body)
        out = generate_stream_config(s)
        assert out.endswith("\n")
        assert out.rstrip("\n") == body

    def test_override_skips_structured_field_rendering(self):
        """When override is set, cs_ip/listen_port/etc. from fields MUST NOT
        leak into the output — the override is authoritative."""
        body = "server { listen 7777; proxy_pass 9.9.9.9:7777; }\n"
        s = _make_stream(
            listen_port=443,
            cs_ip="10.0.0.5",
            cs_port=443,
            custom_config_override=body,
        )
        out = generate_stream_config(s)
        assert "10.0.0.5" not in out
        assert "443" not in out
        assert "9.9.9.9:7777" in out

    def test_empty_override_falls_through_to_generated(self):
        """Empty string is treated as 'no override' so the structured path runs."""
        s = _make_stream(custom_config_override="")
        out = generate_stream_config(s)
        assert "# CyberX Managed - test-stream" in out
        assert "proxy_pass 10.0.0.5:443;" in out


@pytest.mark.unit
class TestValidateCustomOverride:
    def test_accepts_minimal_server_block(self):
        validate_custom_override("server {\n    listen 443;\n    proxy_pass 1.2.3.4:443;\n}\n")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_custom_override("")

    def test_rejects_null_byte(self):
        with pytest.raises(ValueError, match="null byte"):
            validate_custom_override("server {\x00}")

    def test_rejects_missing_server_block(self):
        with pytest.raises(ValueError, match="server"):
            validate_custom_override("# just a comment, no server block")

    def test_rejects_unbalanced_extra_close(self):
        with pytest.raises(ValueError, match="unbalanced"):
            validate_custom_override("server { listen 443; } }")

    def test_rejects_unbalanced_missing_close(self):
        with pytest.raises(ValueError, match="unbalanced"):
            validate_custom_override("server { listen 443;")

    def test_ignores_braces_in_comment_lines(self):
        # Bare '}' inside a comment line must not throw off the balance counter.
        text = "# here is a stray } in a comment\nserver {\n    listen 443;\n}\n"
        validate_custom_override(text)

    def test_rejects_oversized(self):
        big = "server {\n" + ("# padding\n" * 5000) + "}\n"
        with pytest.raises(ValueError, match="exceeds"):
            validate_custom_override(big)

    def test_accepts_realistic_tls_bridging_block(self):
        text = """# CyberX Managed - prod-c2
server {
    listen 443 ssl;
    proxy_pass 10.32.88.189:443;
    proxy_connect_timeout 60s;
    proxy_timeout 10m;
    ssl_certificate /etc/ssl/certs/legit.pem;
    ssl_certificate_key /etc/ssl/private/legit.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    proxy_ssl on;
    proxy_ssl_verify off;
}
"""
        validate_custom_override(text)
