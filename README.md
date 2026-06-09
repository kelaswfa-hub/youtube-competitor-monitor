# YouTube Competitor Monitor

A lightweight YouTube competitor monitoring skill for OpenClaw. It tracks selected YouTube channels with the YouTube Data API v3, stores historical snapshots in PostgreSQL, calculates daily competitor metrics, and produces digest-ready JSON reports.

## What it does

- Monitors up to 20 active YouTube competitor channels.
- Uses each channel's uploads playlist for reliable video discovery.
- Stores channel snapshots:
  - subscriber count
  - total video count
  - total channel views
- Stores video snapshots:
  - views
  - likes
  - comments
  - estimated views per hour (VPH)
- Detects newly uploaded videos for the current local day.
- Calculates daily channel stats and baselines.
- Generates alerts for notable changes.
- Produces machine-readable daily digest JSON for assistant summaries or notifications.

## Repository layout

```text
.
├── README.md
├── SKILL.md
├── references
│   ├── operations.md
│   └── schema.sql
└── scripts
    └── ycm.py
```

## Requirements

- Python 3.11+
- PostgreSQL
- `psycopg` Python package
- `youtube-data-cli` configured for YouTube Data API v3 access
- YouTube API credentials through one of:
  - `~/.config/youtube-data-cli/credentials.json`
  - `YOUTUBE_API_KEY`
  - OAuth environment variables supported by `youtube-data-cli`

## Environment variables

Set a PostgreSQL connection URL:

```bash
export YCM_DATABASE_URL='postgresql://user:password@127.0.0.1:5432/youtube_monitor'
```

Fallback:

```bash
export DATABASE_URL='postgresql://user:password@127.0.0.1:5432/youtube_monitor'
```

Optional settings:

```bash
export YCM_TIMEZONE='Asia/Jakarta'
export YCM_MAX_CHANNELS='20'
```

Defaults:

- Timezone: `Asia/Jakarta`
- Maximum active channels: `20`

## Setup

From the OpenClaw workspace root:

```bash
python3 skills/youtube-competitor-monitor/scripts/ycm.py init-db
```

Add a competitor channel:

```bash
python3 skills/youtube-competitor-monitor/scripts/ycm.py add-channel "https://www.youtube.com/@Example" --niche "AI"
```

Accepted channel inputs:

- `UC...` channel IDs
- YouTube channel URLs
- `@handle` handles
- Searchable channel names, when resolvable by YouTube search

List monitored channels:

```bash
python3 skills/youtube-competitor-monitor/scripts/ycm.py list-channels
```

## CLI commands

```bash
# Show help
python3 skills/youtube-competitor-monitor/scripts/ycm.py --help

# Initialize PostgreSQL schema
python3 skills/youtube-competitor-monitor/scripts/ycm.py init-db

# Add or update a monitored channel
python3 skills/youtube-competitor-monitor/scripts/ycm.py add-channel "https://www.youtube.com/@Example" --niche "AI"

# List monitored channels
python3 skills/youtube-competitor-monitor/scripts/ycm.py list-channels

# Poll one channel immediately
python3 skills/youtube-competitor-monitor/scripts/ycm.py poll-channel UCxxxxxxxxxxxxxxxxxxxxxx

# Poll all active channels that are due
python3 skills/youtube-competitor-monitor/scripts/ycm.py poll-due

# Refresh today's videos more frequently for VPH tracking
python3 skills/youtube-competitor-monitor/scripts/ycm.py fast-track-today

# Build daily stats and output digest JSON
python3 skills/youtube-competitor-monitor/scripts/ycm.py daily-digest --date today

# Recalculate per-channel baselines
python3 skills/youtube-competitor-monitor/scripts/ycm.py recalc-baselines

# Remove old completed job/queue rows
python3 skills/youtube-competitor-monitor/scripts/ycm.py cleanup --days 30
```

## Recommended workflow

1. Configure PostgreSQL and YouTube API credentials.
2. Run `init-db`.
3. Add up to 20 competitor channels.
4. Test one channel with `poll-channel`.
5. Run `poll-due` to verify the full monitoring loop.
6. Run `daily-digest --date today` to verify report output.
7. Schedule recurring jobs only after manual checks pass.

## Recommended cron schedule

The skill itself does not install cron jobs automatically. In OpenClaw, use isolated cron agent turns or your preferred scheduler.

Recommended schedule using `Asia/Jakarta` wall-clock time:

```text
*/30 * * * * fast-track-today
0 * * * * poll-due
0 7 * * * daily-digest --date today
30 7 * * * recalc-baselines
0 3 * * * cleanup --days 30
```

Notes:

- `fast-track-today` can be every 15 minutes for aggressive monitoring, or every 30 minutes to reduce API/model usage.
- `poll-due` respects each channel's configured `check_interval_minutes`.
- Digest delivery should be handled by OpenClaw, a wrapper script, or another notification layer.

## Alerts

Implemented alert types:

- `NEW_UPLOAD_TODAY`
- `HIGH_VPH`
- `SUB_GROWTH_SPIKE`
- `UPLOAD_SURGE`
- `LOW_ENGAGEMENT_WARNING`

Alerts are stored in `yt_alerts` and use stable `alert_key` values to avoid duplicates.

## Data model

The PostgreSQL schema is defined in [`references/schema.sql`](references/schema.sql).

Main tables:

- `yt_channels` — monitored channel metadata and polling settings
- `yt_channel_snapshots` — historical channel metrics
- `yt_videos` — discovered videos
- `yt_video_snapshots` — historical video metrics
- `yt_channel_daily_stats` — daily rollups
- `yt_channel_baselines` — baseline metrics for anomaly detection
- `yt_alerts` — generated alerts
- `job_runs` — local job execution history
- `channel_check_queue` — queued channel checks

Helper view:

- `vw_latest_video_today`

## Output

Most commands print JSON. The daily digest is designed to be consumed by an assistant or another reporting layer and summarized into a human-readable report.

A good user-facing digest should include:

- New uploads today
- Fastest subscriber growth, when available
- Highest VPH or latest video highlights
- Alerts requiring attention
- Any failed jobs, quota limits, or API issues

## Troubleshooting

### Database connection fails

Check:

- `YCM_DATABASE_URL` or `DATABASE_URL`
- PostgreSQL service status
- database/user permissions
- whether `init-db` has been run

### YouTube API or quota errors

Try:

- reducing channel count
- increasing polling intervals
- reducing fast-track frequency
- checking `youtube-data-cli` authentication

### Subscriber count is missing

Some channels hide subscribers. In that case `subscriber_count` may be `null`.

### Like count is missing

Some videos have unavailable or hidden like data. In that case `like_count` may be `null`.

## OpenClaw skill usage

This repository is structured as an OpenClaw AgentSkill. The main skill instructions live in [`SKILL.md`](SKILL.md), while operational details are in [`references/operations.md`](references/operations.md).

When using this as an OpenClaw skill:

1. Read `SKILL.md` first.
2. Use `scripts/ycm.py` as the deterministic CLI.
3. Read `references/operations.md` for workflow and troubleshooting.
4. Read `references/schema.sql` only when database details matter.

## Safety notes

- Do not commit real database URLs, OAuth credentials, API keys, or token files.
- Keep credentials in environment variables or local config files outside the repository.
- Do not send external notifications or create scheduled jobs unless explicitly requested.

## License

No license has been specified yet. Add one before public reuse or distribution.
