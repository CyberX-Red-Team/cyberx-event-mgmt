#!/usr/bin/env python3
"""CyberX Instance Agent — polls for tasks and executes them.

Runs as a systemd service, logs to journald via stderr.

DNS resolution is handled independently of the system resolver so that
isolated-network DNS and C2 frameworks that hijack /etc/resolv.conf cannot
prevent the agent from reaching the management API.

Dependencies: dnspython, requests
"""
import logging
import os
import subprocess
import sys
import time
from urllib.parse import urlparse

import dns.resolver
import requests
from requests.adapters import HTTPAdapter

# ─── Configuration ──────────────────────────────────────────────────

TOKEN_PATH = os.environ.get(
    "CYBERX_AGENT_TOKEN", "/etc/cyberx-agent/token"
)
API_ENDPOINT = os.environ.get(
    "CYBERX_AGENT_API", ""  # e.g. https://app.example.com/api/agent
)
POLL_INTERVAL = int(os.environ.get("CYBERX_AGENT_POLL_INTERVAL", "30"))
WG_INTERFACE = os.environ.get("CYBERX_WG_INTERFACE", "wg0")
WG_CONFIG_PATH = os.environ.get(
    "CYBERX_WG_CONFIG", f"/etc/wireguard/{WG_INTERFACE}.conf"
)

MAX_BACKOFF = 300  # 5 minutes

# External DNS servers to query directly, bypassing /etc/resolv.conf.
# Comma-separated list via env var, defaults to Cloudflare + Google.
DNS_SERVERS = os.environ.get(
    "CYBERX_DNS_SERVERS", "1.1.1.1,8.8.8.8"
).split(",")

# How long (seconds) to cache a DNS result before re-resolving.
DNS_CACHE_TTL = int(os.environ.get("CYBERX_DNS_CACHE_TTL", "300"))

# ─── Logging ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("cyberx-agent")

# ─── Independent DNS resolver ──────────────────────────────────────

_dns_cache: dict[str, tuple[str, float]] = {}


def _resolve_host(hostname: str) -> str:
    """Resolve *hostname* → IP using external DNS, bypassing the system resolver.

    Results are cached for DNS_CACHE_TTL seconds.
    """
    now = time.monotonic()
    cached = _dns_cache.get(hostname)
    if cached and (now - cached[1]) < DNS_CACHE_TTL:
        return cached[0]

    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = list(DNS_SERVERS)
    resolver.lifetime = 10  # seconds total timeout

    try:
        answers = resolver.resolve(hostname, "A")
        ip = str(answers[0])
        _dns_cache[hostname] = (ip, now)
        log.info("Resolved %s → %s (via %s)", hostname, ip, DNS_SERVERS[0])
        return ip
    except Exception as e:
        log.error("DNS resolution failed for %s: %s", hostname, e)
        raise

# ─── HTTP session with custom DNS ──────────────────────────────────


class _DirectDNSAdapter(HTTPAdapter):
    """Requests adapter that resolves hostnames via our own DNS resolver
    and connects to the resolved IP while preserving the original Host
    header and TLS SNI."""

    def send(self, request, stream=False, timeout=None,
             verify=True, cert=None, proxies=None):
        parsed = urlparse(request.url)
        hostname = str(parsed.hostname or "")

        # Resolve via our independent DNS
        ip = _resolve_host(hostname)

        # Rewrite the URL to use the resolved IP, keep everything else
        port_suffix = f":{parsed.port}" if parsed.port else ""
        request.url = request.url.replace(
            f"{parsed.scheme}://{parsed.hostname}{port_suffix}",
            f"{parsed.scheme}://{ip}{port_suffix}",
            1,
        )

        # Ensure the original Host header is set (required for virtual hosts / TLS SNI)
        request.headers.setdefault("Host", hostname)

        # Store the real hostname so init_poolmanager can use it for TLS SNI
        self._real_hostname = hostname

        return super().send(request, stream=stream, timeout=timeout,
                            verify=verify, cert=cert, proxies=proxies)

    def init_poolmanager(self, *args, **kwargs):
        # Use the real hostname for TLS certificate validation and SNI
        hostname = getattr(self, "_real_hostname", None)
        if hostname:
            kwargs["assert_hostname"] = hostname
            kwargs["server_hostname"] = hostname
        super().init_poolmanager(*args, **kwargs)


def _build_session(token: str) -> requests.Session:
    """Create a requests.Session that uses our independent DNS resolver."""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    adapter = _DirectDNSAdapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# ─── HTTP helpers ───────────────────────────────────────────────────

# Global session, initialised in main()
_session: requests.Session | None = None


def _read_token() -> str:
    """Read agent token from file."""
    with open(TOKEN_PATH) as f:
        return f.read().strip()


def _api_request(
    method: str, path: str, token: str, body: dict | None = None
) -> dict | None:
    """Make an authenticated API request. Returns parsed JSON or None."""
    url = f"{API_ENDPOINT}{path}"

    try:
        resp = _session.request(method, url, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        body_text = e.response.text[:500] if e.response is not None else ""
        log.error(
            "HTTP %d on %s %s: %s",
            e.response.status_code if e.response is not None else 0,
            method, path, body_text,
        )
        raise
    except requests.exceptions.ConnectionError as e:
        log.error("Connection error on %s %s: %s", method, path, e)
        raise


# ─── Task handlers ──────────────────────────────────────────────────


def handle_cycle_vpn(task: dict, token: str) -> None:
    """Cycle VPN: tear down, request new config, bring up."""
    task_id = task["id"]
    log.info("Starting cycle_vpn (task %d)", task_id)

    # 1. Mark task as IN_PROGRESS
    _api_request("PATCH", f"/tasks/{task_id}", token, {
        "status": "IN_PROGRESS",
    })

    try:
        # 2. Tear down WireGuard
        log.info("Bringing down %s...", WG_INTERFACE)
        subprocess.run(
            ["wg-quick", "down", WG_INTERFACE],
            capture_output=True, text=True, timeout=30,
        )
        # Ignore errors — interface might not be up

        # 3. Request new VPN config
        log.info("Requesting new VPN config...")
        result = _api_request("POST", "/vpn/new-config", token, {
            "task_id": task_id,
        })

        if not result or "config" not in result:
            raise RuntimeError("No config in VPN response")

        # 4. Write new config
        config_text = result["config"]
        with open(WG_CONFIG_PATH, "w") as f:
            f.write(config_text)
        os.chmod(WG_CONFIG_PATH, 0o600)
        log.info(
            "Wrote new config to %s (IP: %s)",
            WG_CONFIG_PATH, result.get("ipv4_address", "?"),
        )

        # 5. Bring up WireGuard
        log.info("Bringing up %s...", WG_INTERFACE)
        proc = subprocess.run(
            ["wg-quick", "up", WG_INTERFACE],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"wg-quick up failed: {proc.stderr.strip()}"
            )

        # 6. Mark completed
        _api_request("PATCH", f"/tasks/{task_id}", token, {
            "status": "COMPLETED",
            "result": {
                "ipv4_address": result.get("ipv4_address"),
                "interface_ip": result.get("interface_ip"),
            },
        })
        log.info("cycle_vpn completed (task %d)", task_id)

    except Exception as e:
        log.error("cycle_vpn failed (task %d): %s", task_id, e)
        try:
            _api_request("PATCH", f"/tasks/{task_id}", token, {
                "status": "FAILED",
                "error_message": str(e)[:500],
            })
        except Exception:
            log.error("Failed to report task failure")


# ─── Task registry ──────────────────────────────────────────────────

TASK_HANDLERS = {
    "cycle_vpn": handle_cycle_vpn,
}

# ─── Main loop ──────────────────────────────────────────────────────


def main():
    """Main agent loop: poll for tasks, execute them."""
    if not API_ENDPOINT:
        log.error(
            "CYBERX_AGENT_API not set and no default configured. "
            "Set it or pass via cloud-init."
        )
        sys.exit(1)

    if not os.path.exists(TOKEN_PATH):
        log.error("Token file not found: %s", TOKEN_PATH)
        sys.exit(1)

    token = _read_token()

    global _session
    _session = _build_session(token)

    log.info(
        "Agent started. Polling %s every %ds (DNS via %s)",
        API_ENDPOINT, POLL_INTERVAL, ", ".join(DNS_SERVERS),
    )

    backoff = POLL_INTERVAL

    while True:
        try:
            # Poll for tasks (also serves as heartbeat)
            data = _api_request("GET", "/tasks", token)
            tasks = data.get("tasks", []) if data else []

            if tasks:
                log.info("Received %d task(s)", len(tasks))
                for task in tasks:
                    task_type = task.get("task_type")
                    handler = TASK_HANDLERS.get(task_type)
                    if handler:
                        handler(task, token)
                    else:
                        log.warning(
                            "Unknown task type: %s (task %d)",
                            task_type, task.get("id"),
                        )

            # Reset backoff on success
            backoff = POLL_INTERVAL

        except Exception as e:
            log.error("Poll error: %s", e)
            backoff = min(backoff * 2, MAX_BACKOFF)
            log.info("Backing off to %ds", backoff)

        time.sleep(backoff)


if __name__ == "__main__":
    main()
