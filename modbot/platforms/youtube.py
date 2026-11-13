"""YouTube Live Chat adapter using the official YouTube Data API v3."""
from __future__ import annotations

import asyncio
import logging

import httpx

from .base import ChatMessage

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/youtube/v3"


class YouTubeAdapter:
    def __init__(self, live_chat_id: str, access_token: str, poll_interval: float = 5):
        self.live_chat_id = live_chat_id.strip()
        self.access_token = access_token.strip()
        self.poll_interval = max(2.0, poll_interval)
        if not self.live_chat_id or not self.access_token:
            raise RuntimeError("YouTube connection requires live_chat_id and an OAuth access token")

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}

    async def run(self, on_message):
        page_token = None
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {"liveChatId": self.live_chat_id, "part": "snippet,authorDetails", "maxResults": 200}
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(f"{API}/liveChat/messages", params=params, headers=self._headers())
                response.raise_for_status()
                data = response.json()
                page_token = data.get("nextPageToken", page_token)
                self.poll_interval = max(2.0, float(data.get("pollingIntervalMillis", self.poll_interval * 1000)) / 1000)
                for item in data.get("items", []):
                    snippet = item.get("snippet", {})
                    author = item.get("authorDetails", {})
                    if snippet.get("type") != "textMessageEvent":
                        continue
                    text = snippet.get("textMessageDetails", {}).get("messageText", "")
                    if not text:
                        continue
                    await on_message(ChatMessage(
                        platform="youtube",
                        username=author.get("displayName", "unknown"),
                        text=text,
                        is_moderator=bool(author.get("isChatModerator")),
                        is_broadcaster=bool(author.get("isChatOwner")),
                        message_id=item.get("id"),
                        platform_user_id=snippet.get("authorChannelId"),
                    ))
                await asyncio.sleep(self.poll_interval)

    async def delete_message(self, message: ChatMessage):
        if not message.message_id:
            return
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.delete(
                f"{API}/liveChat/messages", params={"id": message.message_id}, headers=self._headers()
            )
            response.raise_for_status()

    async def _ban(self, message: ChatMessage, permanent: bool, seconds: int = 0):
        if not message.platform_user_id:
            raise RuntimeError("YouTube author channel ID is missing; cannot moderate this user")
        snippet = {
            "liveChatId": self.live_chat_id,
            "type": "permanent" if permanent else "temporary",
            "bannedUserDetails": {"channelId": message.platform_user_id},
        }
        if not permanent:
            snippet["banDurationSeconds"] = max(1, int(seconds))
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{API}/liveChat/bans",
                params={"part": "snippet"},
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"snippet": snippet},
            )
            response.raise_for_status()

    async def timeout_user(self, message: ChatMessage, seconds: int, reason: str):
        await self._ban(message, permanent=False, seconds=seconds)

    async def ban_user(self, message: ChatMessage, reason: str):
        await self._ban(message, permanent=True)

    async def warn_user(self, message: ChatMessage, reason: str):
        # YouTube Live Chat API has no private warning action; send a short public notice.
        body = {
            "snippet": {
                "liveChatId": self.live_chat_id,
                "type": "textMessageEvent",
                "textMessageDetails": {"messageText": f"@{message.username} warning: {reason}"},
            }
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{API}/liveChat/messages",
                params={"part": "snippet"},
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
