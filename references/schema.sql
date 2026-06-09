create table if not exists yt_channels (
 channel_id text primary key,
 channel_name text not null,
 channel_handle text,
 channel_url text not null,
 uploads_playlist_id text not null,
 niche text,
 country_code text,
 timezone_name text not null default 'Asia/Jakarta',
 is_active boolean not null default true,
 check_interval_minutes integer not null default 60,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);

create index if not exists idx_yt_channels_active on yt_channels (is_active, check_interval_minutes);

create table if not exists yt_channel_snapshots (
 id bigserial primary key,
 channel_id text not null references yt_channels(channel_id) on delete cascade,
 captured_at timestamptz not null,
 subscriber_count bigint,
 video_count bigint,
 view_count_total bigint,
 snapshot_source text not null default 'youtube_api',
 created_at timestamptz not null default now(),
 unique (channel_id, captured_at)
);

create index if not exists idx_yt_channel_snapshots_channel_time on yt_channel_snapshots (channel_id, captured_at desc);

create table if not exists yt_videos (
 video_id text primary key,
 channel_id text not null references yt_channels(channel_id) on delete cascade,
 title text not null,
 published_at timestamptz not null,
 video_url text not null,
 detected_first_at timestamptz not null default now(),
 detected_last_at timestamptz not null default now(),
 is_today_upload boolean not null default false,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);

create index if not exists idx_yt_videos_channel_published on yt_videos (channel_id, published_at desc);

create table if not exists yt_video_snapshots (
 id bigserial primary key,
 video_id text not null references yt_videos(video_id) on delete cascade,
 channel_id text not null references yt_channels(channel_id) on delete cascade,
 captured_at timestamptz not null,
 view_count bigint,
 like_count bigint,
 comment_count bigint,
 age_hours numeric(12,2),
 views_per_hour_est numeric(14,4),
 snapshot_source text not null default 'youtube_api',
 created_at timestamptz not null default now(),
 unique (video_id, captured_at)
);

create index if not exists idx_yt_video_snapshots_video_time on yt_video_snapshots (video_id, captured_at desc);
create index if not exists idx_yt_video_snapshots_channel_time on yt_video_snapshots (channel_id, captured_at desc);

create table if not exists yt_channel_daily_stats (
 stat_date date not null,
 channel_id text not null references yt_channels(channel_id) on delete cascade,
 subscriber_count_end bigint,
 subscriber_growth_abs bigint,
 subscriber_growth_pct numeric(10,4),
 upload_count_1d integer not null default 0,
 upload_count_7d integer not null default 0,
 upload_count_30d integer not null default 0,
 latest_video_id text references yt_videos(video_id) on delete set null,
 latest_video_title text,
 latest_video_views bigint,
 latest_video_vph numeric(14,4),
 latest_video_likes bigint,
 latest_video_comments bigint,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 primary key (stat_date, channel_id)
);

create index if not exists idx_yt_channel_daily_stats_channel_date on yt_channel_daily_stats (channel_id, stat_date desc);

create table if not exists yt_channel_baselines (
 channel_id text primary key references yt_channels(channel_id) on delete cascade,
 avg_sub_growth_7d numeric(14,4),
 avg_sub_growth_30d numeric(14,4),
 avg_uploads_per_7d numeric(14,4),
 median_latest_video_vph_10 numeric(14,4),
 avg_latest_video_like_rate numeric(14,4),
 avg_latest_video_comment_rate numeric(14,4),
 recalculated_at timestamptz not null default now()
);

create table if not exists yt_alerts (
 id bigserial primary key,
 channel_id text not null references yt_channels(channel_id) on delete cascade,
 video_id text references yt_videos(video_id) on delete set null,
 alert_type text not null,
 severity text not null,
 alert_key text not null,
 message text not null,
 metadata_json jsonb not null default '{}'::jsonb,
 status text not null default 'new',
 created_at timestamptz not null default now(),
 acknowledged_at timestamptz,
 unique (alert_key)
);

create index if not exists idx_yt_alerts_channel_created on yt_alerts (channel_id, created_at desc);
create index if not exists idx_yt_alerts_status_created on yt_alerts (status, created_at desc);

create table if not exists job_runs (
 id bigserial primary key,
 job_name text not null,
 job_type text not null,
 scheduled_for timestamptz not null,
 started_at timestamptz,
 finished_at timestamptz,
 status text not null default 'queued',
 worker_name text,
 payload_json jsonb not null default '{}'::jsonb,
 result_json jsonb not null default '{}'::jsonb,
 error_message text,
 retry_count integer not null default 0,
 created_at timestamptz not null default now()
);

create index if not exists idx_job_runs_status_scheduled on job_runs (status, scheduled_for);

create table if not exists channel_check_queue (
 id bigserial primary key,
 channel_id text not null references yt_channels(channel_id) on delete cascade,
 scheduled_for timestamptz not null,
 priority integer not null default 100,
 status text not null default 'queued',
 locked_at timestamptz,
 locked_by text,
 attempt_count integer not null default 0,
 last_error text,
 created_at timestamptz not null default now(),
 unique (channel_id, scheduled_for)
);

create index if not exists idx_channel_check_queue_status_schedule on channel_check_queue (status, scheduled_for, priority);

create or replace view vw_latest_video_today as
select distinct on (v.channel_id)
 v.channel_id,
 v.video_id,
 v.title,
 v.published_at,
 vs.view_count,
 vs.views_per_hour_est,
 vs.like_count,
 vs.comment_count,
 vs.captured_at
from yt_videos v
join yt_video_snapshots vs on vs.video_id = v.video_id
where (v.published_at at time zone 'Asia/Jakarta')::date = (now() at time zone 'Asia/Jakarta')::date
order by v.channel_id, v.published_at desc, vs.captured_at desc;
