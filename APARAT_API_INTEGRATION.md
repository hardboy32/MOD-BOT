# Aparat API integration checklist

The Aparat adapter is intentionally fail-closed until Aparat supplies an authorized, documented API contract. Do not implement private endpoints, browser-cookie scraping, or guessed request formats.

## What we need from Aparat

Please obtain the following from Aparat's developer/support team:

1. **API documentation and access**
   - Official API base URL and version.
   - Authentication method (OAuth/API key/bearer token), required scopes/permissions, token expiry and refresh process.
   - Whether access is approved for live-chat moderation and any account/channel eligibility requirements.

2. **Live-chat ingestion**
   - How to subscribe to or poll a channel's live chat.
   - A real sample event/payload for a new chat message.
   - Stable message ID, channel/stream ID, user ID, username, message text, timestamp, and moderator/broadcaster role fields.
   - Reconnect/resume behavior, pagination/cursors, heartbeat requirements, and rate limits.

3. **Moderation actions**
   - Official endpoints or events for deleting a message.
   - Timeout/mute support, including duration limits.
   - Ban/unban support, including required identifiers.
   - Required permissions/scopes and expected success/error responses for each action.
   - Whether warning messages can be sent by an authorized moderator account.

4. **Operational/security details**
   - Webhook signature verification instructions, if webhooks are used.
   - Rate limits, retry rules, error codes, and API version/deprecation policy.
   - A sandbox/test channel or safe test procedure.

## Adapter contract in MOD-BOT

The adapter will normalize incoming events into `modbot.platforms.base.ChatMessage` and implement the existing platform interface:

- `run(on_message)`: receive live chat messages and pass them to the in-memory moderation engine.
- `delete_message(message)`
- `timeout_user(message, seconds, reason)`
- `ban_user(message, reason)`
- `warn_user(message, reason)`

The exact API calls and payload mapping must be based on Aparat's official documentation and the access credentials they issue. If Aparat does not support one of these actions, the adapter will report that capability as unsupported rather than pretending it succeeded.

## Privacy requirements

- Message text may be processed in memory only.
- Never write message bodies, tokens, cookies, or authorization headers to logs or files.
- Store credentials in Railway Variables, not in Git.
- Keep Aparat disabled until the integration is implemented and tested against an authorized channel.

## What to send back

Send the official documentation link or PDF, the issued API credential type (never paste the secret itself), required scopes, and sanitized sample request/response payloads. Redact tokens, cookies, personal information, and private channel data.
