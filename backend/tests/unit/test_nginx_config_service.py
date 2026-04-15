"""Unit tests for nginx stream config text generator.

These are pure-Python tests — no DB, no SSH. The generator is called with
a lightweight stand-in object that exposes the same attributes as the
StreamConfig ORM model.
"""
from types import SimpleNamespace

import pytest

from app.services.nginx_config_service import (
    generate_stream_config,
    generate_sni_router_config,
    generate_decoy_http_config,
    generate_decoy_html,
    generate_decoy_cert_shell_command,
    validate_custom_override,
    SNI_BRIDGE_PORT_MIN,
    SNI_BRIDGE_PORT_MAX,
    SNI_DECOY_PORT,
    SNI_LOOPBACK_IP,
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
        sni_hostname=None,
        internal_bridge_port=None,
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


# ---------------------------------------------------------------------------
# SNI routing — inner terminator branch
# ---------------------------------------------------------------------------

def _make_sni_stream(**overrides):
    """Valid SNI-routed stream with all required fields populated."""
    defaults = dict(
        sni_hostname="beacon.example.com",
        internal_bridge_port=10001,
        ssl_enabled=True,
        ssl_cert_path="/etc/ssl/certs/legit.pem",
        ssl_key_path="/etc/ssl/private/legit.key",
    )
    defaults.update(overrides)
    return _make_stream(**defaults)


@pytest.mark.unit
class TestSniInnerTerminator:
    def test_inner_terminator_binds_loopback(self):
        s = _make_sni_stream()
        out = generate_stream_config(s)
        assert f"listen {SNI_LOOPBACK_IP}:10001 ssl;" in out
        # Must NOT listen on a public interface or the public listen_port
        assert "listen 443" not in out
        # Should still bridge with proxy_ssl on — inner terminator still
        # re-encrypts to the CS teamserver's self-signed cert
        assert "proxy_ssl on;" in out
        assert "proxy_ssl_verify off;" in out
        assert "proxy_pass 10.0.0.5:443;" in out
        assert "ssl_certificate /etc/ssl/certs/legit.pem;" in out

    def test_inner_terminator_header_mentions_sni(self):
        s = _make_sni_stream()
        out = generate_stream_config(s)
        assert "SNI inner terminator for beacon.example.com" in out

    def test_sni_stream_requires_bridge_port(self):
        s = _make_sni_stream(internal_bridge_port=None)
        with pytest.raises(ValueError, match="internal_bridge_port"):
            generate_stream_config(s)

    def test_sni_stream_requires_cert_paths(self):
        s = _make_sni_stream(ssl_cert_path=None)
        with pytest.raises(ValueError, match="ssl_cert_path"):
            generate_stream_config(s)

    def test_sni_stream_rejects_bridge_port_out_of_range(self):
        s = _make_sni_stream(internal_bridge_port=9999)
        with pytest.raises(ValueError, match="outside allowed range"):
            generate_stream_config(s)

    def test_sni_stream_rejects_invalid_hostname(self):
        s = _make_sni_stream(sni_hostname="not a hostname with spaces")
        with pytest.raises(ValueError, match="Invalid sni_hostname"):
            generate_stream_config(s)

    def test_override_wins_over_sni_routing(self):
        """Custom override bypasses everything including SNI rendering."""
        s = _make_sni_stream(custom_config_override="server { listen 9999; }\n")
        out = generate_stream_config(s)
        assert out == "server { listen 9999; }\n"
        assert "10001" not in out  # no bridge port leakage


# ---------------------------------------------------------------------------
# SNI router (outer preread)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSniRouterConfig:
    def test_router_has_map_and_preread(self):
        s1 = _make_sni_stream(sni_hostname="beacon.example.com", internal_bridge_port=10001, id="s1")
        s2 = _make_sni_stream(sni_hostname="c2.example.net", internal_bridge_port=10002, id="s2")
        out = generate_sni_router_config(443, [s1, s2])
        assert "map $ssl_preread_server_name $cyberx_p443_backend" in out
        assert f"default {SNI_LOOPBACK_IP}:{SNI_DECOY_PORT};" in out
        assert f"beacon.example.com {SNI_LOOPBACK_IP}:10001;" in out
        assert f"c2.example.net {SNI_LOOPBACK_IP}:10002;" in out
        assert "listen 443;" in out
        assert "ssl_preread on;" in out
        assert "proxy_pass $cyberx_p443_backend;" in out
        # Router MUST NOT carry its own ssl_certificate — preread doesn't
        # terminate; the inner blocks do.
        assert "ssl_certificate" not in out

    def test_router_sorts_hostnames_deterministically(self):
        s1 = _make_sni_stream(sni_hostname="zebra.example.com", internal_bridge_port=10010, id="s1")
        s2 = _make_sni_stream(sni_hostname="alpha.example.com", internal_bridge_port=10020, id="s2")
        out = generate_sni_router_config(443, [s1, s2])
        alpha_pos = out.index("alpha.example.com")
        zebra_pos = out.index("zebra.example.com")
        assert alpha_pos < zebra_pos

    def test_router_empty_streams_raises(self):
        with pytest.raises(ValueError, match="no SNI streams"):
            generate_sni_router_config(443, [])

    def test_router_rejects_stream_without_bridge_port(self):
        s = _make_sni_stream(internal_bridge_port=None, id="s1")
        with pytest.raises(ValueError, match="internal_bridge_port"):
            generate_sni_router_config(443, [s])

    def test_router_includes_outer_acl_when_any_stream_has_it(self):
        s = _make_sni_stream(
            id="s1",
            access_control_enabled=True,
            allowed_cidrs=["10.0.0.0/8", "1.2.3.4"],
        )
        out = generate_sni_router_config(443, [s])
        assert "allow 10.0.0.0/8;" in out
        assert "allow 1.2.3.4;" in out
        assert "deny all;" in out

    def test_router_deduplicates_by_hostname(self):
        # If the same hostname somehow appears twice (DB unique constraint
        # should prevent this, but we dedupe defensively), the router should
        # keep only one map entry.
        s1 = _make_sni_stream(sni_hostname="dup.example.com", internal_bridge_port=10001, id="s1")
        s2 = _make_sni_stream(sni_hostname="dup.example.com", internal_bridge_port=10002, id="s2")
        out = generate_sni_router_config(443, [s1, s2])
        assert out.count("dup.example.com") == 1
        # First one wins, so 10001 should be the bridge port
        assert f"{SNI_LOOPBACK_IP}:10001" in out
        assert f"{SNI_LOOPBACK_IP}:10002" not in out

    def test_router_rejects_listen_port_out_of_range(self):
        s = _make_sni_stream(id="s1")
        with pytest.raises(ValueError, match="listen_port"):
            generate_sni_router_config(0, [s])
        with pytest.raises(ValueError, match="listen_port"):
            generate_sni_router_config(99999, [s])


# ---------------------------------------------------------------------------
# Decoy http server + HTML + self-signed cert helper
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDecoyHttpConfig:
    def test_decoy_conf_binds_loopback_only(self):
        out = generate_decoy_http_config()
        assert f"listen {SNI_LOOPBACK_IP}:{SNI_DECOY_PORT} ssl;" in out
        # Must NOT bind 0.0.0.0 or a public interface
        assert "listen 0.0.0.0" not in out
        assert "listen *" not in out

    def test_decoy_conf_returns_503(self):
        out = generate_decoy_http_config()
        assert "return 503 '" in out
        assert "default_type text/html;" in out

    def test_decoy_conf_references_cert_paths(self):
        out = generate_decoy_http_config()
        assert "ssl_certificate /etc/nginx/cyberx/decoy.crt;" in out
        assert "ssl_certificate_key /etc/nginx/cyberx/decoy.key;" in out


@pytest.mark.unit
class TestDecoyHtml:
    def test_decoy_html_has_maintenance_and_flags(self):
        html = generate_decoy_html()
        assert "Maintenance Mode" in html
        assert "Blue Team" in html
        assert "turning it off and on again" in html
        assert "@rtm" in html
        assert "CyberX Network Grand Master" in html
        # Both inline SVG flags
        assert "United States flag" in html
        assert "Canadian flag" in html
        # No external network references. The SVG xmlns
        # (http://www.w3.org/2000/svg) is a namespace identifier, not a
        # fetchable resource — strip it before checking.
        stripped = html.replace('xmlns="http://www.w3.org/2000/svg"', "")
        assert "http://" not in stripped
        assert "https://" not in stripped

    def test_decoy_html_no_single_quotes(self):
        """Decoy HTML is embedded in nginx `return 503 '...'`. Raw single
        quotes in the HTML would close the string early — ensure none exist.
        """
        html = generate_decoy_html()
        assert "'" not in html, "decoy HTML must use &#39; not raw single quotes"


@pytest.mark.unit
class TestDecoyCertShellCommand:
    def test_cert_cmd_idempotent(self):
        """Must short-circuit when cert files already exist."""
        cmd = generate_decoy_cert_shell_command()
        assert "[ ! -f" in cmd
        assert "openssl req -x509" in cmd
        assert "-nodes" in cmd
        assert "mkdir -p" in cmd

    def test_cert_cmd_uses_quoted_paths(self):
        cmd = generate_decoy_cert_shell_command()
        assert "'/etc/nginx/cyberx'" in cmd
        assert "'/etc/nginx/cyberx/decoy.crt'" in cmd
        assert "'/etc/nginx/cyberx/decoy.key'" in cmd

    def test_cert_cmd_refuses_unsafe_overrides(self):
        """_sh quoting raises on shell-unsafe characters."""
        with pytest.raises(ValueError, match="unsafe"):
            generate_decoy_cert_shell_command(cert_path="/tmp/a;rm -rf /")
