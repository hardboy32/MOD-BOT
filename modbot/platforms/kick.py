"""Kick webhook + moderation adapter using Kick's official Public API."""
from __future__ import annotations
import asyncio, base64, json, logging, os, time
from collections import OrderedDict
from typing import Callable
import httpx
from aiohttp import web
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from .base import ChatMessage

log = logging.getLogger(__name__)
API = "https://api.kick.com/public/v1"

class KickWebhookHub:
    def __init__(self):
        self.adapters = {}
        self.runner = None
        self.lock = asyncio.Lock()
        self.public_key = None
        self.seen = OrderedDict()

    async def start(self):
        async with self.lock:
            if self.runner is not None:
                return
            app = web.Application(client_max_size=1024 * 1024)
            app.router.add_get("/health", self.health)
            app.router.add_post("/webhooks/kick", self.receive)
            self.runner = web.AppRunner(app, access_log=None)
            await self.runner.setup()
            await web.TCPSite(self.runner, "0.0.0.0", int(os.getenv("PORT", "8080"))).start()
            log.info("Kick webhook receiver started")

    async def health(self, request):
        return web.json_response({"ok": True, "service": "modbot"})

    async def verify(self, request, body):
        msg_id = request.headers.get("Kick-Event-Message-Id", "")
        timestamp = request.headers.get("Kick-Event-Message-Timestamp", "")
        signature = request.headers.get("Kick-Event-Signature", "")
        if not (msg_id and timestamp and signature):
            return False
        try:
            if self.public_key is None:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(f"{API}/public-key")
                    response.raise_for_status()
                    payload = response.json()
                pem = payload.get("data", {}).get("public_key") or payload.get("public_key")
                if not pem:
                    raise RuntimeError("Kick public key missing")
                self.public_key = serialization.load_pem_public_key(pem.encode())
            signed = f"{msg_id}.{timestamp}.{body.decode('utf-8')}".encode()
            self.public_key.verify(base64.b64decode(signature, validate=True), signed, padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception as exc:
            log.warning("Kick webhook signature rejected (%s)", type(exc).__name__)
            return False

    async def receive(self, request):
        body = await request.read()
        if not await self.verify(request, body):
            return web.Response(status=401, text="invalid signature")
        msg_id = request.headers.get("Kick-Event-Message-Id", "")
        now = time.monotonic()
        while self.seen and now - next(iter(self.seen.values())) > 3600:
            self.seen.popitem(last=False)
        if msg_id in self.seen:
            return web.Response(text="duplicate")
        self.seen[msg_id] = now
        if len(self.seen) > 10000:
            self.seen.popitem(last=False)
        if request.headers.get("Kick-Event-Type") != "chat.message.sent":
            return web.Response(text="ignored")
        try:
            data = json.loads(body)
            broadcaster_id = int(data["broadcaster"]["user_id"])
            sender = data["sender"]
            sender_id = str(sender.get("user_id") or "")
            identity = sender.get("identity") or {}
            badges = {str(b.get("type", "")).casefold() for b in identity.get("badges", []) if isinstance(b, dict)}
            is_owner = sender_id == str(broadcaster_id)
            adapter = self.adapters.get(broadcaster_id)
            content = str(data.get("content") or "")
            if adapter is None or not content:
                return web.Response(text="unmapped")
            msg = ChatMessage(
                platform="kick", username=str(sender.get("username") or "unknown"), text=content,
                is_moderator=bool({"moderator", "broadcaster"} & badges) or is_owner,
                is_broadcaster=is_owner, message_id=str(data.get("message_id") or ""),
                platform_user_id=sender_id,
            )
            await adapter.on_message(msg)
            return web.Response(text="ok")
        except Exception as exc:
            log.exception("Kick webhook handler failed (%s)", type(exc).__name__)
            return web.Response(status=500, text="processing error")

_HUB = KickWebhookHub()

class KickAdapter:
    def __init__(self, broadcaster_user_id: int, access_token: str, webhook_url: str):
        self.broadcaster_user_id = int(broadcaster_user_id)
        self.access_token = access_token.strip()
        self.webhook_url = webhook_url.strip()
        self.on_message: Callable | None = None
        if not self.access_token:
            raise RuntimeError("Kick connection requires a user OAuth access token")
        if not self.webhook_url.startswith("https://"):
            raise RuntimeError("KICK_WEBHOOK_URL must be a public HTTPS URL ending in /webhooks/kick")

    def headers(self):
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    async def request(self, method, path, **kwargs):
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, f"{API}{path}", headers=self.headers(), **kwargs)
            response.raise_for_status()
            return response

    async def run(self, on_message):
        if self.broadcaster_user_id in _HUB.adapters:
            raise RuntimeError(f"Duplicate Kick broadcaster ID {self.broadcaster_user_id}")
        self.on_message = on_message
        _HUB.adapters[self.broadcaster_user_id] = self
        await _HUB.start()
        await self.request("POST", "/events/subscriptions", json={
            "method": "webhook", "events": [{"name": "chat.message.sent", "version": 1}]
        })
        log.info("Kick chat webhook subscribed for broadcaster %s", self.broadcaster_user_id)
        await asyncio.Event().wait()

    async def delete_message(self, message):
        if message.message_id:
            await self.request("DELETE", f"/chat/{message.message_id}")

    async def moderate(self, message, duration, reason):
        if not message.platform_user_id:
            raise RuntimeError("Kick sender user ID missing")
        body = {"broadcaster_user_id": self.broadcaster_user_id,
                "user_id": int(message.platform_user_id), "reason": reason[:100]}
        if duration is not None:
            body["duration"] = max(1, min(10080, int(duration)))
        await self.request("POST", "/moderation/bans", json=body)

    async def timeout_user(self, message, seconds, reason):
        await self.moderate(message, max(1, (int(seconds) + 59) // 60), reason)

    async def ban_user(self, message, reason):
        await self.moderate(message, None, reason)

    async def warn_user(self, message, reason):
        await self.request("POST", "/chat", json={
            "type": "user", "broadcaster_user_id": self.broadcaster_user_id,
            "content": f"@{message.username} warning: {reason}"[:500],
        })
