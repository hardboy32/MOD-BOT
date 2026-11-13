from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from modbot.moderation import ModerationEngine
from modbot.platforms.twitch import TwitchAdapter
from modbot.platforms.youtube import YouTubeAdapter

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("modbot")


def load_connections(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Each item is an isolated platform/channel connection with its own rules."""
    configured = config.get("connections") or []
    if configured:
        return configured

    # Backward-compatible single Twitch connection using the original .env fields.
    if os.getenv("TWITCH_CHANNEL"):
        return [{
            "id": "default-twitch",
            "platform": "twitch",
            "channel": os.environ["TWITCH_CHANNEL"],
            "username_env": "TWITCH_BOT_USERNAME",
            "token_env": "TWITCH_OAUTH_TOKEN",
        }]
    return []


def env_value(name: str | None, default: str = "") -> str:
    return os.getenv(name, default) if name else default


async def run_connection(connection: dict[str, Any], base_moderation: dict[str, Any]) -> None:
    connection_id = str(connection.get("id") or f"{connection.get('platform')}-{connection.get('channel')}")
    platform = str(connection.get("platform", "")).lower()
    rules = {**base_moderation, **connection.get("moderation", {})}
    exempt = {str(x).casefold() for x in connection.get("exempt_users", [])}
    engine = ModerationEngine(rules, exempt)

    if platform == "twitch":
        adapter = TwitchAdapter(
            channel=str(connection["channel"]),
            username=env_value(connection.get("username_env", "TWITCH_BOT_USERNAME")),
            token=env_value(connection.get("token_env", "TWITCH_OAUTH_TOKEN")),
        )
    elif platform == "youtube":
        adapter = YouTubeAdapter(
            live_chat_id=str(connection["live_chat_id"]),
            access_token=env_value(connection.get("access_token_env", "YOUTUBE_ACCESS_TOKEN")),
            poll_interval=float(connection.get("poll_interval_seconds", 5)),
        )
    else:
        log.error("Connection %s uses unsupported platform %s; skipped", connection_id, platform)
        return

    async def handle(message):
        # A separate engine per connection prevents penalties leaking between channels.
        if message.is_moderator or message.is_broadcaster:
            return
        decision = engine.inspect(message.username, message.text)
        if decision.action == "allow":
            return
        log.info(
            "Moderation event connection=%s platform=%s user=%s type=%s action=%s",
            connection_id, message.platform, message.username, decision.violation, decision.action,
        )
        try:
            await adapter.delete_message(message)
            if decision.action == "timeout":
                await adapter.timeout_user(message, decision.timeout_seconds, decision.reason)
            elif decision.action == "ban":
                await adapter.ban_user(message, decision.reason)
            elif decision.action == "delete_warn":
                await adapter.warn_user(message, decision.reason)
        except Exception as exc:
            log.warning(
                "Moderation action failed connection=%s platform=%s error=%s",
                connection_id, platform, type(exc).__name__,
            )

    log.info("Starting connection %s (%s / %s)", connection_id, platform, connection.get("channel", connection.get("live_chat_id")))
    await adapter.run(handle)


async def main() -> None:
    config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8")) or {}
    connections = load_connections(config)
    if not connections:
        raise RuntimeError("No connections configured. Add one or more entries to connections.yaml.")

    # Optional separate file keeps the main rules easy to edit.
    connections_path = Path("connections.yaml")
    if connections_path.exists():
        extra = yaml.safe_load(connections_path.read_text(encoding="utf-8")) or {}
        connections = extra.get("connections", connections)

    moderation = config.get("moderation", {})
    tasks = [asyncio.create_task(run_connection(c, moderation)) for c in connections]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failures = [r for r in results if isinstance(r, BaseException)]
    if failures:
        for failure in failures:
            log.error("A connection stopped: %s", type(failure).__name__)
        raise RuntimeError(f"{len(failures)} connection(s) stopped")


if __name__ == "__main__":
    asyncio.run(main())
