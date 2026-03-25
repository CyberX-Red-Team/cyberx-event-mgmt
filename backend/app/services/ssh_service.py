"""SSH/SFTP service for managing nginx stream configs on remote redirectors.

All paramiko operations are synchronous. Public async methods wrap the sync
implementations in a bounded ThreadPoolExecutor so they don't block the
FastAPI event loop.

Error taxonomy (maps to HTTP responses in the route layer):
    SSHConnectionError  → 503 Service Unavailable
    SSHAuthError        → 422 Unprocessable Entity
    NginxTestError      → 200 OK  with success=False + nginx stderr
    NginxReloadError    → 500 Internal Server Error
    SSHCommandError     → 500 Internal Server Error

NginxTestError returns HTTP 200 (not 500) because the operation completed —
the operator needs to see the nginx -t output to diagnose and fix the config.

Rollback: on single-stream deploy with NginxTestError, the just-written file
is deleted via SFTP before returning, leaving the remote in its prior state.

Sudo requirement on each redirector (set up once by operator):
    # /etc/sudoers.d/cyberx
    <ssh_user> ALL=(ALL) NOPASSWD: /usr/sbin/nginx, /bin/systemctl reload nginx
"""
import asyncio
import io
import logging
import shlex
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple

import paramiko

logger = logging.getLogger(__name__)

# Bounded thread pool — all paramiko calls execute here
_executor = ThreadPoolExecutor(max_workers=10)

# Semaphore prevents queuing more requests than the pool can handle,
# so a few offline redirectors can't exhaust all workers.
_ssh_semaphore = asyncio.Semaphore(10)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class SSHConnectionError(Exception):
    """TCP connect or handshake failed."""


class SSHAuthError(Exception):
    """SSH authentication rejected (bad key, wrong user, missing passphrase)."""


class NginxTestError(Exception):
    """nginx -t returned non-zero. Message contains nginx stderr output."""


class NginxReloadError(Exception):
    """nginx -t passed but systemctl reload failed."""


class SSHCommandError(Exception):
    """exec_command returned non-zero for a command that is not otherwise handled."""


# ---------------------------------------------------------------------------
# SSHService (synchronous core — runs inside the executor)
# ---------------------------------------------------------------------------

class SSHService:
    """
    Manages SSH/SFTP operations for a single Redirector.

    Instantiate per-request in the route handler with the decrypted key.
    Do NOT store the instance across requests — the decrypted key must
    remain a short-lived local variable.
    """

    CONNECT_TIMEOUT = 10   # seconds until TCP connect fails
    AUTH_TIMEOUT = 15      # seconds for key exchange + auth
    COMMAND_TIMEOUT = 30   # per-command channel timeout

    @property
    def _sudo_prefix(self) -> str:
        """Return 'sudo ' if not root, empty string if root."""
        return "" if self.username == "root" else "sudo "

    def __init__(
        self,
        hostname: str,
        port: int,
        username: str,
        private_key_pem: str,
        passphrase: Optional[str] = None,
    ):
        self.hostname = hostname
        self.port = port
        self.username = username
        self._private_key_pem = private_key_pem
        self._passphrase = passphrase

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_key(self) -> paramiko.PKey:
        """
        Try RSA → Ed25519 → ECDSA key loading from PEM string.

        Raises SSHAuthError on authentication-related failures.
        """
        pem = self._private_key_pem
        passphrase_bytes: Optional[bytes] = (
            self._passphrase.encode("utf-8") if self._passphrase else None
        )

        for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                return key_class.from_private_key(
                    io.StringIO(pem), password=passphrase_bytes
                )
            except paramiko.PasswordRequiredException:
                raise SSHAuthError(
                    "SSH key is passphrase-protected but no passphrase was provided."
                )
            except paramiko.ssh_exception.SSHException:
                # Wrong key type — try the next one
                continue
            except Exception:
                continue

        raise SSHAuthError(
            "Could not load SSH private key: unsupported key type or malformed PEM."
        )

    def _connect(self) -> paramiko.SSHClient:
        """Establish an authenticated SSH connection. Caller must call client.close().

        Security note: WarningPolicy logs a warning when connecting to an unknown
        host key instead of silently accepting it (AutoAddPolicy). This is a
        Trust-On-First-Use (TOFU) model — an adversary performing a MitM attack
        before the first connection would not be detected. For hardened deployments,
        a future enhancement will store per-redirector host key fingerprints and
        validate them on each connection.
        """
        client = paramiko.SSHClient()
        # TODO: SECURITY — implement host key pinning (TOFU) by storing
        # per-redirector fingerprints and verifying on each connection.
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            pkey = self._load_key()
            client.connect(
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                pkey=pkey,
                timeout=self.CONNECT_TIMEOUT,
                auth_timeout=self.AUTH_TIMEOUT,
                look_for_keys=False,
                allow_agent=False,
            )
        except (SSHAuthError, SSHConnectionError):
            raise
        except paramiko.AuthenticationException as e:
            raise SSHAuthError(f"Authentication failed: {e}")
        except Exception as e:
            raise SSHConnectionError(
                f"Could not connect to {self.hostname}:{self.port}: {e}"
            )
        return client

    def _exec(
        self, client: paramiko.SSHClient, command: str
    ) -> Tuple[str, str, int]:
        """Execute a shell command. Returns (stdout, stderr, exit_code)."""
        _, stdout_fh, stderr_fh = client.exec_command(
            command, timeout=self.COMMAND_TIMEOUT
        )
        exit_code = stdout_fh.channel.recv_exit_status()
        stdout = stdout_fh.read().decode("utf-8", errors="replace")
        stderr = stderr_fh.read().decode("utf-8", errors="replace")
        return stdout, stderr, exit_code

    def _ensure_remote_dir(self, sftp: paramiko.SFTPClient, path: str) -> None:
        """Create the remote directory if it does not exist."""
        try:
            sftp.stat(path)
        except FileNotFoundError:
            sftp.mkdir(path)

    def _nginx_test_and_reload(
        self, client: paramiko.SSHClient
    ) -> Tuple[str, str]:
        """
        Run `sudo nginx -t`. On pass, run `sudo systemctl reload nginx`.

        Returns (test_output, reload_output) on full success.
        Raises NginxTestError if nginx -t fails (test_output = nginx stderr).
        Raises NginxReloadError if reload fails after a successful test.
        """
        # nginx -t writes its output to stderr
        _, test_stderr, test_code = self._exec(client, f"{self._sudo_prefix}/usr/sbin/nginx -t")
        test_output = test_stderr.strip()

        if test_code != 0:
            raise NginxTestError(test_output)

        _, reload_stderr, reload_code = self._exec(
            client, f"{self._sudo_prefix}/bin/systemctl reload nginx"
        )
        reload_output = reload_stderr.strip()

        if reload_code != 0:
            raise NginxReloadError(f"nginx reload failed: {reload_output}")

        return test_output, reload_output

    # ------------------------------------------------------------------
    # Public synchronous operations (called via run_in_executor)
    # ------------------------------------------------------------------

    def sync_test_connection(self) -> dict:
        """
        Verify SSH connectivity and confirm nginx stream module is present.

        Returns a dict compatible with TestConnectionResult schema.
        """
        t0 = time.monotonic()
        client = self._connect()
        try:
            stdout, _, code = self._exec(client, "echo cyberx_ok")
            if code != 0 or "cyberx_ok" not in stdout:
                raise SSHCommandError("Echo connectivity check failed.")

            rtt_ms = round((time.monotonic() - t0) * 1000, 1)

            # nginx stream module check (compiled-in or dynamic)
            stream_out, _, _ = self._exec(
                client, f"{self._sudo_prefix}/usr/sbin/nginx -V 2>&1 | grep -- --with-stream"
            )
            compiled_in = "--with-stream" in stream_out
            _, _, mod_code = self._exec(
                client, "test -f /usr/lib/nginx/modules/ngx_stream_module.so"
            )
            stream_module_present = compiled_in or mod_code == 0

            return {
                "success": True,
                "status": "online",
                "stream_module_present": stream_module_present,
                "rtt_ms": rtt_ms,
                "message": "Connection successful."
                + ("" if stream_module_present else " WARNING: nginx stream module not detected."),
            }
        finally:
            client.close()

    def sync_check_port(self, port: int, protocol: str) -> dict:
        """
        Check whether anything is already listening on the given port.

        Runs `ss -tlunp sport = :<port>` (covers both TCP and UDP) so the
        operator is warned regardless of which protocol nginx would use.

        Returns {"in_use": bool, "listeners": list[str], "process_names": list[str], "message": str}.
        """
        import re
        command = f"ss -tlunp sport = :{port} 2>/dev/null"
        client = self._connect()
        try:
            stdout, _, _ = self._exec(client, command)
            lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
            # First line is the ss header row; anything beyond it is a match
            listeners = lines[1:] if len(lines) > 1 else []
            in_use = bool(listeners)

            # Extract unique process names from users:(("name",...)) in each line
            process_names: list[str] = []
            for ln in listeners:
                for m in re.finditer(r'users:\(\("([^"]+)"', ln):
                    name = m.group(1)
                    if name not in process_names:
                        process_names.append(name)

            nginx_listening = "nginx" in process_names
            other_processes = [p for p in process_names if p != "nginx"]

            if nginx_listening:
                status = "healthy"
                message = f"nginx is listening on port {port}."
            elif in_use:
                status = "conflict"
                proc_str = ", ".join(other_processes) if other_processes else "unknown process"
                message = (
                    f"Port {port} is already in use by: {proc_str} — "
                    "nginx will not be able to bind."
                )
            else:
                status = "not_listening"
                message = f"Nothing is listening on port {port} — stream may not be deployed."

            return {
                "in_use": in_use,
                "status": status,
                "listeners": listeners,
                "process_names": process_names,
                "message": message,
            }
        finally:
            client.close()

    def sync_deploy_single(self, stream_dir: str, stream) -> dict:
        """
        Write a single enabled StreamConfig file to the redirector and reload nginx.

        On NginxTestError: deletes the file just written (rollback) before returning.
        Returns a dict compatible with DeployResult schema.
        """
        from app.services.nginx_config_service import generate_stream_config

        filename = f"cyberx_{stream.id}.conf"
        remote_path = f"{stream_dir}/{filename}"
        config_text = generate_stream_config(stream)

        client = self._connect()
        try:
            sftp = client.open_sftp()
            self._ensure_remote_dir(sftp, stream_dir)
            sftp.putfo(io.BytesIO(config_text.encode("utf-8")), remote_path)

            try:
                test_out, reload_out = self._nginx_test_and_reload(client)
            except NginxTestError as e:
                # Rollback: remove the file we just wrote
                try:
                    sftp.remove(remote_path)
                    logger.info("Rolled back %s after nginx -t failure", remote_path)
                except Exception as rm_err:
                    logger.warning("Rollback failed for %s: %s", remote_path, rm_err)

                return {
                    "success": False,
                    "nginx_test_output": str(e),
                    "nginx_reload_output": "",
                    "stream_module_present": True,
                    "files_written": [],
                    "files_deleted": [],
                    "message": "nginx configuration test failed. File rolled back.",
                }

            return {
                "success": True,
                "nginx_test_output": test_out,
                "nginx_reload_output": reload_out,
                "stream_module_present": True,
                "files_written": [filename],
                "files_deleted": [],
                "message": f"Stream '{stream.name}' deployed successfully.",
            }
        finally:
            client.close()

    def sync_remove_single(
        self, stream_dir: str, stream_id: str, stream_name: str
    ) -> dict:
        """
        Delete a single stream config file from the redirector and reload nginx.

        Missing file is not an error (idempotent).
        Returns a dict compatible with DeployResult schema.
        """
        filename = f"cyberx_{stream_id}.conf"
        remote_path = f"{stream_dir}/{filename}"

        client = self._connect()
        try:
            sftp = client.open_sftp()
            try:
                sftp.remove(remote_path)
                files_deleted = [filename]
                logger.info("Removed %s from redirector", remote_path)
            except FileNotFoundError:
                files_deleted = []
                logger.info("File %s not found on redirector (already removed)", remote_path)

            try:
                test_out, reload_out = self._nginx_test_and_reload(client)
            except NginxTestError as e:
                return {
                    "success": False,
                    "nginx_test_output": str(e),
                    "nginx_reload_output": "",
                    "stream_module_present": True,
                    "files_written": [],
                    "files_deleted": files_deleted,
                    "message": "nginx configuration test failed after file removal.",
                }

            return {
                "success": True,
                "nginx_test_output": test_out,
                "nginx_reload_output": reload_out,
                "stream_module_present": True,
                "files_written": [],
                "files_deleted": files_deleted,
                "message": f"Stream '{stream_name}' removed successfully.",
            }
        finally:
            client.close()

    def sync_deploy_all(self, stream_dir: str, streams: list) -> dict:
        """
        Sync all StreamConfigs for a redirector:
          1. Snapshot existing config files (for rollback)
          2. Write enabled streams
          3. Delete disabled streams
          4. Remove orphaned cyberx_*.conf files not in the current set
          5. nginx -t → systemctl reload nginx
          6. On nginx -t failure: restore all snapshots (rollback)

        Returns a dict compatible with DeployResult schema.
        """
        from app.services.nginx_config_service import generate_stream_config

        files_written: list[str] = []
        files_deleted: list[str] = []

        client = self._connect()
        try:
            sftp = client.open_sftp()
            self._ensure_remote_dir(sftp, stream_dir)

            known_filenames = {f"cyberx_{s.id}.conf" for s in streams}

            # Snapshot existing files for rollback on nginx -t failure
            # Key = remote_path, Value = bytes (existing content) or None (file was new)
            backup: dict[str, Optional[bytes]] = {}

            for stream in streams:
                filename = f"cyberx_{stream.id}.conf"
                remote_path = f"{stream_dir}/{filename}"
                if stream.enabled:
                    try:
                        with sftp.open(remote_path, "rb") as f:
                            backup[remote_path] = f.read()
                    except FileNotFoundError:
                        backup[remote_path] = None

            # Write enabled streams, delete disabled streams
            for stream in streams:
                filename = f"cyberx_{stream.id}.conf"
                remote_path = f"{stream_dir}/{filename}"

                if stream.enabled:
                    config_text = generate_stream_config(stream)
                    sftp.putfo(io.BytesIO(config_text.encode("utf-8")), remote_path)
                    files_written.append(filename)
                    logger.debug("Wrote %s", remote_path)
                else:
                    try:
                        # Snapshot before deleting for rollback
                        try:
                            with sftp.open(remote_path, "rb") as f:
                                backup[remote_path] = f.read()
                        except FileNotFoundError:
                            pass
                        sftp.remove(remote_path)
                        files_deleted.append(filename)
                        logger.debug("Removed disabled stream file %s", remote_path)
                    except FileNotFoundError:
                        pass

            # Orphan cleanup: remove cyberx_*.conf files that are no longer in the DB
            try:
                remote_listing = sftp.listdir(stream_dir)
                for remote_file in remote_listing:
                    if (
                        remote_file.startswith("cyberx_")
                        and remote_file.endswith(".conf")
                        and remote_file not in known_filenames
                    ):
                        orphan_path = f"{stream_dir}/{remote_file}"
                        try:
                            with sftp.open(orphan_path, "rb") as f:
                                backup[orphan_path] = f.read()
                        except FileNotFoundError:
                            pass
                        sftp.remove(orphan_path)
                        files_deleted.append(remote_file)
                        logger.info("Removed orphan file %s", remote_file)
            except Exception as list_err:
                logger.warning("Orphan cleanup failed: %s", list_err)

            try:
                test_out, reload_out = self._nginx_test_and_reload(client)
            except NginxTestError as e:
                # Rollback: restore all files to their pre-deploy state
                rollback_ok = True
                for path, content in backup.items():
                    try:
                        if content is None:
                            sftp.remove(path)
                        else:
                            sftp.putfo(io.BytesIO(content), path)
                    except Exception as rb_err:
                        rollback_ok = False
                        logger.warning("Rollback failed for %s: %s", path, rb_err)
                if rollback_ok:
                    logger.info("Rolled back %d file(s) after nginx -t failure", len(backup))
                return {
                    "success": False,
                    "nginx_test_output": str(e),
                    "nginx_reload_output": "",
                    "stream_module_present": True,
                    "files_written": files_written,
                    "files_deleted": files_deleted,
                    "message": "nginx configuration test failed. Files rolled back."
                    if rollback_ok
                    else "nginx configuration test failed. Partial rollback — check server manually.",
                }

            return {
                "success": True,
                "nginx_test_output": test_out,
                "nginx_reload_output": reload_out,
                "stream_module_present": True,
                "files_written": files_written,
                "files_deleted": files_deleted,
                "message": (
                    f"Deployed {len(files_written)} stream(s), "
                    f"removed {len(files_deleted)} file(s)."
                ),
            }
        finally:
            client.close()


    def sync_check_nginx_setup(self) -> dict:
        """
        Check two common nginx setup issues on the redirector:
          1. Default HTTP site active (port 80 served by nginx, not a stream)
          2. Stream block with stream.d include absent from nginx config

        Returns {"nginx_conf_ok": bool, "default_site_active": bool,
                 "stream_block_present": bool, "issues": list[str]}
        """
        client = self._connect()
        try:
            issues = []

            # Default site: symlink exists → nginx is serving HTTP on port 80
            _, _, code = self._exec(
                client, "test -e /etc/nginx/sites-enabled/default"
            )
            default_site_active = (code == 0)
            if default_site_active:
                issues.append(
                    "Default HTTP site is active — nginx is listening on port 80 via "
                    "sites-enabled/default. This blocks any stream config that also needs "
                    "port 80 and may be unexpected traffic on a redirector."
                )

            # Stream block: grep for stream.d include in all nginx config files
            stream_out, _, _ = self._exec(
                client, "grep -r 'stream.d' /etc/nginx/ 2>/dev/null || true"
            )
            stream_block_present = bool(stream_out.strip())
            if not stream_block_present:
                issues.append(
                    "No stream block found in nginx config — stream proxying will not work "
                    "until a 'stream { include stream.d/*.conf; }' block is added to nginx.conf."
                )

            return {
                "nginx_conf_ok": not issues,
                "default_site_active": default_site_active,
                "stream_block_present": stream_block_present,
                "issues": issues,
            }
        finally:
            client.close()

    def sync_fix_nginx_setup(self, stream_dir: str) -> dict:
        """
        Fix common nginx setup issues:
          1. Remove sites-enabled/default symlink (disables default HTTP server)
          2. Ensure stream.d directory exists
          3. Append stream block to nginx.conf if absent
          4. nginx -t → systemctl reload nginx

        Writes a temp script via SFTP and executes it with sudo.
        Requires sudoers entry:
            <user> ALL=(ALL) NOPASSWD: /bin/bash /var/lib/cyberx/scripts/.cyberx_nginx_fix_*.sh
        """
        safe_dir = shlex.quote(stream_dir)
        script_path = f"/var/lib/cyberx/scripts/.cyberx_nginx_fix_{uuid.uuid4().hex[:8]}.sh"
        script = (
            "#!/bin/bash\n"
            "set -e\n"
            "rm -f /etc/nginx/sites-enabled/default\n"
            f"mkdir -p {safe_dir}\n"
            "# Ensure stream module is loaded\n"
            "if [ -f /usr/lib/nginx/modules/ngx_stream_module.so ] && "
            "! grep -q 'ngx_stream_module' /etc/nginx/nginx.conf 2>/dev/null; then\n"
            "    # Debian: enable via symlink if available\n"
            "    if [ -f /usr/share/nginx/modules-available/mod-stream.conf ]; then\n"
            "        ln -sf /usr/share/nginx/modules-available/mod-stream.conf /etc/nginx/modules-enabled/50-mod-stream.conf 2>/dev/null || true\n"
            "    fi\n"
            "    # Also add load_module directly — works regardless of modules-enabled include\n"
            "    sed -i '1i load_module /usr/lib/nginx/modules/ngx_stream_module.so;' /etc/nginx/nginx.conf\n"
            "fi\n"
            "# Add stream block if not present\n"
            "if ! grep -rq 'stream.d' /etc/nginx/ 2>/dev/null; then\n"
            f"    printf '\\nstream {{\\n    include {safe_dir}/*.conf;\\n}}\\n'"
            " >> /etc/nginx/nginx.conf\n"
            "fi\n"
            "/usr/sbin/nginx -t\n"
            "systemctl reload nginx\n"
        )
        client = self._connect()
        try:
            sftp = client.open_sftp()
            sftp.putfo(io.BytesIO(script.encode()), script_path)
            sftp.chmod(script_path, 0o700)

            _, stderr, code = self._exec(
                client, f"{self._sudo_prefix}/bin/bash {shlex.quote(script_path)} 2>&1"
            )
            self._exec(client, f"rm -f {shlex.quote(script_path)}")

            if code != 0:
                return {
                    "success": False,
                    "message": f"Fix script failed: {stderr.strip()}",
                    "output": stderr.strip(),
                }
            return {
                "success": True,
                "message": "nginx configuration fixed — default site disabled, stream block added, nginx reloaded.",
                "output": stderr.strip(),
            }
        finally:
            client.close()


    def sync_check_prereqs(self, stream_dir: str) -> dict:
        """
        Verify all CyberX prerequisites on the redirector:
          1. nginx installed
          2. nginx stream module compiled in
          3. Stream directory exists
          4. sudo nginx -t works
          5. sudo systemctl reload nginx is allowed
        """
        client = self._connect()
        try:
            checks = []

            # 1. nginx installed
            _, _, code = self._exec(client, "which nginx 2>/dev/null")
            nginx_ok = code == 0
            checks.append({
                "id": "nginx_installed",
                "label": "nginx installed",
                "ok": nginx_ok,
                "detail": "nginx binary found." if nginx_ok
                          else "nginx not found — install with: apt-get install nginx-full",
            })

            # 2. nginx stream module (compiled-in or dynamic)
            if nginx_ok:
                v_out, _, _ = self._exec(client, "nginx -V 2>&1")
                compiled_in = "with-stream" in v_out
                # Also check for dynamic stream module
                mod_out, _, mod_code = self._exec(
                    client, "test -f /usr/lib/nginx/modules/ngx_stream_module.so 2>/dev/null"
                )
                dynamic_mod = mod_code == 0
                stream_mod_ok = compiled_in or dynamic_mod
            else:
                stream_mod_ok = False
            checks.append({
                "id": "nginx_stream",
                "label": "nginx stream module",
                "ok": stream_mod_ok,
                "detail": "Stream module available." if stream_mod_ok
                          else "Stream module absent — install nginx-full: apt-get install nginx-full",
            })

            # 3. Stream directory
            _, _, code = self._exec(client, f"test -d {stream_dir}")
            dir_ok = code == 0
            checks.append({
                "id": "stream_dir",
                "label": f"Stream directory ({stream_dir})",
                "ok": dir_ok,
                "detail": "Directory exists." if dir_ok
                          else f"Directory missing — fix will create it.",
            })

            # 4. nginx -t (runs nginx config test — safe, read-only)
            sudo_n = "" if self.username == "root" else "sudo -n "
            out4, _, code = self._exec(
                client, f"{sudo_n}/usr/sbin/nginx -t 2>&1"
            )
            sudo_nginx_ok = code == 0
            if sudo_nginx_ok:
                nginx_t_detail = "nginx -t succeeded."
            elif self.username == "root":
                nginx_t_detail = f"nginx -t failed — config error: {out4.strip()}"
            else:
                nginx_t_detail = (
                    f"nginx -t failed — add sudoers entry: "
                    f"{self.username} ALL=(ALL) NOPASSWD: /usr/sbin/nginx"
                )
            checks.append({
                "id": "sudo_nginx",
                "label": "nginx -t",
                "ok": sudo_nginx_ok,
                "detail": nginx_t_detail,
            })

            # 5. systemctl reload nginx (check via is-active — read-only)
            _, _, code = self._exec(
                client, f"{sudo_n}/bin/systemctl is-active nginx 2>/dev/null"
            )
            # exit 0 = active, exit 3 = inactive — both mean the command works
            sudo_systemctl_ok = code in (0, 3)
            if sudo_systemctl_ok:
                systemctl_detail = "systemctl works."
            elif self.username == "root":
                systemctl_detail = "systemctl failed — nginx may not be running."
            else:
                systemctl_detail = (
                    f"systemctl failed — add sudoers entry: "
                    f"{self.username} ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx"
                )
            checks.append({
                "id": "sudo_systemctl",
                "label": "systemctl nginx",
                "ok": sudo_systemctl_ok,
                "detail": systemctl_detail,
            })

            all_ok = all(c["ok"] for c in checks)
            return {"all_ok": all_ok, "checks": checks}
        finally:
            client.close()

    def sync_fix_prereqs(self, stream_dir: str) -> dict:
        """
        Attempt to satisfy CyberX prerequisites automatically:
          1. Install nginx-full (if absent)
          2. Create stream directory
          3. Write /etc/sudoers.d/cyberx with required NOPASSWD entries
          4. Validate sudoers with visudo -c

        Writes a temp script via SFTP and executes it with 'sudo /bin/bash'.
        Requires the SSH user to have NOPASSWD sudo (any command).
        """
        safe_dir = shlex.quote(stream_dir)
        safe_user = shlex.quote(self.username)
        # Bootstrap script uses /tmp because /var/lib/cyberx/scripts/ doesn't exist yet
        script_path = f"/tmp/.cyberx_prereq_fix_{uuid.uuid4().hex[:8]}.sh"
        script = (
            "#!/bin/bash\n"
            "set -e\n"
            "# Install nginx-full if nginx binary is missing\n"
            "if ! command -v nginx &>/dev/null; then\n"
            "    export DEBIAN_FRONTEND=noninteractive\n"
            "    apt-get update -qq\n"
            "    apt-get install -y nginx-full\n"
            "fi\n"
            f"# Create stream directory\n"
            f"mkdir -p {safe_dir}\n"
            "# Create script staging directory (not world-writable, unlike /tmp)\n"
            "mkdir -p /var/lib/cyberx/scripts\n"
            f"chown {safe_user}:{safe_user} /var/lib/cyberx/scripts\n"
            "chmod 750 /var/lib/cyberx/scripts\n"
            "# Ensure stream module is loaded\n"
            "if [ -f /usr/lib/nginx/modules/ngx_stream_module.so ] && "
            "! grep -q 'ngx_stream_module' /etc/nginx/nginx.conf 2>/dev/null; then\n"
            "    if [ -f /usr/share/nginx/modules-available/mod-stream.conf ]; then\n"
            "        ln -sf /usr/share/nginx/modules-available/mod-stream.conf /etc/nginx/modules-enabled/50-mod-stream.conf 2>/dev/null || true\n"
            "    fi\n"
            "    sed -i '1i load_module /usr/lib/nginx/modules/ngx_stream_module.so;' /etc/nginx/nginx.conf\n"
            "fi\n"
            "# Add stream block if not present\n"
            "if ! grep -rq 'stream.d' /etc/nginx/ 2>/dev/null; then\n"
            f"    printf '\\nstream {{\\n    include {safe_dir}/*.conf;\\n}}\\n'"
            " >> /etc/nginx/nginx.conf\n"
            "fi\n"
            "# Write sudoers file for CyberX\n"
            f"cat > /etc/sudoers.d/cyberx <<SUDOERS\n"
            f"{safe_user} ALL=(ALL) NOPASSWD: /usr/sbin/nginx, /bin/systemctl reload nginx, /bin/bash /var/lib/cyberx/scripts/.cyberx_nginx_fix_*.sh\n"
            "SUDOERS\n"
            "chmod 440 /etc/sudoers.d/cyberx\n"
            "visudo -c -f /etc/sudoers.d/cyberx\n"
        )
        client = self._connect()
        try:
            sftp = client.open_sftp()
            sftp.putfo(io.BytesIO(script.encode()), script_path)
            sftp.chmod(script_path, 0o700)
            sftp.close()

            out, stderr, code = self._exec(
                client, f"{self._sudo_prefix}/bin/bash {shlex.quote(script_path)} 2>&1"
            )
            self._exec(client, f"rm -f {shlex.quote(script_path)}")

            if code != 0:
                return {
                    "success": False,
                    "message": f"Prereq fix failed: {(out + stderr).strip()}",
                    "output": (out + stderr).strip(),
                }
            return {
                "success": True,
                "message": "Prerequisites installed — nginx-full, stream dir, and sudoers configured.",
                "output": (out + stderr).strip(),
            }
        finally:
            client.close()


# ---------------------------------------------------------------------------
# Async wrappers — use these from FastAPI route handlers
# ---------------------------------------------------------------------------

async def _run_ssh(fn, *args) -> dict:
    """Run a synchronous SSH operation in the bounded thread pool with semaphore."""
    async with _ssh_semaphore:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, fn, *args)


async def run_test_connection(ssh: SSHService) -> dict:
    return await _run_ssh(ssh.sync_test_connection)


async def run_check_prereqs(ssh: SSHService, stream_dir: str) -> dict:
    return await _run_ssh(ssh.sync_check_prereqs, stream_dir)


async def run_fix_prereqs(ssh: SSHService, stream_dir: str) -> dict:
    return await _run_ssh(ssh.sync_fix_prereqs, stream_dir)


async def run_check_nginx_setup(ssh: SSHService) -> dict:
    return await _run_ssh(ssh.sync_check_nginx_setup)


async def run_fix_nginx_setup(ssh: SSHService, stream_dir: str) -> dict:
    return await _run_ssh(ssh.sync_fix_nginx_setup, stream_dir)


async def run_check_port(ssh: SSHService, port: int, protocol: str) -> dict:
    return await _run_ssh(ssh.sync_check_port, port, protocol)


async def run_deploy_single(ssh: SSHService, stream_dir: str, stream) -> dict:
    return await _run_ssh(ssh.sync_deploy_single, stream_dir, stream)


async def run_remove_single(
    ssh: SSHService, stream_dir: str, stream_id: str, stream_name: str
) -> dict:
    return await _run_ssh(ssh.sync_remove_single, stream_dir, stream_id, stream_name)


async def run_deploy_all(ssh: SSHService, stream_dir: str, streams: list) -> dict:
    return await _run_ssh(ssh.sync_deploy_all, stream_dir, streams)
