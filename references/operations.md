# Operations Guide

## Environment

Set a local PostgreSQL URL:

```bash
export YCM_DATABASE_URL='postgresql://user:password@127.0.0.1:5432/youtube_monitor'
```

`DATABASE_URL` is accepted as fallback.

YouTube credentials are read by `youtube-data-cli`. Recommended path:

```text
~/.config/youtube-data-cli/credentials.json
```

## Setup flow

1. Confirm PostgreSQL exists and `YCM_DATABASE_URL` is set.
2. Run `init-db`.
3. Add up to 20 channels.
4. Run `poll-channel` on one test channel.
5. Run `daily-digest` to verify output.
6. Only then schedule cron jobs.

## CLI commands

- `init-db` — creates tables and view from `references/schema.sql`.
- `add-channel <url-or-id>` — resolves channel, stores uploads playlist ID.
- `list-channels` — lists active/inactive monitored channels.
- `poll-channel <channel_id>` — collects channel metadata, recent uploads, video stats, snapshots, and alerts.
- `poll-due` — queues/checks all active channels due by interval.
- `fast-track-today` — refreshes today's videos, prioritizing new videos for VPH tracking.
- `daily-digest [--date YYYY-MM-DD|today]` — upserts daily stats and prints digest JSON.
- `recalc-baselines` — computes per-channel baseline metrics.
- `cleanup [--days 30]` — removes old completed job runs/queue rows.

## Adding channels

Accepted inputs:
- `UC...` channel IDs
- YouTube channel URLs
- `@handle` handles

The resolver uses `youtube-data-cli channels` where possible and falls back to `youtube-data-cli search --type channel` for handles/searchable names.

## Alerts

Alerts are persisted in `yt_alerts`. `alert_key` uniqueness prevents repeats.

Daily digest includes alert types from that local date.

## Troubleshooting

- If DB connection fails: check `YCM_DATABASE_URL`, PostgreSQL service, and database existence.
- If YouTube quota fails: reduce channel count, polling interval, or fast-track frequency.
- If channel has hidden subscribers: `subscriber_count` may be null.
- If likes are hidden/unavailable: `like_count` may be null.
