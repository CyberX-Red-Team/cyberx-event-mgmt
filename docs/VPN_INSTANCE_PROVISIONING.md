# VPN Instance Auto-Assignment System

## Overview

The VPN instance auto-assignment system automatically assigns VPN credentials to OpenStack instances during provisioning. This enables instances to automatically download and configure their VPN connection via cloud-init without manual intervention.

## How It Works

### Architecture

```
┌─────────────────┐
│  Admin uploads  │
│  VPN configs    │
│  with type:     │
│  INSTANCE_AUTO_ │
│  ASSIGN         │
└────────┬────────┘
         │
         v
┌─────────────────┐     ┌──────────────────┐
│  Event created  │────>│  vpn_available   │
│                 │     │  = true          │
└─────────────────┘     └────────┬─────────┘
                                 │
                                 v
                        ┌────────────────┐
                        │  Instance      │
                        │  provisioned   │
                        └────────┬───────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                    v                         v
            ┌───────────────┐        ┌───────────────┐
            │  VPN assigned │        │  Token        │
            │  from pool    │        │  generated    │
            └───────┬───────┘        └───────┬───────┘
                    │                        │
                    └────────────┬───────────┘
                                 │
                                 v
                        ┌────────────────┐
                        │  Cloud-init    │
                        │  template      │
                        │  rendered with │
                        │  VPN variables │
                        └────────┬───────┘
                                 │
                                 v
                        ┌────────────────┐
                        │  Instance      │
                        │  boots and     │
                        │  runs cloud-   │
                        │  init          │
                        └────────┬───────┘
                                 │
                                 v
                        ┌────────────────┐
                        │  Cloud-init    │
                        │  calls API     │
                        │  with token    │
                        └────────┬───────┘
                                 │
                                 v
                        ┌────────────────┐
                        │  VPN config    │
                        │  downloaded    │
                        │  & installed   │
                        └────────────────┘
```

### VPN Assignment Types

The system supports three VPN assignment types:

1. **USER_REQUESTABLE** - VPNs available for participant self-service requests
2. **INSTANCE_AUTO_ASSIGN** - VPNs reserved for automatic instance assignment
3. **RESERVED** - VPNs held back from automatic assignment (for special purposes)

VPN pools are **completely separated** - user requests will never consume instance auto-assign VPNs and vice versa.

## Setup Guide

### Step 1: Upload VPN Configurations

1. Navigate to **Admin → VPN Management**
2. Click **Upload VPN Configs**
3. Select your ZIP file containing WireGuard `.conf` files
4. Choose **Assignment Type: Instance Auto-Assign**
5. Click **Upload**

The system will:
- Parse each configuration file
- Extract all WireGuard settings (including optional fields)
- Store configurations with `assignment_type = INSTANCE_AUTO_ASSIGN`
- Calculate SHA-256 hash for each config

### Step 2: Monitor VPN Pool

Check the **Instance Pool Statistics** card on the VPN Management page:

```
┌─────────────────────────────────┐
│  Instance Pool Statistics       │
├─────────────────────────────────┤
│  Total: 100                     │
│  Available: 45                  │
│  Assigned: 55                   │
└─────────────────────────────────┘
```

**Important**: Ensure you have enough VPNs before creating events. If the pool is exhausted, instance creation will fail with an error.

### Step 3: Create Event with VPN Assignment

1. Navigate to **Admin → Events**
2. Click **Create Event** or edit existing event
3. Enable the **VPN Available** checkbox
4. Save the event

All instances created in this event will automatically receive VPN credentials.

### Step 4: Create Cloud-Init Template

Create a cloud-init template that fetches and configures the VPN. See [Example Templates](#example-templates) below.

### Step 5: Provision Instances

When creating instances:

1. Select an event with **VPN Available = true**
2. Choose your cloud-init template with VPN setup
3. Click **Create Instance**

The system will automatically:
- Assign an available VPN from the instance pool
- Generate a secure single-use token (3-minute expiry)
- Render the cloud-init template with VPN variables
- Populate the instance's `vpn_ip` field
- Create the instance on OpenStack

## Example Templates

### Basic VPN Auto-Configuration Template

```yaml
#cloud-config
hostname: {{hostname}}

package_update: true
packages:
  - wireguard
  - curl

write_files:
  - path: /usr/local/bin/fetch_vpn_config.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      set -e

      echo "[$(date)] Fetching VPN config from backend..."

      # Retry logic: 3 attempts with 30s backoff
      for i in {1..3}; do
        if curl -f -H "Authorization: Bearer {{vpn_config_token}}" \
             "{{vpn_config_endpoint}}" \
             -o /etc/wireguard/wg0.conf; then
          echo "[$(date)] VPN config retrieved successfully"
          break
        else
          echo "[$(date)] Attempt $i failed, retrying in 30s..."
          sleep 30
        fi
      done

      # Verify config was downloaded
      if [ ! -f /etc/wireguard/wg0.conf ]; then
        echo "[$(date)] ERROR: Failed to download VPN config after 3 attempts"
        exit 1
      fi

      # Set secure permissions
      chmod 600 /etc/wireguard/wg0.conf

      # Enable and start WireGuard
      systemctl enable wg-quick@wg0
      systemctl start wg-quick@wg0

      echo "[$(date)] VPN configured and running"

runcmd:
  - /usr/local/bin/fetch_vpn_config.sh >> /var/log/vpn-setup.log 2>&1
```

### Advanced Template with Verification

```yaml
#cloud-config
hostname: {{hostname}}

package_update: true
packages:
  - wireguard
  - curl
  - jq

write_files:
  - path: /usr/local/bin/fetch_vpn_config.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      set -e

      LOGFILE="/var/log/vpn-setup.log"
      ENDPOINT="{{vpn_config_endpoint}}"
      TOKEN="{{vpn_config_token}}"

      log() {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
      }

      log "Starting VPN configuration..."
      log "Endpoint: $ENDPOINT"

      # Fetch VPN config with retries
      MAX_ATTEMPTS=3
      RETRY_DELAY=30

      for attempt in $(seq 1 $MAX_ATTEMPTS); do
        log "Attempt $attempt of $MAX_ATTEMPTS..."

        if curl -f -s -H "Authorization: Bearer $TOKEN" \
             "$ENDPOINT" -o /etc/wireguard/wg0.conf; then
          log "VPN config retrieved successfully"
          break
        else
          EXIT_CODE=$?
          log "ERROR: curl failed with exit code $EXIT_CODE"

          if [ $attempt -lt $MAX_ATTEMPTS ]; then
            log "Retrying in ${RETRY_DELAY}s..."
            sleep $RETRY_DELAY
          else
            log "FATAL: Failed to download VPN config after $MAX_ATTEMPTS attempts"
            exit 1
          fi
        fi
      done

      # Verify config file exists and has content
      if [ ! -f /etc/wireguard/wg0.conf ]; then
        log "FATAL: Config file does not exist"
        exit 1
      fi

      if [ ! -s /etc/wireguard/wg0.conf ]; then
        log "FATAL: Config file is empty"
        exit 1
      fi

      # Verify config contains required fields
      if ! grep -q "PrivateKey" /etc/wireguard/wg0.conf; then
        log "FATAL: Config missing PrivateKey"
        exit 1
      fi

      # Set secure permissions
      chmod 600 /etc/wireguard/wg0.conf
      log "Set config file permissions to 600"

      # Enable and start WireGuard
      systemctl enable wg-quick@wg0
      systemctl start wg-quick@wg0
      log "WireGuard service enabled and started"

      # Wait for interface to come up
      sleep 5

      # Verify VPN is running
      if systemctl is-active --quiet wg-quick@wg0; then
        log "SUCCESS: VPN is running"

        # Log VPN interface status
        wg show wg0 | while IFS= read -r line; do
          log "  $line"
        done
      else
        log "ERROR: VPN service failed to start"
        journalctl -u wg-quick@wg0 --no-pager | tail -20 | while IFS= read -r line; do
          log "  $line"
        done
        exit 1
      fi

runcmd:
  - /usr/local/bin/fetch_vpn_config.sh
```

### Template with SSH Keys

```yaml
#cloud-config
hostname: {{hostname}}

users:
  - name: ubuntu
    ssh_authorized_keys:
      {{ssh_public_key}}
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
    groups: sudo
    shell: /bin/bash

package_update: true
packages:
  - wireguard
  - curl

write_files:
  - path: /usr/local/bin/fetch_vpn_config.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      set -e

      for i in {1..3}; do
        if curl -f -H "Authorization: Bearer {{vpn_config_token}}" \
             "{{vpn_config_endpoint}}" \
             -o /etc/wireguard/wg0.conf; then
          chmod 600 /etc/wireguard/wg0.conf
          systemctl enable wg-quick@wg0
          systemctl start wg-quick@wg0
          echo "VPN configured successfully" | tee -a /var/log/vpn-setup.log
          exit 0
        fi
        sleep 30
      done

      echo "ERROR: Failed to configure VPN" | tee -a /var/log/vpn-setup.log
      exit 1

runcmd:
  - /usr/local/bin/fetch_vpn_config.sh
```

## Available Template Variables

When an instance is created with VPN auto-assignment enabled, the following variables are available in cloud-init templates:

| Variable | Description | Example |
|----------|-------------|---------|
| `{{hostname}}` | Instance name | `participant-vm-001` |
| `{{vpn_config_token}}` | Single-use token for API authentication | `a8f3k2... (48 chars)` |
| `{{vpn_config_endpoint}}` | Backend API endpoint URL | `https://events.example.com/api/cloud-init/vpn-config` |
| `{{ssh_public_key}}` | SSH public key (if configured) | `ssh-rsa AAAA...` |

**Important**: `vpn_config_token` is the **raw token** (not hashed) - use it directly in the Authorization header.

## Security Features

### Token Security

- **Single-use**: Token is deleted from database after first successful retrieval
- **Time-limited**: 3-minute expiry window (configurable)
- **Hash storage**: Only SHA-256 hash stored in database, never plaintext
- **No cookies/sessions**: Uses Bearer token authentication suitable for cloud-init

### Token Format

```
Authorization: Bearer <48-character-token>
```

Example:
```bash
curl -H "Authorization: Bearer a8f3k2j9m1n4p7q5r8s6t3u1v9w2x4y7z5" \
     https://events.example.com/api/cloud-init/vpn-config
```

### Race Condition Prevention

- **Row-level locking**: `SELECT FOR UPDATE with skip_locked` prevents concurrent VPN assignment
- **Atomic operations**: Assignment happens in single database transaction
- **Idempotent**: Multiple calls to assign VPN to same instance are safe

## API Endpoint

### GET /api/cloud-init/vpn-config

Retrieves VPN configuration for instance using token authentication.

**Headers:**
```
Authorization: Bearer <token>
```

**Response (200 OK):**
```json
{
  "config": "[Interface]\nPrivateKey = ...\n[Peer]\n...",
  "ipv4_address": "10.20.200.149",
  "interface_ip": "10.20.200.149,fd00:a:14:c8:95::95",
  "endpoint": "216.208.235.11:51020"
}
```

**Errors:**
- `401 Unauthorized` - Invalid, expired, or already-used token
- `404 Not Found` - No VPN assigned to instance

## Troubleshooting

### Instance Creation Fails with "No VPN Available"

**Symptom**: Instance creation fails with error message about VPN pool exhaustion.

**Solution**:
1. Check instance pool statistics
2. Upload more VPN configs with `assignment_type = INSTANCE_AUTO_ASSIGN`
3. Or temporarily disable VPN for the event

### VPN Not Configured on Instance

**Symptom**: Instance boots but VPN is not installed.

**Debugging steps**:

1. **Check cloud-init logs**:
   ```bash
   ssh ubuntu@<instance-ip>
   sudo cat /var/log/cloud-init-output.log
   sudo cat /var/log/vpn-setup.log
   ```

2. **Check if token expired**:
   - Token has 3-minute expiry
   - If cloud-init runs slowly, token may expire
   - Solution: Increase token expiry in settings (if needed)

3. **Check network connectivity**:
   ```bash
   curl -v https://events.example.com/api/cloud-init/vpn-config
   ```
   - Ensure instance can reach backend API
   - Check security groups allow outbound HTTPS

4. **Verify cloud-init template**:
   - Ensure template includes VPN fetch script
   - Check template variables are correct: `{{vpn_config_token}}` and `{{vpn_config_endpoint}}`

### Token Already Used Error

**Symptom**: VPN config request fails with "Invalid or expired VPN config token".

**Cause**: Token was already consumed by a previous request (single-use).

**Solution**:
- Tokens are single-use for security
- If instance needs to re-fetch config, it must be re-provisioned
- **Do not** retry VPN fetch in cloud-init if first attempt succeeds

### VPN Pool Exhausted

**Symptom**: Cannot create instances, error "No available VPN credentials".

**Immediate fix**:
1. Navigate to **Admin → VPN Management**
2. Check **Instance Pool Statistics**
3. If available = 0, upload more VPNs

**Long-term solutions**:
1. Monitor pool usage regularly
2. Set up alerts when `available < 10`
3. Maintain buffer of VPNs (e.g., always keep 20% available)

### Instance Deleted but VPN Still Assigned

**Behavior**: This is **expected and by design**.

**Reason**: VPNs remain assigned to deleted instances for audit trail purposes.

**To release VPNs manually**:
1. Navigate to **Admin → VPN Management**
2. Find VPNs assigned to deleted instances
3. Click **Release** to make them available again

## Monitoring & Observability

### Key Metrics to Track

1. **VPN Pool Utilization**:
   - `available / total` ratio
   - Alert when `available < 10`

2. **Token Expiry Rate**:
   - Track tokens that expired before use
   - May indicate cloud-init slowness

3. **Failed VPN Fetches**:
   - Monitor 401/404 errors on cloud-init endpoint
   - May indicate token issues or misconfiguration

4. **Average Fetch Time**:
   - Time from instance creation to VPN fetch
   - Should be < 2 minutes typically

### Logs

VPN assignment events are logged with context:

```
INFO: Assigned VPN 123 to instance 456 (name: participant-vm-001)
INFO: Generated VPN config token for instance participant-vm-001
INFO: VPN config retrieved by instance 456 from IP: 192.168.1.100
INFO: VPN config token consumed for instance 456
```

Search logs for:
- `"Assigned VPN"` - Successful assignments
- `"VPN config retrieved"` - Successful fetches
- `"No available VPN"` - Pool exhaustion
- `"Invalid or expired VPN config token"` - Token issues

## Best Practices

### 1. Maintain VPN Pool Buffer

Always keep at least 20% of your instance pool available:

```
If max concurrent instances = 50
Then upload at least 60-70 VPN configs
```

### 2. Use Separate VPN Pools

Keep user self-service and instance auto-assign pools completely separate:

- **User pool**: Upload with `assignment_type = USER_REQUESTABLE`
- **Instance pool**: Upload with `assignment_type = INSTANCE_AUTO_ASSIGN`

### 3. Test Cloud-Init Templates

Before using in production:

1. Create test event with `vpn_available = true`
2. Provision single test instance
3. SSH to instance and verify:
   ```bash
   sudo wg show
   ip addr show wg0
   ```
4. Check logs: `cat /var/log/vpn-setup.log`

### 4. Set Appropriate Token Expiry

Default: 3 minutes

- Too short: May expire before slow cloud-init finishes
- Too long: Security risk if token leaks

Adjust based on your instance boot times.

### 5. Monitor Pool Usage

Set up alerts:
- When `available < 10`
- When `available / total < 0.2` (20%)
- When pool exhausted events occur

## Admin Endpoints

### Get Instance Pool Statistics

```
GET /api/vpn/stats/instance-pool
```

**Response:**
```json
{
  "total": 100,
  "available": 45,
  "assigned": 55
}
```

### Update VPN Assignment Type

```
PATCH /api/vpn/credentials/{vpn_id}/assignment-type

{
  "assignment_type": "INSTANCE_AUTO_ASSIGN"
}
```

**Note**: Can only change if VPN is not currently assigned.

### Bulk Update Assignment Type

```
POST /api/vpn/bulk-update-assignment-type

{
  "vpn_ids": [1, 2, 3, 4, 5],
  "assignment_type": "INSTANCE_AUTO_ASSIGN"
}
```

## VPN Lifecycle

```
[Upload] → INSTANCE_AUTO_ASSIGN, is_available=true
    ↓
[Event with vpn_available=true] → Instance created
    ↓
[VPN Assigned] → assigned_to_instance_id set, is_available=false
    ↓
[Cloud-Init Fetches] → Token consumed, config installed
    ↓
[Instance Running] → VPN active
    ↓
[Instance Deleted] → VPN REMAINS assigned (audit trail)
    ↓
[Manual Release] → is_available=true (optional)
```

## FAQ

**Q: Can one VPN be assigned to multiple instances?**

A: No. Each VPN is assigned to at most one instance (or one user), never both.

**Q: What happens if I delete an instance?**

A: The VPN remains assigned to that instance for audit purposes. To reuse it, you must manually release it via the admin UI.

**Q: Can I change a VPN's assignment type after upload?**

A: Yes, but only if it's not currently assigned. Use the assignment type management endpoints.

**Q: What if the VPN pool runs out during instance creation?**

A: Instance creation will fail with an error message. Upload more VPN configs or disable VPN for the event.

**Q: How do I verify a VPN was assigned correctly?**

A: Check the instance details - it should show the `vpn_ip` field populated. Also check VPN admin page to see the assignment.

**Q: Can I use the same cloud-init template for instances with and without VPNs?**

A: Yes, but use conditional logic in the template to check if VPN variables exist before running VPN setup.

**Q: What's the maximum token expiry time?**

A: While configurable, we recommend keeping it under 5 minutes for security. Default is 3 minutes.

**Q: Do I need to configure VPN server settings?**

A: No, VPN configs preserve all settings from the uploaded files. Server-wide defaults are only used if specific fields are missing.

## Related Documentation

- [VPN Management Guide](VPN_MANAGEMENT.md)
- [Cloud-Init Templates Guide](CLOUD_INIT_TEMPLATES.md)
- [OpenStack Instance Provisioning](INSTANCE_PROVISIONING.md)
- [Event Management](EVENT_MANAGEMENT.md)
