# MOD-BOT

A privacy-conscious live-chat moderation worker for Railway.

## Current status

- Twitch IRC chat ingestion and moderator actions: initial adapter included.
- Platform-neutral rules: links, configured blocked words, repeated messages and message flooding.
- YouTube, Kick and Aparat: adapter interfaces are reserved; each needs its own verified authentication/API implementation before it is enabled.
- Chat message text is processed in memory and is not written to logs or a database.

## Run locally

1. Install Python 3.11 or newer.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in Twitch credentials.
4. Ensure the bot account is a moderator in the target Twitch channel.
5. `python main.py`

## Railway

Create a Worker service from this GitHub repository, use `python main.py` as the start command, and add the environment variables from `.env.example` in Railway Variables. Do not commit `.env` or real tokens.

## Safety defaults

The profanity list is intentionally empty to avoid false positives. Add words in `config.yaml` after review. Start with link deletion and flood/repeat detection; verify moderation permissions in a test channel before using timeout/ban actions in a public stream.

## Environment variables

- `TWITCH_BOT_USERNAME`
- `TWITCH_OAUTH_TOKEN` (OAuth token; prefix `oauth:` is added if omitted)
- `TWITCH_CHANNEL`
- `ENABLED_PLATFORMS` (currently `twitch`)
- `MODBOT_EXEMPT_USERS` (comma-separated usernames)
