# MOD-BOT

Privacy-conscious multi-channel live-chat moderation for Railway.

## One process, many channels

A single running process manages multiple independent channel connections simultaneously. Add any number of entries to `connections.yaml`; each gets its own credentials, moderation counters and optional rule overrides. A user can connect one channel or several channels across supported platforms. Tokens are stored only in Railway Variables / local `.env`, never in Git.

## Platform status

- **Twitch:** IRC chat ingestion and moderation commands.
- **YouTube:** official YouTube Data API v3 adapter for chat ingestion, message deletion and temporary/permanent live-chat bans.
- **Kick:** official webhook + Public API adapter. Verifies signed webhooks, ingests chat messages, deletes messages, sends warnings and applies timeouts/bans.
- **Aparat:** intentionally not activated. A supported public API for reading live chat and deleting/timing out/banning users could not be verified. The service skips Aparat entries safely instead of scraping undocumented private endpoints.

## Kick configuration

1. Create a Kick Developer application.
2. Each broadcaster must authorize the app; save each user's access token as a separate Railway Variable.
3. Required scopes: `chat:read events:subscribe moderation:chat_message:manage moderation:ban chat:write`.
4. In the Kick Developer app settings, enable Webhooks and set the public URL to `https://YOUR-RAILWAY-DOMAIN/webhooks/kick`.
5. Set Railway Variable `KICK_WEBHOOK_URL` to the same URL.
6. Add one Kick connection per broadcaster in `connections.yaml`.

```yaml
connections:
  - id: kick-channel-a
    platform: kick
    broadcaster_user_id: 123456789
    access_token_env: KICK_CHANNEL_A_TOKEN
  - id: kick-channel-b
    platform: kick
    broadcaster_user_id: 987654321
    access_token_env: KICK_CHANNEL_B_TOKEN
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
