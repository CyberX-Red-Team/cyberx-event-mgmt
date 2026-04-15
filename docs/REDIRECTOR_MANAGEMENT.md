# Redirector Management System

## Overview

The Redirector Management system allows operators to manage nginx stream proxy servers (redirectors) that route traffic between external listeners and internal command-and-control (C2) teamservers. Redirectors are configured remotely via SSH and support TCP, UDP, and DNS stream proxying with optional SSL/TLS termination and IP-based access control.

Two types of redirectors are supported:

- **BYOD (Bring Your Own Device)** -- operator-provided servers bootstrapped with the event's infrastructure SSH key
- **CyberX** -- instances provisioned through the platform's cloud infrastructure, pre-configured via cloud-init

## How It Works

### Architecture

```
                                      ┌─────────────────────────┐
                                      │   CyberX Event Mgmt     │
                                      │   Platform               │
                                      │                         │
                                      │  ┌───────────────────┐  │
                                      │  │  Redirector API    │  │
                                      │  │  /api/redirectors  │  │
                                      │  └────────┬──────────┘  │
                                      │           │ SSH          │
                                      └───────────┼─────────────┘
                                                  │
                          ┌───────────────────────┼───────────────────────┐
                          │                       │                       │
                          v                       v                       v
                  ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
                  │  Redirector 1 │      │  Redirector 2 │      │  Redirector N │
                  │  (BYOD)       │      │  (CyberX)     │      │  (CyberX)     │
                  │               │      │               │      │               │
                  │  nginx stream │      │  nginx stream │      │  nginx stream │
                  │  ┌─────────┐  │      │  ┌─────────┐  │      │  ┌─────────┐  │
                  │  │ :443 → ─┼──┼──┐   │  │ :80  → ─┼──┼──┐   │  │ :53  → ─┼──┼──┐
                  │  │ :8443→ ─┼──┼──┼─  │  │ :443 → ─┼──┼──┼─  │  │ :8080→ ─┼──┼──┼─
                  │  └─────────┘  │  │ │  │  └─────────┘  │  │ │  │  └─────────┘  │  │ │
                  └───────────────┘  │ │  └───────────────┘  │ │  └───────────────┘  │ │
                                     │ │                     │ │                     │ │
                                     v v                     v v                     v v
                              ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
                              │ C2 Server 1 │         │ C2 Server 2 │         │ C2 Server 3 │
                              └─────────────┘         └─────────────┘         └─────────────┘
```

### Data Flow

1. **Operator creates a redirector** via the admin portal or participant portal
2. **Platform connects via SSH** to the remote server using the infrastructure key (or BYOD key during bootstrap)
3. **Stream configs are written** as nginx `.conf` files to the redirector's stream directory
4. **nginx is reloaded** to apply the configuration
5. **Traffic flows** from external clients through the redirector to the upstream C2 server

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Redirector model | `backend/app/models/redirector.py` | Redirector + StreamConfig ORM models |
| Redirector service | `backend/app/services/redirector_service.py` | CRUD with Fernet encryption for SSH keys |
| SSH service | `backend/app/services/ssh_service.py` | Remote SSH operations (deploy, test, prereqs) |
| nginx config service | `backend/app/services/nginx_config_service.py` | Generate nginx stream config files |
| API routes | `backend/app/api/routes/redirectors.py` | REST API (CRUD, deploy, CyberX flow) |
| Page routes | `backend/app/api/routes/redirectors_pages.py` | HTML pages (admin + participant) |
| Admin UI | `frontend/templates/pages/redirectors/` | Admin list + detail pages |
| Participant UI | `frontend/templates/pages/participant/portal.html` | Redirectors card on participant portal |
| Participant detail | `frontend/templates/pages/participant/redirector_detail.html` | Stream management for participants |

---

## Redirector Types

### BYOD Redirector

For operator-provided servers (e.g., a VPS, cloud instance from another provider, or physical server).

**Flow:**
1. Operator provides: name, IP, SSH port, username, PEM private key
2. Platform connects using the provided SSH key
3. Platform deploys the event's infrastructure public key to `~/.ssh/authorized_keys`
4. BYOD key is deleted from the database
5. All future SSH operations use the infrastructure key

**Requirements:**
- SSH access with public key authentication
- nginx installed with stream module (`ngx_stream_module`)
- The SSH user must have sudo access (NOPASSWD preferred) for nginx operations

### CyberX Redirector

For instances provisioned through the platform's cloud infrastructure (OpenStack or DigitalOcean).

**Flow:**
1. Operator selects an existing ACTIVE instance from a redirector template, or provisions a new one
2. The instance already has the infrastructure key injected via cloud-init
3. Platform auto-populates name, IP, SSH username from the instance and template
4. Redirector is registered and ready immediately

**Requirements:**
- An instance template marked as a redirector template (`is_redirector=True` or using "Redirector Init" cloud-init)
- An active event with an SSH key pair generated
- The cloud-init template must install nginx with stream module

---

## Permissions

| Permission | Role Defaults | Description |
|-----------|---------------|-------------|
| `redirectors.view` | Admin, Sponsor, Invitee | View own redirectors and stream configs |
| `redirectors.manage` | Admin, Sponsor, Invitee | Create, edit, delete, deploy redirectors and streams |
| `redirectors.view_all` | Admin only | View all redirectors across all users |

**Owner scoping:** Non-admin users only see redirectors where `owner_id` matches their user ID.

**UI access:**
- **Admins** -- Redirectors sidebar item at `/admin/redirectors`
- **Sponsors/Invitees** -- Redirectors card on the participant portal at `/portal`, detail pages at `/portal/redirectors/{id}`

---

## Setup Guide

### Prerequisites

1. **Event with SSH key pair** -- Navigate to the active event settings and generate an SSH key pair. This is used as the infrastructure key for all redirector management.

2. **For CyberX redirectors:** An instance template with:
   - `is_redirector` checkbox enabled, OR
   - Cloud-init template named "Redirector Init"
   - `ssh_username` set (default: `root`)

3. **For BYOD redirectors:** A remote server with:
   - SSH access via public key authentication
   - nginx installed with stream module
   - sudo access for the SSH user

### Adding a BYOD Redirector

1. Navigate to the Redirectors page (admin sidebar or participant portal card)
2. Click **Add Redirector** > **Add BYOD Redirector**
3. Fill in:
   - **Name** -- unique identifier for this redirector
   - **IP Address** -- public IP of the server
   - **SSH Port** -- default 22
   - **SSH Username** -- the SSH user (e.g., `debian`, `ubuntu`, `root`)
   - **SSH Private Key (PEM)** -- full PEM content (used once for bootstrap, then deleted)
   - **Key Passphrase** -- optional, if the key is encrypted
   - **nginx Stream Directory** -- default `/etc/nginx/stream.d`
4. Click **Add Redirector**

The platform will:
- Test the SSH connection
- Deploy the infrastructure public key to the server
- Delete the BYOD key from the database
- Set initial status (online/offline)

### Adding a CyberX Redirector

1. Navigate to the Redirectors page
2. Click **Add Redirector** > **Add CyberX Redirector**
3. **Select an existing instance** from the list (ACTIVE instances from redirector templates not already managed), OR
4. **Provision a new one** by selecting a redirector template and entering an instance name
5. If provisioning, wait for the instance to become ACTIVE (polled automatically)
6. Confirm the redirector name, IP, and nginx directory
7. Click **Add Redirector**

### Configuring Stream Proxies

1. Navigate to the redirector detail page (click the redirector name)
2. Click **Add Stream** to create a new stream config
3. Configure:
   - **Name** -- descriptive name (e.g., "HTTPS Beacon")
   - **Protocol** -- TCP, UDP, or DNS
   - **Listen Port** -- port the redirector listens on
   - **Upstream IP:Port** -- C2 teamserver address
   - **Access Control** (optional) -- restrict by source CIDR
   - **SSL/TLS** (optional, TCP only) -- terminate TLS on the redirector
4. Click **Save Stream** -- stream is created as disabled
5. Use the **Enable** toggle to activate and deploy the stream

---

## Instance Deletion and Isolated Redirectors

When a cloud instance that is under redirector management is deleted, the platform handles it differently based on the user's role:

### Admin Deletion

Admins can delete instances under management. A confirmation warning shows the redirector name and stream count. Upon deletion:
- The linked redirector's status is set to **isolated**
- Stream configurations are preserved in the database
- The isolated redirector detail page shows a warning banner with options to:
  - **Re-home to New IP** -- update the redirector's IP to point to a replacement server
  - **Delete Config** -- remove the redirector and all stream configs permanently

### Sponsor / Invitee Deletion

Non-admin users are **blocked** from deleting instances under redirector management. They must remove the instance from redirector management first (delete the redirector entry), then delete the instance.

### Redirector Status Values

| Status | Badge | Description |
|--------|-------|-------------|
| `unknown` | Grey | Initial state, not yet tested |
| `online` | Green | SSH connection test succeeded |
| `offline` | Red | SSH connection test failed |
| `isolated` | Yellow | Source instance deleted, redirector orphaned |

---

## Stream Config Details

Each stream config generates an nginx stream server block written to the redirector's stream directory.

### Protocols

| Protocol | Description | nginx Directive |
|----------|-------------|-----------------|
| TCP | Layer 4 TCP proxy | `proxy_pass upstream:port;` |
| UDP | Layer 4 UDP proxy | `proxy_pass upstream:port;` with `udp` |
| DNS | DNS proxy (UDP on port 53) | `proxy_pass upstream:port;` with `udp` + `proxy_responses 1` |

### Access Control

When enabled, generates `allow`/`deny` rules from a CIDR list:

```nginx
allow 10.0.0.0/8;
allow 203.0.113.0/24;
deny all;
```

Only traffic from listed CIDRs is accepted. All other traffic is dropped.

### SSL/TLS Bridging

When **SSL Enabled** is checked on a TCP stream, the redirector performs
**TLS bridging** — it terminates the client's TLS handshake with a
legitimate certificate stored on the redirector, then opens a fresh TLS
connection to the upstream teamserver. This lets C2 teamservers keep
using their own self-signed certificates while clients see a trusted
public cert at the edge.

This is bridging (terminate + re-origin), **not** passthrough:

- The public cert lives on the redirector (operator-managed).
- The teamserver's self-signed cert lives on the teamserver, unchanged.
- nginx sits between the two and re-encrypts in both directions.

```nginx
server {
    listen 443 ssl;
    proxy_pass 10.32.88.189:443;
    ssl_certificate /etc/ssl/certs/legit.pem;
    ssl_certificate_key /etc/ssl/private/legit.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    proxy_ssl on;            # re-encrypt to upstream
    proxy_ssl_verify off;    # accept upstream self-signed cert
}
```

`proxy_ssl on;` is the load-bearing directive here — without it, nginx
sends **plaintext** to the upstream TLS listener and the teamserver
drops the connection immediately. `proxy_ssl_verify off;` is required
because teamservers typically use self-signed certs that nginx has no
CA chain for; trust is asserted by the infra operator, not by PKI.

Prerequisites on the redirector:

- The certificate and private key files must already exist at the
  paths supplied in **SSL Certificate Path** and **SSL Key Path**.
- The key file must be readable by the nginx user (`www-data` on
  Debian/Ubuntu/Kali).

### Custom Config Override

The **View/Edit Config** modal lets operators hand-edit the nginx config
for a stream when the structured fields don't cover what they need —
advanced nginx directives, experimental tuning, or one-off tweaks that
don't deserve their own schema field.

**When to use it:**
- You need an nginx directive the wizard doesn't expose (e.g. custom
  `proxy_buffer_size`, `real_ip_header`, or a `map` block).
- You want to test a config change without round-tripping through a code
  deploy.
- You're debugging a broken stream and need to inspect exactly what the
  generator would produce, then poke at it.

**When to avoid it:** if the change is expressible via the structured
fields (ports, upstream, SSL, ACLs), use the Edit Stream form instead —
it stays in sync with wizard validation and survives schema changes.

**Save flow:**

1. Validate basic structure on the server — non-empty, balanced braces,
   size ≤ 32 KB, contains a `server` block.
2. Persist the override on the `stream_configs` row.
3. SFTP the file onto the redirector, run `nginx -t`, reload nginx.
4. On `nginx -t` failure, roll back the on-disk file (restore previous
   content or delete if it was new) and mark the stream
   `deployed=false`. The DB override is **kept** so the operator can
   keep editing their broken draft instead of starting over.

**While an override is active**, the generator path is bypassed
entirely: edits to structured fields (listen_port, cs_ip, SSL options,
ACLs) do not change what is deployed. The modal shows a drift banner
and a **Reset to Generated** button that clears the override and
redeploys the rendered config in one step.

Backed by `custom_config_override TEXT NULL` on `stream_configs` and the
`PUT|DELETE /api/redirectors/{id}/streams/{sid}/config` endpoints. Audit
events `STREAM_CONFIG_OVERRIDE_SET` and `STREAM_CONFIG_OVERRIDE_RESET`
record only the override's byte length — never its content — so
operators can embed sensitive strings in comments without them appearing
in audit logs.

---

## API Reference

### Redirector CRUD

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET /api/redirectors/` | List redirectors (owner-scoped) |
| `POST /api/redirectors/` | Create BYOD redirector |
| `GET /api/redirectors/{id}` | Get redirector details |
| `PUT /api/redirectors/{id}` | Update redirector |
| `DELETE /api/redirectors/{id}` | Delete redirector + cascade stream configs |

### CyberX Flow

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET /api/redirectors/available-instances` | List ACTIVE instances from redirector templates not yet managed |
| `GET /api/redirectors/redirector-templates` | List active redirector instance templates |
| `POST /api/redirectors/from-instance` | Create redirector from existing instance |
| `POST /api/redirectors/provision-and-register` | Provision new instance from redirector template |
| `GET /api/redirectors/instance-status/{id}` | Poll instance provisioning status |

### SSH Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST /api/redirectors/{id}/test-connection` | Test SSH + check nginx stream module |
| `POST /api/redirectors/{id}/check-prereqs` | Check CyberX prerequisites |
| `POST /api/redirectors/{id}/fix-prereqs` | Auto-fix prerequisites (requires sudo) |
| `POST /api/redirectors/{id}/check-nginx-setup` | Check nginx configuration issues |
| `POST /api/redirectors/{id}/fix-nginx-setup` | Auto-fix nginx configuration |
| `POST /api/redirectors/{id}/check-port` | Check if a port is in use |

### Stream Config Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET /api/redirectors/{id}/streams` | List stream configs |
| `POST /api/redirectors/{id}/streams` | Create stream config |
| `GET /api/redirectors/{id}/streams/{sid}` | Get stream config |
| `PUT /api/redirectors/{id}/streams/{sid}` | Update stream config |
| `DELETE /api/redirectors/{id}/streams/{sid}` | Delete stream config |
| `POST /api/redirectors/{id}/streams/{sid}/enable` | Enable + deploy stream |
| `POST /api/redirectors/{id}/streams/{sid}/deploy` | Deploy stream config to redirector |
| `POST /api/redirectors/{id}/streams/{sid}/remove` | Remove stream config file from redirector |
| `GET /api/redirectors/{id}/streams/{sid}/preview` | Preview generated nginx config |
| `PUT /api/redirectors/{id}/streams/{sid}/config` | Install a hand-edited custom config override and deploy it (test + reload with rollback) |
| `DELETE /api/redirectors/{id}/streams/{sid}/config` | Clear the custom override and redeploy the generated config |
| `POST /api/redirectors/{id}/deploy-all` | Enable all streams + deploy |
| `POST /api/redirectors/{id}/disable-all` | Disable all streams + remove config files |

The regular `PUT /api/redirectors/{id}/streams/{sid}` auto-redeploys to the
redirector whenever a deploy-sensitive field changes (listen port, proxy
target, SSL options, ACLs) and the stream was already deployed. This keeps
the on-disk config on the redirector in sync with the database and prevents
silent drift. Cosmetic fields (name) still skip the redeploy.

---

## Security

### SSH Key Management

- **BYOD keys** are Fernet-encrypted (AES-128 CBC + HMAC-SHA256) at rest in the database
- BYOD keys are **deleted after bootstrap** -- the infrastructure key is used for all subsequent operations
- **Infrastructure keys** are stored on the Event model and shared across all redirectors for the event
- SSH private keys are **never returned in API responses** -- always `"**REDACTED**"`
- Decrypted keys exist only as short-lived local variables in route handlers

### Access Control

- All endpoints require authentication via session cookie
- Permission-based access: `redirectors.view`, `redirectors.manage`, `redirectors.view_all`
- Owner scoping: non-admins see only their own redirectors
- CSRF protection on all state-changing operations

### Input Validation

- IP addresses validated via `ipaddress.ip_address()`
- SSH usernames restricted to `[a-zA-Z0-9_.-]`
- nginx stream directory validated against safe path regex `^/[a-zA-Z0-9_./-]+$`
- Stream names reject nginx-unsafe characters (semicolons, newlines, braces)
- CIDR lists validated via `ipaddress.ip_network()`
- SSL paths validated against safe path regex

### Audit Logging

All security-relevant actions are logged via `AuditService`:
- `REDIRECTOR_CREATE` / `REDIRECTOR_CREATE_FROM_INSTANCE`
- `REDIRECTOR_UPDATE` / `REDIRECTOR_DELETE`
- `REDIRECTOR_DEPLOY_ALL` / `REDIRECTOR_DISABLE_ALL`
- `INFRA_KEY_DEPLOYED`
- `REDIRECTOR_INSTANCE_PROVISIONED`

---

## Troubleshooting

### Connection Test Fails

**Symptom:** Redirector shows "offline" status after creation or test.

**Debugging steps:**
1. Verify the IP address is reachable from the platform server
2. Verify SSH port is open: `nc -zv <ip> <port>`
3. Verify the SSH user and key are correct
4. Check if the infrastructure key is in `~/.ssh/authorized_keys` on the redirector
5. Check platform logs for SSH error details

### Prerequisites Check Fails

**Symptom:** Prerequisites accordion shows failures.

**Common issues:**
- **nginx not installed** -- install nginx with stream module
- **Stream module missing** -- install `libnginx-mod-stream` (Debian/Ubuntu) or enable in nginx build
- **Stream directory missing** -- create `/etc/nginx/stream.d` and add `stream { include /etc/nginx/stream.d/*.conf; }` to nginx.conf
- **sudo not available** -- the SSH user needs `NOPASSWD` sudo for nginx operations
- **apache2 blocking ports** -- Kali preinstalls apache2 and enables it by default, which holds ports 80/443 and prevents nginx from binding them. The `apache2_not_blocking` check detects this; **Fix Prerequisites** stops and disables apache2 (without uninstalling it, so operators can re-enable manually).

Use **Fix Prerequisites** to auto-resolve common issues (requires sudo).

### Deploy Fails

**Symptom:** Stream deploy returns error.

**Common causes:**
- nginx syntax error in generated config -- check the **Preview** to inspect the config
- Port already in use -- use **Check Port** to detect conflicts
- nginx reload failed -- check nginx error log on the redirector: `sudo nginx -t`
- SSH connection lost -- test connection first

### BYOD Key Bootstrap Fails

**Symptom:** Redirector created but infrastructure key not deployed. BYOD key retained.

**Cause:** SSH connection succeeded but key deployment failed (permissions, missing `.ssh` directory, etc.)

**Fix:**
1. SSH into the redirector manually
2. Add the event's public key to `~/.ssh/authorized_keys`
3. Set permissions: `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys`

### CyberX Instance Not Appearing

**Symptom:** No instances shown in the CyberX redirector picker.

**Check:**
1. Instance must be **ACTIVE** (not BUILDING, ERROR, or DELETED)
2. Instance must be created from a **redirector template** (`is_redirector=True` or "Redirector Init" cloud-init)
3. Instance must not already be linked to a managed redirector
4. Instance must belong to the current user (or user must have `redirectors.view_all`)

---

## nginx Stream Module Reference

The redirector requires nginx with the stream module. The platform writes individual `.conf` files to the stream directory.

### Required nginx.conf Setup

```nginx
# /etc/nginx/nginx.conf (add at the top level, outside http block)
stream {
    include /etc/nginx/stream.d/*.conf;
}
```

### Generated Config Example (TCP with SSL + ACL)

```nginx
# /etc/nginx/stream.d/cyberx_<uuid>.conf
# CyberX stream: HTTPS Beacon (tcp)
# Redirector: prod-redir-01
# Generated: 2026-03-30T12:00:00Z

server {
    listen 443;
    proxy_pass 10.0.0.5:8443;

    # SSL/TLS termination
    ssl_preread off;
    ssl_certificate /etc/ssl/certs/redir.pem;
    ssl_certificate_key /etc/ssl/private/redir.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Access control
    allow 10.0.0.0/8;
    allow 203.0.113.0/24;
    deny all;
}
```

### Generated Config Example (DNS)

```nginx
# /etc/nginx/stream.d/cyberx_<uuid>.conf
server {
    listen 53 udp;
    proxy_pass 10.0.0.5:53;
    proxy_responses 1;
}
```

---

## Related Documentation

- [Developer Guide](../DEVELOPER_GUIDE.md) -- Architecture reference and new feature checklist
- [Roles & Permissions](ROLES_AND_PERMISSIONS.md) -- Permission system and role defaults
- [VPN Instance Provisioning](VPN_INSTANCE_PROVISIONING.md) -- VPN auto-assignment for cloud instances
