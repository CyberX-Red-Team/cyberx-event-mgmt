"""Pure-Python nginx stream config file text generator.

No I/O — only produces text. The SSH service is responsible for writing
the generated text to the remote redirector.

Each StreamConfig produces a single server {} block written to:
    <nginx_stream_dir>/cyberx_<stream_id>.conf

The outer  stream { include ...; }  block is assumed to already exist in
nginx.conf, configured by the operator. This service never touches nginx.conf.
"""
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.redirector import StreamConfig


_UNSAFE_NGINX_CHARS = frozenset("\n\r;{}")


def _safe_nginx_value(val: str, field_name: str) -> str:
    """Defense-in-depth: reject values that could break out of an nginx directive."""
    if any(c in _UNSAFE_NGINX_CHARS for c in val):
        raise ValueError(f"Unsafe character in {field_name}: {val!r}")
    return val


def generate_stream_config(stream: "StreamConfig") -> str:
    """
    Generate the content of a single nginx stream .conf file for a StreamConfig.

    Returns the complete text for cyberx_<stream_id>.conf.
    The file contains one server {} block — no outer stream {} wrapper.

    Protocol behaviour:
        tcp  — plain TCP proxy; optionally with SSL termination
        udp  — UDP proxy with reuseport
        dns  — UDP on any port, adds proxy_responses 1 (correct for DNS)
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    protocol = (stream.protocol or "tcp").lower()
    is_dns = protocol == "dns"
    is_udp = protocol in ("udp", "dns")

    # Defense-in-depth: validate all interpolated values
    safe_name = _safe_nginx_value(stream.name, "name")
    safe_cs_ip = _safe_nginx_value(stream.cs_ip, "cs_ip")

    lines: list[str] = [
        f"# CyberX Managed - {safe_name}",
        f"# Generated: {now_utc} - DO NOT EDIT MANUALLY",
        "",
        "server {",
    ]

    # --- listen directive --------------------------------------------------
    if is_udp:
        lines.append(f"    listen {stream.listen_port} udp reuseport;")
    elif stream.ssl_enabled and stream.ssl_cert_path and stream.ssl_key_path:
        lines.append(f"    listen {stream.listen_port} ssl;")
    else:
        lines.append(f"    listen {stream.listen_port};")

    # --- proxy_pass -------------------------------------------------------
    lines.append(f"    proxy_pass {safe_cs_ip}:{stream.cs_port};")

    # --- timeouts ---------------------------------------------------------
    if is_udp:
        lines.append("    proxy_timeout 20s;")
    else:
        lines.append("    proxy_connect_timeout 60s;")
        lines.append("    proxy_timeout 10m;")

    # --- DNS-specific -----------------------------------------------------
    if is_dns:
        lines.append("    proxy_responses 1;")

    # --- SSL block (TCP only) ---------------------------------------------
    if stream.ssl_enabled and not is_udp and stream.ssl_cert_path and stream.ssl_key_path:
        safe_cert = _safe_nginx_value(stream.ssl_cert_path, "ssl_cert_path")
        safe_key = _safe_nginx_value(stream.ssl_key_path, "ssl_key_path")
        safe_protocols = _safe_nginx_value(stream.ssl_protocols, "ssl_protocols")
        safe_ciphers = _safe_nginx_value(stream.ssl_ciphers, "ssl_ciphers")
        lines.append(f"    ssl_certificate {safe_cert};")
        lines.append(f"    ssl_certificate_key {safe_key};")
        lines.append(f"    ssl_protocols {safe_protocols};")
        lines.append(f"    ssl_ciphers {safe_ciphers};")
        lines.append("    ssl_session_cache shared:SSL:10m;")
        lines.append("    ssl_session_timeout 10m;")

    # --- Access control ---------------------------------------------------
    if stream.access_control_enabled and stream.allowed_cidrs:
        for cidr in stream.allowed_cidrs:
            safe_cidr = _safe_nginx_value(cidr.strip(), "allowed_cidr")
            lines.append(f"    allow {safe_cidr};")
        lines.append("    deny all;")

    lines.append("}")
    lines.append("")   # trailing newline

    return "\n".join(lines)


def generate_stream_config_preview(stream: "StreamConfig") -> str:
    """Alias for generate_stream_config — used by the preview endpoint."""
    return generate_stream_config(stream)
