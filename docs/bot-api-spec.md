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

Link a Discord user to a platform user using their unique invite code. Participants find their invite code in the portal UI as a copyable `/verify <code>` command.

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

#### Notes

- Calling verify with the same `discord_id` that's already linked is idempotent (returns success).
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
