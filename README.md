# MOD-BOT

Privacy-conscious multi-channel live-chat moderation worker for Railway.

## Multi-channel setup

One worker can manage multiple independent channels simultaneously. Add any number of connection entries to `connections.yaml`. A connection is one channel/live chat; users can connect only one platform or several platforms and channels at once.

Every connection gets its own adapter and moderation counters. Exempt users and rule overrides can be set per connection. Credentials are referenced by environment-variable names and must be stored as Railway Variables or in a local `.env` file, never committed to GitHub.

## Adapter status

- **Twitch:** multi-channel IRC adapter. The bot account must be a moderator in each channel.
- **YouTube:** official YouTube Data API v3 adapter. Supports chat ingestion, message deletion and temporary/permanent bans. Requires live chat ID and valid OAuth access token; API quota and token expiry apply.
- **Kick:** connection schema reserved; adapter is not implemented yet.
- **Aparat:** connection schema reserved; a supported public chat/moderation API has not been verified, so no live adapter is claimed.

Unsupported platform entries are safely skipped rather than falsely shown as connected.

## Configure

1. Use Python 3.11 or newer.
2. Install: `pip install -r requirements.txt`.
3. Add credentials to Railway Variables (or copy `.env.example` to `.env` locally).
4. Add one or more entries to `connections.yaml`.
5. Run `python main.py`.

Twitch example:

```yaml
connections:
  - id: twitch-one
    platform: twitch
    channel: first_channel
    username_env: TWITCH_BOT_USERNAME
    token_env: TWITCH_OAUTH_TOKEN
    exempt_users: [channel_owner, trusted_mod]

  - id: twitch-two
    platform: twitch
    channel: second_channel
    username_env: TWITCH_BOT_USERNAME
    token_env: TWITCH_OAUTH_TOKEN
```

YouTube example:

```yaml
connections:
  - id: youtube-live
    platform: youtube
    live_chat_id: YOUR_LIVE_CHAT_ID
    access_token_env: YOUTUBE_ACCESS_TOKEN
```

## Moderation

Link filtering, configured blocked domains/words, repeated-message detection and flood protection are implemented. First violation deletes and warns where supported; repeated violations escalate to timeout and then ban. Moderators, broadcasters and configured exempt users are ignored.

Message bodies are processed in memory only and are not written to logs or a database. The profanity and blocked-word lists start empty to avoid false positives; add reviewed terms in `config.yaml`. Test in a private channel before enabling automatic timeouts/bans in a public stream.

## Railway

Create a Railway **Worker** from this repository and use `python main.py` as the start command. Add all environment secrets referenced by `connections.yaml` in Railway Variables.

## Official API references

- Twitch IRC: https://dev.twitch.tv/docs/chat/irc/
- Twitch moderation: https://dev.twitch.tv/docs/chat/moderation/
- YouTube Live Chat: https://developers.google.com/youtube/v3/live/docs/liveChatMessages
- Kick developer docs: https://docs.kick.com/
