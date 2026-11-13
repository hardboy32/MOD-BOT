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
    value = value.replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", value)
    value = re.sub(r"[^\w\s]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def joined_letter_runs(value: str) -> set[str]:
    """Catch spaced-out evasions such as 'f u c k' without joining normal words."""
    tokens = value.split()
    runs: set[str] = set()
    current: list[str] = []
    for token in tokens + [""]:
        if len(token) == 1 and token.isalnum():
            current.append(token)
        else:
            if len(current) >= 3:
                runs.add("".join(current))
            current = []
    return runs


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
        self.last_seen: dict[str, float] = {}
        self.last_cleanup = time.monotonic()

    def _cleanup(self, now: float, max_age: float) -> None:
        if now - self.last_cleanup < 60:
            return
        cutoff = now - max(max_age, 60)
        for user in list(self.user_times):
            events = self.user_times[user]
            while events and events[0] < cutoff:
                events.popleft()
            if not events:
                self.user_times.pop(user, None)
        for user, stamp in list(self.last_seen.items()):
            if stamp < cutoff:
                self.last_seen.pop(user, None)
                self.recent.pop(user, None)
                self.violations.pop(user, None)
        self.last_cleanup = now

    def inspect(self, username: str, message: str, now: float | None = None) -> Decision:
        now = time.monotonic() if now is None else now
        user = username.casefold()
        if user in self.exempt_users or not self.config.get("enabled", True):
            return Decision()

        self.last_seen[user] = now
        cfg = self.config
        rate = cfg.get("rate_limit", {})
        duplicate_window = float(cfg.get("duplicate_window_seconds", 20))
        rate_window = float(rate.get("window_seconds", 8))
        self._cleanup(now, max(duplicate_window, rate_window) * 2)

        normalized = normalize(message)
        violation: str | None = None
        reason = ""

        if cfg.get("delete_links", True):
            url_match = URL_RE.search(message)
            blocked_domains = {str(x).casefold().lstrip(".") for x in cfg.get("blocked_domains", [])}
            if url_match:
                candidate = url_match.group(0).casefold().removeprefix("https://").removeprefix("http://").removeprefix("www.")
                domain = candidate.split("/")[0].split(":")[0]
                if not cfg.get("blocked_domains") or any(domain == d or domain.endswith("." + d) for d in blocked_domains):
                    violation, reason = "link", "Links are not allowed"

        if not violation and cfg.get("profanity_filter", True):
            words = [normalize(w) for w in cfg.get("profanity_words", []) if normalize(w)]
            blocked = [normalize(w) for w in cfg.get("blocked_words", []) if normalize(w)]
            tokens = set(normalized.split())
            spaced_evasions = joined_letter_runs(normalized)
            padded = f" {normalized} "
            if any(
                w in tokens or (len(w.split()) > 1 and f" {w} " in padded) or (len(w) >= 3 and w in spaced_evasions)
                for w in words + blocked
            ):
                violation, reason = "profanity", "Blocked language"

        if not violation and cfg.get("repeat_messages", True):
            previous = self.recent.get(user)
            if previous and previous[0] == normalized and now - previous[1] <= duplicate_window and normalized:
                violation, reason = "repeat", "Repeated message"
            self.recent[user] = (normalized, now)

        if not violation:
            events = self.user_times[user]
            while events and now - events[0] > rate_window:
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
            threshold = int(actions.get("timeout_threshold", 2))
            base = int(actions.get("timeout_seconds", 60))
            maximum = int(actions.get("max_timeout_seconds", 3600))
            duration = min(base * (2 ** (count - threshold)), maximum)
            return Decision(violation, "timeout", duration, reason)
        return Decision(violation, "delete_warn", reason=reason)
