# MOD-BOT

Privacy-conscious multi-channel live-chat moderation for Railway.

## One process, many channels

A single running process manages multiple independent channel connections simultaneously. Add any number of entries to `connections.yaml`; each gets its own credentials, moderation counters and optional rule overrides. A user can connect one channel or several channels across supported platforms. Tokens are stored only in Railway Variables / local `.env`, never in Git.

## Platform status

- **Twitch:** IRC chat ingestion and moderation commands.
- **YouTube:** official YouTube Data API v3 adapter for chat ingestion, message deletion and temporary/permanent live-chat bans.
- **Kick:** official webhook + Public API adapter. Verifies signed webhooks, ingests chat messages, deletes messages, sends warnings and applies timeouts/bans.
- **Aparat:** integration scaffold and adapter safety boundary are prepared, but live-chat ingestion and moderation are **not active yet**. The official developer portal currently exposes only a generic documentation landing page; we could not verify the API contract for chat reading or delete/timeout/ban actions. Aparat remains disabled until its official API documentation and authorized access are provided. See [APARAT_API_INTEGRATION.md](APARAT_API_INTEGRATION.md) for the exact information needed. We will not invent private endpoints or claim unsupported actions work.

## Kick configuration

1. Create a Kick Developer application.
2. Each broadcaster must authorize the app; save each user's access token and refresh token as separate Railway Variables. The worker refreshes access tokens automatically using the app client credentials.
3. Required scopes: `chat:read events:subscribe moderation:chat_message:manage moderation:ban chat:write`. Keep the refresh token secret; access tokens expire and are refreshed by the adapter.
4. In the Kick Developer app settings, enable Webhooks and set the public URL to `https://YOUR-RAILWAY-DOMAIN/webhooks/kick`.
5. Set Railway Variable `KICK_WEBHOOK_URL` to the same URL.
6. Set `KICK_CLIENT_ID` and `KICK_CLIENT_SECRET` in Railway Variables, then add one Kick connection per broadcaster in `connections.yaml` with both `access_token_env` and `refresh_token_env`.

```yaml
connections:
  - id: kick-channel-a
    platform: kick
    broadcaster_user_id: 123456789
    access_token_env: KICK_CHANNEL_A_ACCESS_TOKEN
    refresh_token_env: KICK_CHANNEL_A_REFRESH_TOKEN
  - id: kick-channel-b
    platform: kick
    broadcaster_user_id: 987654321
    access_token_env: KICK_CHANNEL_B_ACCESS_TOKEN
    refresh_token_env: KICK_CHANNEL_B_REFRESH_TOKEN
```

The webhook endpoint is shared across all Kick connections and routes messages by broadcaster ID. It verifies signatures using Kick's current public key. **Kick requires a publicly reachable HTTPS webhook**, so expose the Railway service on a public domain and route its configured port to the process; a private-only Worker endpoint will not receive webhooks.

## Twitch and YouTube

Twitch requires a bot username/token and moderator permissions in every connected channel. YouTube requires a live chat ID and valid OAuth access token.

## Moderation and privacy

Link filtering, configured blocked domains/words, repeat detection and flood protection are included. First violation deletes and warns where supported; repeated violations escalate to timeout and then ban. Moderators, broadcasters and configured exempt users are ignored. Message bodies are processed in memory only and never written to logs or a database.

Review the Persian and English starter profanity list in `config.yaml` to reduce false positives.

## Railway

Start command: `python main.py`. Add all token variables referenced by `connections.yaml`. For Kick, configure the public domain and `KICK_WEBHOOK_URL` as described above.

## Official references

- Twitch: https://dev.twitch.tv/docs/chat/irc/
- YouTube Live Chat: https://developers.google.com/youtube/v3/live/docs/liveChatMessages
- Kick Public API: https://docs.kick.com/
- Kick webhook security: https://docs.kick.com/events/webhook-security
- Kick event payloads: https://docs.kick.com/events/event-types
- Aparat developer portal: https://api.aparat.com/


## Copyright and license

**Copyright (c) 2026 hardboy32. All rights reserved.**  
**Owner:** [hardboy32](https://github.com/hardboy32)  
**Email:** m629446@gmail.com  
**Contact / permission requests:** [m629446@gmail.com](mailto:m629446@gmail.com)  

This repository is public for inspection only; it is not offered under an open-source license. Copying,
modifying, redistributing, rebranding, or commercial use requires prior written
permission from the copyright holder. See [LICENSE](LICENSE) and [COPYRIGHT.md](COPYRIGHT.md).
