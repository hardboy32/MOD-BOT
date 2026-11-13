"""Platform-neutral moderation rules. Message bodies are never persisted or logged."""
from __future__ import annotations

import re
import time
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b[\w.-]+\.(?:com|net|org|io|gg|tv|ir|de|co|me|info|xyz)\b", re.I)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", value)
    value = re.sub(r"[^\w\s]", "", value)
    return re.sub(r"\s+", " ", value).strip()


@dataclass
class Decision:
    violation: str | None = None
    action: str = "allow"
    timeout_seconds: int = 0
    reason: str = ""


class ModerationEngine:
    def __init__(self, config: dict[str, Any], exempt_users: set[str] | None = None):
        self.config = config
        self.exempt_users = {u.casefold() for u in (exempt_users or set())}
        self.user_times: dict[str, deque[float]] = defaultdict(deque)
        self.recent: dict[str, tuple[str, float]] = {}
        self.violations: dict[str, int] = defaultdict(int)

    def inspect(self, username: str, message: str, now: float | None = None) -> Decision:
        now = now or time.monotonic()
        user = username.casefold()
        if user in self.exempt_users:
            return Decision()
        cfg = self.config
        if not cfg.get("enabled", True):
            return Decision()

        normalized = normalize(message)
        violation: str | None = None
        reason = ""

        if cfg.get("delete_links", True) and URL_RE.search(message):
            violation, reason = "link", "Links are not allowed"
        elif cfg.get("profanity_filter", True):
            words = [normalize(w) for w in cfg.get("profanity_words", []) if normalize(w)]
            blocked = [normalize(w) for w in cfg.get("blocked_words", []) if normalize(w)]
            tokens = set(normalized.split())
            if any(w in tokens for w in words + blocked):
                violation, reason = "profanity", "Blocked language"

        if not violation and cfg.get("repeat_messages", True):
            previous = self.recent.get(user)
            window = float(cfg.get("duplicate_window_seconds", 20))
            if previous and previous[0] == normalized and now - previous[1] <= window and normalized:
                violation, reason = "repeat", "Repeated message"
            self.recent[user] = (normalized, now)

        if not violation:
            rate = cfg.get("rate_limit", {})
            events = self.user_times[user]
            window = float(rate.get("window_seconds", 8))
            while events and now - events[0] > window:
                events.popleft()
            events.append(now)
            if len(events) > int(rate.get("messages", 6)):
                violation, reason = "flood", "Message flood"

        if not violation:
            return Decision()

        self.violations[user] += 1
        count = self.violations[user]
        actions = cfg.get("actions", {})
        if count >= int(actions.get("ban_threshold", 5)):
            return Decision(violation, "ban", reason=reason)
        if count >= int(actions.get("timeout_threshold", 2)):
            base = int(actions.get("timeout_seconds", 60))
            maximum = int(actions.get("max_timeout_seconds", 3600))
            duration = min(base * (2 ** (count - int(actions.get("timeout_threshold", 2)))), maximum)
            return Decision(violation, "timeout", duration, reason)
        return Decision(violation, "delete_warn", reason=reason)
