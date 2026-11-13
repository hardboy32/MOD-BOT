from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from aiohttp import web
from dotenv import load_dotenv

from modbot.moderation import ModerationEngine
from modbot.platforms.twitch import TwitchAdapter
from modbot.platforms.youtube import YouTubeAdapter
from modbot.platforms.kick import KickAdapter, register_kick_routes

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("modbot")


def load_connections(config: dict[str, Any]) -> list[dict[str, Any]]:
    configured = config.get("connections") or []
    if configured:
        return configured
    if os.getenv("TWITCH_CHANNEL"):
        return [{"id": "default-twitch", "platform": "twitch",
                 "channel": os.environ["TWITCH_CHANNEL"],
                 "username_env": "TWITCH_BOT_USERNAME", "token_env": "TWITCH_OAUTH_TOKEN"}]
    return []


def env_value(name: str | None, default: str = "") -> str:
    return os.getenv(name, default) if name else default


async def run_connection(connection: dict[str, Any], base_moderation: dict[str, Any]) -> None:
    connection_id = str(connection.get("id") or f"{connection.get('platform')}-{connection.get('channel')}")
    platform = str(connection.get("platform", "")).lower()
    rules = {**base_moderation, **connection.get("moderation", {})}
    exempt = {str(x).casefold() for x in connection.get("exempt_users", [])}
    exempt.update(x.strip().casefold() for x in os.getenv("MODBOT_EXEMPT_USERS", "").split(",") if x.strip())
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
    elif platform == "kick":
        adapter = KickAdapter(
            broadcaster_user_id=int(connection["broadcaster_user_id"]),
            access_token=env_value(connection.get("access_token_env", "")),
            refresh_token=env_value(connection.get("refresh_token_env", "")),
            webhook_url=env_value("KICK_WEBHOOK_URL"),
        )
    elif platform == "aparat":
        log.error("Aparat connection %s skipped: no verified public live-chat moderation API", connection_id)
        return
    else:
        log.error("Connection %s uses unsupported platform %s; skipped", connection_id, platform)
        return

    async def handle(message):
        if message.is_moderator or message.is_broadcaster:
            return
        decision = engine.inspect(message.username, message.text)
        if decision.action == "allow":
            return
        log.info("Moderation event connection=%s platform=%s user=%s type=%s action=%s",
                 connection_id, message.platform, message.username, decision.violation, decision.action)
        try:
            await adapter.delete_message(message)
            if decision.action == "timeout":
                await adapter.timeout_user(message, decision.timeout_seconds, decision.reason)
            elif decision.action == "ban":
                await adapter.ban_user(message, decision.reason)
            elif decision.action == "delete_warn":
                await adapter.warn_user(message, decision.reason)
        except Exception as exc:
            log.warning("Moderation action failed connection=%s platform=%s error=%s",
                        connection_id, platform, type(exc).__name__)

    log.info("Starting connection %s (%s)", connection_id, platform)
    await adapter.run(handle)


async def start_dashboard():
    from modbot.dashboard import create_dashboard_app
    from modbot.tenant_store import TenantStore

    store = TenantStore()
    app = create_dashboard_app(store)
    register_kick_routes(app)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8080")))
    await site.start()
    log.info("MOD-BOT dashboard and webhook server started")
    return runner


async def main() -> None:
    dashboard_enabled = os.getenv("DASHBOARD_ENABLED", "false").casefold() == "true"
    if dashboard_enabled:
        await start_dashboard()

    config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8")) or {}
    connections_path = Path("connections.yaml")
    connections = []
    if connections_path.exists():
        extra = yaml.safe_load(connections_path.read_text(encoding="utf-8")) or {}
        connections = extra.get("connections") or []
    if not connections:
        connections = load_connections(config)

    if not connections:
        if dashboard_enabled:
            log.info("Dashboard-only mode: no platform connections are configured yet")
            await asyncio.Event().wait()
        raise RuntimeError("No connections configured. Add one or more entries to connections.yaml.")

    moderation = config.get("moderation", {})
    results = await asyncio.gather(
        *(run_connection(c, moderation) for c in connections), return_exceptions=True
    )
    failures = [result for result in results if isinstance(result, BaseException)]
    for failure in failures:
        log.error("A connection stopped: %s", type(failure).__name__)
    if failures:
        raise RuntimeError(f"{len(failures)} connection(s) stopped")


if __name__ == "__main__":
    asyncio.run(main())
