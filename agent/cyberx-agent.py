#!/usr/bin/env python3
"""CyberX Instance Agent — polls for tasks and executes them.

Zero external dependencies (stdlib only).
Runs as a systemd service, logs to journald via stderr.
"""
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

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

# ─── Logging ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("cyberx-agent")

# ─── HTTP helpers ───────────────────────────────────────────────────


def _read_token() -> str:
    """Read agent token from file."""
    with open(TOKEN_PATH) as f:
        return f.read().strip()


def _api_request(
    method: str, path: str, token: str, body: dict | None = None
) -> dict | None:
    """Make an authenticated API request. Returns parsed JSON or None."""
    url = f"{API_ENDPOINT}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode()
        except Exception:
            pass
        log.error("HTTP %d on %s %s: %s", e.code, method, path, body_text)
        raise
    except urllib.error.URLError as e:
        log.error("Connection error on %s %s: %s", method, path, e.reason)
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
    log.info("Agent started. Polling %s every %ds", API_ENDPOINT, POLL_INTERVAL)

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
