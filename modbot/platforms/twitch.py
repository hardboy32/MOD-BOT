"""Twitch IRC adapter. Requires the bot account to be a channel moderator."""
from __future__ import annotations
import asyncio
import logging
import os
import re
import websockets
from .base import ChatMessage

log = logging.getLogger(__name__)
IRC_URL = "wss://irc-ws.chat.twitch.tv:443"

class TwitchAdapter:
    def __init__(self):
        self.username = os.getenv("TWITCH_BOT_USERNAME", "").strip()
        self.token = os.getenv("TWITCH_OAUTH_TOKEN", "").strip()
        self.channel = os.getenv("TWITCH_CHANNEL", "").strip().lstrip("#")
        if not all((self.username, self.token, self.channel)):
            raise RuntimeError("Set TWITCH_BOT_USERNAME, TWITCH_OAUTH_TOKEN and TWITCH_CHANNEL")
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
                    log.info("Connected to Twitch chat: #%s", self.channel)
                    async for raw in ws:
                        for line in raw.split("\r\n"):
                            if not line:
                                continue
                            if line.startswith("PING"):
                                await ws.send("PONG :tmi.twitch.tv\r\n")
                                continue
                            parsed = self._parse(line)
                            if parsed:
                                await on_message(parsed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Twitch connection interrupted (%s); retrying in 5s", type(exc).__name__)
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
        return ChatMessage("twitch", username, text, "moderator/1" in badges or "broadcaster/1" in badges, "broadcaster/1" in badges, tags.get("id"))

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
