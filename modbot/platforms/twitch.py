"""Twitch IRC adapter. One adapter instance is created per channel connection."""
from __future__ import annotations

import asyncio
import logging
import re

import websockets

from .base import ChatMessage

log = logging.getLogger(__name__)
IRC_URL = "wss://irc-ws.chat.twitch.tv:443"


class TwitchAdapter:
    def __init__(self, channel: str, username: str, token: str):
        self.username = username.strip()
        self.token = token.strip()
        self.channel = channel.strip().lstrip("#")
        if not all((self.username, self.token, self.channel)):
            raise RuntimeError("Twitch connection requires channel, bot username and OAuth token")
        if not self.token.startswith("oauth:"):
            self.token = "oauth:" + self.token
        self.ws = None

    async def run(self, on_message):
        while True:
            try:
                async with websockets.connect(IRC_URL, ping_interval=30, ping_timeout=30) as ws:
                    self.ws = ws
                    await ws.send(f"PASS {self.token}\r\n")
                    await ws.send(f"NICK {self.username}\r\n")
                    await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
                    await ws.send(f"JOIN #{self.channel}\r\n")
                    log.info("Connected to Twitch channel #%s", self.channel)
                    async for raw in ws:
                        for line in raw.split("\r\n"):
                            if not line:
                                continue
                            if line.startswith("PING"):
                                await ws.send("PONG :tmi.twitch.tv\r\n")
                                continue
                            if line.startswith(":tmi.twitch.tv RECONNECT"):
                                raise ConnectionError("Twitch requested reconnect")
                            parsed = self._parse(line)
                            if parsed:
                                await on_message(parsed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Twitch #%s interrupted (%s); retrying in 5s", self.channel, type(exc).__name__)
                self.ws = None
                await asyncio.sleep(5)

    @staticmethod
    def _parse(line: str) -> ChatMessage | None:
        if " PRIVMSG #" not in line or " :" not in line:
            return None
        tags = {}
        if line.startswith("@"):
            tagpart, line = line.split(" ", 1)
            tags = dict(item.split("=", 1) if "=" in item else (item, "") for item in tagpart[1:].split(";"))
        match = re.match(r":([^!]+)!.* PRIVMSG #([^ ]+) :(.*)$", line)
        if not match:
            return None
        username, _, text = match.groups()
        badges = tags.get("badges", "")
        is_broadcaster = "broadcaster/1" in badges
        return ChatMessage(
            platform="twitch",
            username=username,
            text=text,
            is_moderator="moderator/1" in badges or "vip/1" in badges or is_broadcaster,
            is_broadcaster=is_broadcaster,
            message_id=tags.get("id"),
        )

    async def _send(self, command: str):
        if self.ws is not None:
            await self.ws.send(f"PRIVMSG #{self.channel} :{command}\r\n")

    async def delete_message(self, message: ChatMessage):
        if message.message_id:
            await self._send(f"/delete {message.message_id}")

    async def timeout_user(self, message: ChatMessage, seconds: int, reason: str):
        await self._send(f"/timeout {message.username} {seconds} {reason[:180]}")

    async def ban_user(self, message: ChatMessage, reason: str):
        await self._send(f"/ban {message.username} {reason[:180]}")

    async def warn_user(self, message: ChatMessage, reason: str):
        await self._send(f"@{message.username} warning: {reason[:150]}")
