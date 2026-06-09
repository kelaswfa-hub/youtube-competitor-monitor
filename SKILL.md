---
name: youtube-competitor-monitor
description: Monitor competitor YouTube channels using YouTube Data API v3 and local PostgreSQL. Use when the user wants to add/list/check competitor channels, collect channel/video snapshots, calculate subscriber growth/upload frequency/views-per-hour, generate alerts, daily digests, or operate the YouTube competitor monitoring workflow.
---

# YouTube Competitor Monitor

Use this skill to monitor up to 20 competitor YouTube channels with YouTube Data API v3 and PostgreSQL.

## What this skill does

- Stores channel/video history in local PostgreSQL.
- Uses YouTube Data API v3 as primary source.
- Uses each channel's uploads playlist for video discovery.
- Captures channel snapshots: subscriber count, total videos, total views.
- Captures video snapshots: views, likes, comments, age hours, estimated VPH.
- Calculates daily stats, baselines, and alerts.
- Produces JSON daily digests and instant-alert records.

## When using this skill

1. Read `references/operations.md` for commands and workflow.
2. For schema details, read `references/schema.sql` only when DB/migration/query details matter.
3. Use `scripts/ycm.py` as the deterministic CLI.
4. Never send external notifications or create cron schedules without user confirmation.

## Prerequisites

- `youtube-data-cli` installed and configured, or YouTube OAuth/API credentials available.
- PostgreSQL connection via `YCM_DATABASE_URL` or `DATABASE_URL`.
- Timezone defaults to `Asia/Jakarta`.

Credential resolution for YouTube follows `youtube-data-cli`:
- `~/.config/youtube-data-cli/credentials.json`, or
- `YOUTUBE_API_KEY`, or
- OAuth env vars.

## Common commands

```bash
# Show help
python3 skills/youtube-competitor-monitor/scripts/ycm.py --help

# Initialize PostgreSQL schema
python3 skills/youtube-competitor-monitor/scripts/ycm.py init-db

# Add a competitor channel by URL, handle, or channel ID
python3 skills/youtube-competitor-monitor/scripts/ycm.py add-channel "https://www.youtube.com/@Example" --niche "AI"

# List monitored channels
python3 skills/youtube-competitor-monitor/scripts/ycm.py list-channels

# Poll one channel now
python3 skills/youtube-competitor-monitor/scripts/ycm.py poll-channel UCxxxxxxxxxxxxxxxxxxxxxx

# Poll all active due channels now
python3 skills/youtube-competitor-monitor/scripts/ycm.py poll-due

# Poll today's videos more frequently
python3 skills/youtube-competitor-monitor/scripts/ycm.py fast-track-today

# Build daily stats and output digest JSON
python3 skills/youtube-competitor-monitor/scripts/ycm.py daily-digest --date today

# Recalculate baselines
python3 skills/youtube-competitor-monitor/scripts/ycm.py recalc-baselines
```

## Recommended cron schedule

Do not install automatically unless the user asks. Recommended schedules:

```text
*/15 * * * * fast-track-today
0 * * * * poll-due
10 20 * * * daily-digest
30 20 * * * recalc-baselines
0 3 * * * cleanup
```

When scheduling through OpenClaw cron, prefer isolated agentTurn jobs that run the relevant CLI command and announce digest/alerts.

## Alerts implemented

- `NEW_UPLOAD_TODAY`
- `HIGH_VPH`
- `SUB_GROWTH_SPIKE`
- `UPLOAD_SURGE`
- `LOW_ENGAGEMENT_WARNING`

Alerts use stable `alert_key` values to avoid duplicates.

## Output style

For user-facing replies, keep summaries concise:

- New uploads today
- Fastest subscriber growth
- Highest VPH videos
- Alerts requiring attention
- Any failed jobs or quota/API issues

## Important constraints

- Maximum active channels: 20.
- Use uploads playlist, not generic search, for channel uploads.
- Store raw snapshots before computing metrics.
- Interpret “today” in `Asia/Jakarta`.
- Browser/scraping is fallback only, not the primary collector.
