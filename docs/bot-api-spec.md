# CyberX Event Management — Bot API Specification

Base URL: `https://<platform-host>`

## Authentication

All endpoints require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <api_key>
```

API keys are created in the admin UI under **Settings > Service API Keys**. Each key has scopes that control which endpoints it can access. Keys are SHA-256 hashed in the database — the plaintext is shown once at creation.

Keys use the format `cxk_<random>` (e.g., `cxk_Ab3xQ7...`).

---

## Endpoints

### POST /api/bot/verify

**Scope required:** `bot.verify`

Link a Discord user to a platform user using their unique invite code. Participants find their invite code in the portal UI as a copyable `!verify <code>` command, which they paste in the `#verify` channel.

#### Request

```json
{
    "invite_code": "abc123xyz",
    "discord_id": "123456789012345678",
    "discord_username": "user#1234"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `invite_code` | string | yes | The participant's unique Discord invite code (from their portal) |
| `discord_id` | string | yes | Discord user snowflake ID |
| `discord_username` | string | no | Discord username (stored for display purposes) |

#### Response `200 OK`

```json
{
    "linked": true,
    "user_email": "participant@example.com",
    "user_name": "John Doe",
    "message": "Discord account linked successfully"
}
```

#### Errors

| Status | Detail | Cause |
|---|---|---|
| `404` | `"Invalid invite code"` | No participation record matches the invite code |
| `404` | `"User not found"` | Participation exists but user record is missing (data integrity issue) |
| `409` | `"This account is already linked to a different Discord user"` | The platform user is already linked to a different Discord snowflake ID |
| `410` | `"This invite code has already been used"` | The invite code is one-time use and has already been consumed |

#### Notes

- **Invite codes are one-time use.** Once verified, the code is marked as used and cannot be reused.
- The invite code comes from `EventParticipation.discord_invite_code` — it is per-event, per-user.
- The `discord_username` field is optional but recommended for admin display purposes.

---

### GET /api/bot/user/{discord_id}

**Scope required:** `bot.lookup`

Look up a platform user by their Discord snowflake ID. Returns their profile, dynamic role, and current event participation status. This is the primary endpoint for auto-role assignment.

#### Path Parameters

| Parameter | Type | Description |
|---|---|---|
| `discord_id` | string | Discord user snowflake ID (e.g., `"123456789012345678"`) |

#### Response `200 OK`

```json
{
    "user_id": 42,
    "email": "participant@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "discord_id": "123456789012345678",
    "discord_username": "johndoe",
    "role": {
        "base_type": "sponsor",
        "role_name": "Event Staff",
        "role_slug": "event-staff"
    },
    "participation": {
        "event_name": "CyberX 2026",
        "event_year": 2026,
        "status": "confirmed"
    }
}
```

#### Response Fields

| Field | Type | Description |
|---|---|---|
| `user_id` | int | Platform user ID |
| `email` | string | User's email address |
| `first_name` | string | First name |
| `last_name` | string | Last name |
| `discord_id` | string \| null | Discord snowflake ID |
| `discord_username` | string \| null | Discord username |
| `role` | object | Role information (see below) |
| `participation` | object \| null | Current event participation (null if no active event) |

**`role` object:**

| Field | Type | Description |
|---|---|---|
| `base_type` | string | Base access tier: `"admin"`, `"sponsor"`, or `"invitee"` |
| `role_name` | string \| null | Dynamic role display name (e.g., `"Event Staff"`, `"Red Team Lead"`) |
| `role_slug` | string \| null | Dynamic role slug (e.g., `"event-staff"`, `"red-team-lead"`) |

**`participation` object:**

| Field | Type | Description |
|---|---|---|
| `event_name` | string | Active event name |
| `event_year` | int | Active event year |
| `status` | string \| null | Participation status (see values below), null if user has no participation record for this event |

**Participation status values:**

| Value | Meaning |
|---|---|
| `"invited"` | Invitation sent, awaiting response |
| `"confirmed"` | User confirmed attendance |
| `"declined"` | User declined |
| `"no_response"` | No response received |
| `null` | User exists but has no participation record for the active event |

#### Errors

| Status | Detail | Cause |
|---|---|---|
| `404` | `"No linked user found for this Discord ID"` | No user has this Discord ID linked (user may need to `/verify` first) |

---

### PATCH /api/bot/user/{discord_id}

**Scope required:** `bot.update`

Update a platform user's Discord-related fields. Useful for keeping Discord usernames in sync when users change their display name.

#### Path Parameters

| Parameter | Type | Description |
|---|---|---|
| `discord_id` | string | Discord user snowflake ID (e.g., `"123456789012345678"`) |

#### Request

```json
{
    "discord_username": "new_username"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `discord_username` | string | no | Updated Discord username |

All fields are optional — only provided fields are updated.

#### Response `200 OK`

```json
{
    "updated": true,
    "user_id": 42,
    "message": "User updated successfully"
}
```

#### Errors

| Status | Detail | Cause |
|---|---|---|
| `404` | `"No linked user found for this Discord ID"` | No user has this Discord ID linked |

---

### POST /api/bot/admin-link

**Scope required:** `bot.admin_link`

Admin override to link a Discord user to a platform user, bypassing the invite code flow. Looks up the user by email or user ID and directly sets their Discord identity. Overwrites any existing Discord link on the user.

#### Request

```json
{
    "email": "participant@example.com",
    "discord_id": "123456789012345678",
    "discord_username": "user"
}
```

Either `email` or `user_id` must be provided (not both required):

| Field | Type | Required | Description |
|---|---|---|---|
| `email` | string | one of email/user_id | Platform user's email address |
| `user_id` | int | one of email/user_id | Platform user's ID |
| `discord_id` | string | yes | Discord user snowflake ID |
| `discord_username` | string | no | Discord username (for display) |

#### Response `200 OK`

```json
{
    "linked": true,
    "user_id": 42,
    "user_email": "participant@example.com",
    "user_name": "John Doe",
    "message": "Discord account linked successfully (admin override)"
}
```

#### Errors

| Status | Detail | Cause |
|---|---|---|
| `400` | `"Either 'email' or 'user_id' is required"` | Neither identifier was provided |
| `404` | `"User not found"` | No user matches the email or user_id |

#### Notes

- This endpoint **overwrites** any existing Discord link on the user, unlike `/verify` which rejects conflicts.
- Does **not** consume or require an invite code.
- Intended for admin/staff use when a participant can't complete the normal `!verify` flow.

---

## Archive lifecycle endpoints

These power cleanup after an event is archived. They are polled/called by the bot, never by users.

### GET /api/bot/invites/pending-revocation

**Scope required:** `bot.manage_invites`

Returns unused Discord invites on **archived** events (`discord_invite_code IS NOT NULL AND discord_verified_at IS NULL`) that the bot should revoke via Discord's `DELETE /invites/{code}`. Used invites are nulled by the platform on archive and never appear here.

#### Response `200 OK`

```json
[
  {
    "event_id": 2,
    "event_year": 2026,
    "participation_id": 1234,
    "invite_code": "abCdEf",
    "generated_at": "2026-05-01T12:00:00Z"
  }
]
```

### POST /api/bot/invites/{invite_code}/revoked

**Scope required:** `bot.manage_invites`

Bot callback after it has revoked the invite on Discord (or confirmed a 404). The platform nulls `EventParticipation.discord_invite_code` and writes a `DISCORD_INVITE_REVOKED` audit row. Returns `404` if no participation holds that code.

---

### GET /api/bot/verified-roster

**Scope required:** `bot.manage_roles`

Returns the snowflake IDs that **should** currently hold the verified Discord role: users linked to Discord who have verified (`discord_verified_at`) for the currently **active** event. The bot reconciles the verified role against this set — removing it from anyone holding it who isn't listed (and optionally adding it to listed members who lack it).

#### Response `200 OK`

```json
{
  "active_event": { "id": 3, "year": 2027, "name": "CyberX 2027" },
  "verified_discord_ids": ["111111111111111111", "222222222222222222"],
  "count": 2
}
```

#### Notes

- **Between seasons** (no active event), `active_event` is `null` and `verified_discord_ids` is `[]`. The bot treats this as a legitimate signal to clear the verified role for everyone — this is how roles are torn down after an archive once the old event is no longer active.
- A **non-200** response must **not** be treated as an empty roster. The bot skips reconciliation on any error so a transient outage can't strip every verified member.
- **Cloudflare safety:** the bot throttles role edits and caps changes per cycle, spreading a large end-of-season sweep across cycles to stay under Discord's edge rate limit (error 1015). Reconciliation is eventually-consistent, not real-time.
- Returning participants keep the role automatically: once they re-verify for the new active event they appear on the roster, so they're never stripped.

---

## Auto-Role Mapping Example

The bot can use the lookup response to assign Discord roles:

```python
user = await api.lookup_user(discord_id)

roles_to_assign = []

# Base type roles
if user["role"]["base_type"] == "admin":
    roles_to_assign.append("Staff")
elif user["role"]["base_type"] == "sponsor":
    roles_to_assign.append("Sponsor")

# Dynamic role (more specific)
if user["role"]["role_slug"]:
    role_map = {
        "red-team-lead": "Red Team",
        "blue-team-lead": "Blue Team",
        "event-staff": "Staff",
        # ... add mappings as needed
    }
    mapped = role_map.get(user["role"]["role_slug"])
    if mapped:
        roles_to_assign.append(mapped)

# Participation status
if user["participation"]:
    if user["participation"]["status"] == "confirmed":
        roles_to_assign.append("Confirmed Participant")
    elif user["participation"]["status"] == "declined":
        roles_to_assign.append("Declined")
```

---

## Common Error Responses

All errors return JSON with a `detail` field:

```json
{
    "detail": "Error message here"
}
```

| Status | Cause |
|---|---|
| `401` | Missing/invalid `Authorization` header or expired API key |
| `403` | API key does not have the required scope |
| `404` | Resource not found |
| `409` | Conflict (e.g., account already linked to different Discord user) |
| `503` | Bot API not configured (no API keys exist and `BOT_API_KEY` env var not set) |
