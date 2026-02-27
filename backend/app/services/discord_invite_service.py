"""Discord invite link generation service.

Generates unique, single-use Discord invite links via the Discord API
for confirmed event participants.
"""
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordInviteService:
    """Service for generating and checking Discord invite links."""

    def __init__(self):
        self.settings = get_settings()
        self.bot_token = self.settings.DISCORD_BOT_TOKEN

    async def generate_invite(self, channel_id: str) -> Optional[str]:
        """
        Generate a unique, single-use Discord invite for a channel.

        Args:
            channel_id: The Discord channel ID to create the invite for.

        Returns:
            The invite code (e.g. "abc123") or None on failure.
            The full URL is https://discord.gg/{code}
        """
        if not self.bot_token:
            logger.warning("Discord bot token not configured, skipping invite generation")
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{DISCORD_API_BASE}/channels/{channel_id}/invites",
                    headers={
                        "Authorization": f"Bot {self.bot_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "max_uses": 1,
                        "unique": True,
                        "max_age": 0  # Never expires
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    code = data.get("code")
                    logger.info(f"Generated Discord invite: {code}")
                    return code
                else:
                    logger.error(
                        f"Failed to generate Discord invite: "
                        f"{response.status_code} {response.text}"
                    )
                    return None

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(f"Discord API unavailable: {e}")
            return None
        except Exception as e:
            logger.error(f"Error generating Discord invite: {e}")
            return None

    async def check_invite_used(self, invite_code: str) -> Optional[bool]:
        """
        Check if a Discord invite has been used (consumed its max_uses).

        Args:
            invite_code: The invite code to check.

        Returns:
            True if the invite has been used/consumed.
            False if the invite is still valid.
            None if the check failed (API error).
        """
        if not self.bot_token:
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{DISCORD_API_BASE}/invites/{invite_code}?with_counts=true",
                    headers={"Authorization": f"Bot {self.bot_token}"}
                )

                if response.status_code == 404:
                    # Invite not found — consumed and auto-deleted by Discord
                    return True

                if response.status_code == 200:
                    data = response.json()
                    uses = data.get("uses", 0)
                    max_uses = data.get("max_uses", 0)
                    if max_uses > 0 and uses >= max_uses:
                        return True
                    return False

                logger.warning(
                    f"Unexpected Discord API response checking invite {invite_code}: "
                    f"{response.status_code}"
                )
                return None

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(f"Discord API unavailable for invite check: {e}")
            return None
        except Exception as e:
            logger.error(f"Error checking Discord invite: {e}")
            return None
