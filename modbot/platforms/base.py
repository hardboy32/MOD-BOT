from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass
class ChatMessage:
    platform: str
    username: str
    text: str
    is_moderator: bool = False
    is_broadcaster: bool = False
    message_id: str | None = None

class PlatformAdapter(Protocol):
    async def run(self, on_message): ...
    async def delete_message(self, message: ChatMessage) -> None: ...
    async def timeout_user(self, message: ChatMessage, seconds: int, reason: str) -> None: ...
    async def ban_user(self, message: ChatMessage, reason: str) -> None: ...
