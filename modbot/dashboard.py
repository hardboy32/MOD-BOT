"""Minimal multi-tenant account dashboard; payment and live adapters are separate stages."""
from __future__ import annotations

import html
import logging
import os

from aiohttp import web

from modbot.tenant_store import (
    EmailAlreadyExists,
    InvalidCredentials,
    TenantStore,
    TenantStoreError,
)

log = logging.getLogger(__name__)
COOKIE_NAME = "modbot_session"


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · MOD-BOT</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#10131b;color:#edf0f7;font:16px system-ui,sans-serif}}
main{{max-width:720px;margin:7vh auto;padding:24px}}.panel{{background:#1a2030;border:1px solid #30394d;border-radius:16px;padding:24px}}
h1{{margin-top:0}}p,.muted{{color:#aab4c8}}label{{display:block;margin:16px 0 6px}}input,textarea{{width:100%;padding:12px;border-radius:9px;border:1px solid #46516a;background:#0f1420;color:#fff}}
textarea{{min-height:180px;font:13px ui-monospace,monospace}}button{{margin-top:18px;padding:12px 18px;border:0;border-radius:9px;background:#7c9cff;color:#10131b;font-weight:700;cursor:pointer}}
a{{color:#9db5ff}}.error{{color:#ff9a9a}}.ok{{color:#8ce0b2}}.row{{display:flex;gap:12px;flex-wrap:wrap;align-items:center}}
</style></head><body><main><section class="panel"><h1>MOD-BOT</h1>{body}</section></main></body></html>"""


def create_dashboard_app(store: TenantStore) -> web.Application:
    app = web.Application(client_max_size=64 * 1024)

    def session(request):
        return store.get_session(request.cookies.get(COOKIE_NAME))

    def cookie(response, token: str):
        response.set_cookie(
            COOKIE_NAME, token, httponly=True, secure=not _is_local(),
            samesite="Strict", max_age=7 * 24 * 3600, path="/",
        )

    async def home(request):
        current = session(request)
        if not current:
            raise web.HTTPFound("/login")
        settings = store.get_settings(current["user_id"])
        # Never render credential values back into HTML.
        safe_json = html.escape(__import__("json").dumps(settings, ensure_ascii=False, indent=2))
        body = f"""<p>Signed in as <strong>{html.escape(current['email'])}</strong></p>
<p class="muted">Your account has its own isolated settings space. Platform credentials are encrypted at rest.</p>
<p class="muted">Account status: pending activation. Subscription billing is not connected yet.</p>
<form method="post" action="/settings">
<input type="hidden" name="csrf" value="{html.escape(current['csrf_token'])}">
<label for="settings">Account settings (JSON)</label>
<textarea id="settings" name="settings" spellcheck="false">{safe_json}</textarea>
<p class="muted">Do not put chat messages or message history here. This area is only for your connection and moderation settings.</p>
<button type="submit">Save settings</button></form>
<form method="post" action="/logout"><input type="hidden" name="csrf" value="{html.escape(current['csrf_token'])}"><button type="submit">Sign out</button></form>"""
        return web.Response(text=_page("Dashboard", body), content_type="text/html")

    async def register(request):
        if request.method == "GET":
            body = """<p>Create your MOD-BOT account.</p><p class="muted">Registration is currently a preview; paid subscriptions are not enabled.</p>
<form method="post"><label>Email</label><input name="email" type="email" required maxlength="254" autocomplete="email">
<label>Password (at least 12 characters)</label><input name="password" type="password" required minlength="12" maxlength="256" autocomplete="new-password">
<button type="submit">Create account</button></form><p><a href="/login">Already registered? Sign in</a></p>"""
            return web.Response(text=_page("Create account", body), content_type="text/html")
        if os.getenv("ALLOW_SIGNUPS", "false").casefold() != "true":
            raise web.HTTPForbidden(text="Registration is disabled")
        data = await request.post()
        try:
            user_id = store.create_user(str(data.get("email", "")), str(data.get("password", "")))
            token, _ = store.create_session(user_id)
        except (ValueError, EmailAlreadyExists) as exc:
            body = f'<p class="error">{html.escape(str(exc))}</p><p><a href="/register">Try again</a></p>'
            return web.Response(text=_page("Registration", body), status=400, content_type="text/html")
        response = web.HTTPFound("/")
        cookie(response, token)
        raise response

    async def login(request):
        if request.method == "GET":
            body = """<p>Sign in to your private dashboard.</p><form method="post"><label>Email</label>
<input name="email" type="email" required autocomplete="email"><label>Password</label>
<input name="password" type="password" required autocomplete="current-password"><button type="submit">Sign in</button></form>
<p><a href="/register">Create an account</a></p>"""
            return web.Response(text=_page("Sign in", body), content_type="text/html")
        data = await request.post()
        try:
            user_id = store.authenticate(str(data.get("email", "")), str(data.get("password", "")))
            token, _ = store.create_session(user_id)
        except InvalidCredentials:
            body = '<p class="error">Email or password is incorrect.</p><p><a href="/login">Try again</a></p>'
            return web.Response(text=_page("Sign in", body), status=401, content_type="text/html")
        response = web.HTTPFound("/")
        cookie(response, token)
        raise response

    async def save_settings(request):
        current = session(request)
        if not current:
            raise web.HTTPUnauthorized(text="Sign in required")
        data = await request.post()
        if not __import__("hmac").compare_digest(str(data.get("csrf", "")), current["csrf_token"]):
            raise web.HTTPForbidden(text="Invalid CSRF token")
        try:
            import json
            payload = json.loads(str(data.get("settings", "{}")))
            if not isinstance(payload, dict):
                raise ValueError("Settings must be a JSON object")
            if len(str(data.get("settings", ""))) > 48 * 1024:
                raise ValueError("Settings are too large")
            store.save_settings(current["user_id"], payload)
        except (ValueError, TenantStoreError) as exc:
            body = f'<p class="error">{html.escape(str(exc))}</p><p><a href="/">Back to dashboard</a></p>'
            return web.Response(text=_page("Settings", body), status=400, content_type="text/html")
        raise web.HTTPFound("/")

    async def logout(request):
        current = session(request)
        if not current:
            raise web.HTTPFound("/login")
        data = await request.post()
        if not __import__("hmac").compare_digest(str(data.get("csrf", "")), current["csrf_token"]):
            raise web.HTTPForbidden(text="Invalid CSRF token")
        store.delete_session(request.cookies.get(COOKIE_NAME))
        response = web.HTTPFound("/login")
        response.del_cookie(COOKIE_NAME, path="/")
        raise response

    async def health(request):
        return web.json_response({"ok": True, "service": "modbot"})

    app.router.add_get("/", home)
    app.router.add_get("/register", register)
    app.router.add_post("/register", register)
    app.router.add_get("/login", login)
    app.router.add_post("/login", login)
    app.router.add_post("/settings", save_settings)
    app.router.add_post("/logout", logout)
    app.router.add_get("/health", health)
    return app


def _is_local() -> bool:
    return os.getenv("APP_ENV", "production").casefold() == "development"
