from __future__ import annotations
import asyncio
import logging
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv
from modbot.moderation import ModerationEngine
from modbot.platforms.twitch import TwitchAdapter

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("modbot")

async def main():
    config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    mod_cfg = config.get("moderation", {})
    exempt = {x.strip() for x in os.getenv("MODBOT_EXEMPT_USERS", "").split(",") if x.strip()}
    engine = ModerationEngine(mod_cfg, exempt)
    enabled = {x.strip().lower() for x in os.getenv("ENABLED_PLATFORMS", "twitch").split(",") if x.strip()}
    tasks = []

    async def handle(message):
        if message.is_moderator or message.is_broadcaster:
            return
        decision = engine.inspect(message.username, message.text)
        if decision.action == "allow":
            return
        log.info("Moderation event platform=%s user=%s type=%s action=%s", message.platform, message.username, decision.violation, decision.action)
        adapter = adapters.get(message.platform)
        if not adapter:
            return
        try:
            await adapter.delete_message(message)
            if decision.action == "timeout":
                await adapter.timeout_user(message, decision.timeout_seconds, decision.reason)
            elif decision.action == "ban":
                await adapter.ban_user(message, decision.reason)
            elif decision.action == "delete_warn":
                # Warning notices can be added later; avoid noisy public bot messages by default.
                pass
        except Exception as exc:
            log.warning("Moderation action failed platform=%s error=%s", message.platform, type(exc).__name__)

    adapters = {}
    if "twitch" in enabled and config.get("platforms", {}).get("twitch", {}).get("enabled", True):
        adapters["twitch"] = TwitchAdapter()
        tasks.append(asyncio.create_task(adapters["twitch"].run(handle)))
    for platform in ("youtube", "kick", "aparat"):
        if platform in enabled or config.get("platforms", {}).get(platform, {}).get("enabled", False):
            log.warning("%s adapter is not configured yet; no connection will be attempted", platform)
    if not tasks:
        raise RuntimeError("No configured platform. Enable Twitch and provide its credentials.")
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
