# Cloud-Init Template Variables

This document lists all available variables for cloud-init template substitution.

## Available Variables

### Always Available
These variables are automatically provided for every instance:

| Variable | Description | Example Value |
|----------|-------------|---------------|
| `{{hostname}}` | Instance hostname/name | `participant-001` |
| `{{instance_name}}` | Instance name (same as hostname) | `participant-001` |

### SSH Keys (Conditional)
Automatically injected if SSH keys are configured:

| Variable | Description | Notes |
|----------|-------------|-------|
| `{{ssh_public_key}}` | SSH public key(s) | If both individual and event keys exist, both are included as separate list items |

**Important:** If no SSH keys are configured, the entire `ssh_authorized_keys:` section will be automatically removed from the rendered template.

### Config-Based Variables (Optional)
These variables are available if configured in `.env` or environment:

| Variable | Config Setting | Description |
|----------|----------------|-------------|
| `{{license_server}}` | _(auto: `FRONTEND_URL/api/license`)_ | License API endpoint (automatically derived from FRONTEND_URL) |
| `{{license_token}}` | _(auto-generated)_ | **Unique per-instance** - Cryptographically-secure 43-character token, generated fresh for each instance |
| `{{download_base_url}}` | `DOWNLOAD_BASE_URL` | Base URL for file downloads |
| `{{vpn_server_public_key}}` | `VPN_SERVER_PUBLIC_KEY` | WireGuard server public key |
| `{{vpn_server_endpoint}}` | `VPN_SERVER_ENDPOINT` | WireGuard server endpoint (IP:port) |
| `{{vpn_dns_servers}}` | `VPN_DNS_SERVERS` | VPN DNS servers (comma-separated) |
| `{{vpn_allowed_ips}}` | `VPN_ALLOWED_IPS` | Allowed IPs for VPN routing |

## Configuration

### Step 1: Set Environment Variables

Add to your `.env` file:

```bash
# License Configuration
# License server URL is automatically derived from FRONTEND_URL + "/api/license"
# No additional configuration needed - just ensure FRONTEND_URL is set correctly
FRONTEND_URL=https://dev.cyberxredteam.org

# Download URLs
DOWNLOAD_BASE_URL=https://files.example.com

# VPN Configuration (if using WireGuard)
VPN_SERVER_PUBLIC_KEY=your-wg-public-key
VPN_SERVER_ENDPOINT=vpn.example.com:51820
VPN_DNS_SERVERS=10.20.200.1
VPN_ALLOWED_IPS=10.0.0.0/8,fd00:a::/32
```

### Step 2: Use Variables in Templates

Example cloud-init template:

```yaml
#cloud-config

# SSH Keys (auto-populated or removed if none available)
ssh_authorized_keys:
  - {{ssh_public_key}}

# License activation
runcmd:
  - |
    python3 /opt/hexio/hexio_setup.py \
      --license-url "{{license_server}}" \
      --license-token "{{license_token}}" \
      --root-password "password123" \
      --quiet
```

## Variable Handling

### Substitution
- All `{{variable_name}}` placeholders are replaced with their values
- If a variable is not provided, a warning is logged but substitution continues

### Auto-Cleanup
The template renderer automatically removes:
1. Empty list items: `  - ` (after substitution with empty string)
2. Unsubstituted placeholders: `  - {{missing_var}}`
3. Parent keys with no children: `ssh_authorized_keys:` (when all items removed)

This prevents YAML parsing errors in cloud-init.

## Future Enhancements

The following will be implemented as part of the full OpenStack integration:

### ✅ Per-Instance License Tokens (IMPLEMENTED)
- **Status:** ✅ Complete
- **Implementation:** Each instance gets a unique, cryptographically-secure token (43 characters)
- **Variable:** `{{license_token}}` is auto-generated using `secrets.token_urlsafe(32)`
- **Future:** Will be enhanced with database tracking, expiry, and single-use validation via LicenseService

### Signed Download URLs
- **Current:** `DOWNLOAD_BASE_URL` is static
- **Future:** Each instance will get unique signed URLs for file downloads (R2 or nginx secure_link)
- **Variable:** `{{download_url}}` will be auto-generated (not yet implemented)

### Per-Instance VPN Config
- **Current:** VPN settings are static (shared server config)
- **Future:** Each instance can get unique WireGuard private keys and IPs
- **Variables:** `{{vpn_private_key}}`, `{{vpn_ip}}` (not yet implemented)

## Troubleshooting

### Variable Not Substituting

1. **Check logs:** Look for warnings about unsubstituted placeholders
2. **Verify config:** Ensure the corresponding config setting is set in `.env`
3. **Restart backend:** Settings are loaded on startup

Example error:
```
ValueError: unknown url type: '{{license_server}}/blob'
```
This means `FRONTEND_URL` is not set in `.env`, or a license product was not selected during instance creation.

### YAML Parsing Errors

If cloud-init fails with YAML errors, check:
1. Are all required variables configured?
2. Are there typos in variable names? (e.g., `{{lisence_server}}` vs `{{license_server}}`)
3. Check cloud-init logs: `/var/log/cloud-init-output.log`

## Testing Templates

Before deploying instances, you can preview template rendering via the API:

```bash
POST /api/cloud-init/templates/{id}/preview
{
  "variables": {
    "hostname": "test-instance",
    "license_server": "https://example.com/api/license",
    "license_token": "test-token-123"
  }
}
```

This returns the rendered YAML without creating an instance.
