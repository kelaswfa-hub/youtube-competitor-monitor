#!/usr/bin/env python3
"""YouTube Competitor Monitor CLI.

Uses youtube-data-cli for YouTube Data API v3 and PostgreSQL for persistence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import psycopg  # type: ignore
    from psycopg.rows import dict_row  # type: ignore
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None

TZ = ZoneInfo(os.environ.get("YCM_TIMEZONE", "Asia/Jakarta"))
ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "references" / "schema.sql"
MAX_CHANNELS = int(os.environ.get("YCM_MAX_CHANNELS", "20"))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def local_date(dt: datetime | None = None):
    return (dt or now_utc()).astimezone(TZ).date()


def json_default(value: Any):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def require_psycopg():
    if psycopg is None:
        raise SystemExit(
            "Missing psycopg. Install with: python3 -m pip install psycopg[binary] "
            "or use your system package manager."
        )


def db_url() -> str:
    url = os.environ.get("YCM_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set YCM_DATABASE_URL or DATABASE_URL for PostgreSQL.")
    return url


@contextmanager
def db():
    require_psycopg()
    with psycopg.connect(db_url(), row_factory=dict_row) as conn:  # type: ignore[union-attr]
        yield conn


def run_yt(args: list[str]) -> dict[str, Any]:
    cmd = ["youtube-data-cli", *args, "--format", "compact"]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"youtube-data-cli failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from youtube-data-cli: {proc.stdout[:500]}") from exc


def parse_channel_input(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"UC[\w-]{20,}", value):
        return value
    m = re.search(r"/(channel)/(UC[\w-]{20,})", value)
    if m:
        return m.group(2)
    return value


def resolve_channel(value: str) -> dict[str, Any]:
    raw = parse_channel_input(value)
    if raw.startswith("UC"):
        data = run_yt(["channels", raw])
        items = data.get("items", [])
        if not items:
            raise RuntimeError(f"Channel not found: {value}")
        return items[0]

    query = raw
    if "youtube.com" in raw:
        handle = re.search(r"/@([^/?#]+)", raw)
        custom = re.search(r"/c/([^/?#]+)", raw)
        user = re.search(r"/user/([^/?#]+)", raw)
        query = "@" + handle.group(1) if handle else (custom or user).group(1) if (custom or user) else raw

    data = run_yt(["search", "--q", query, "--type", "channel", "--max-results", "1"])
    items = data.get("items", [])
    if not items:
        raise RuntimeError(f"Could not resolve channel: {value}")
    channel_id = items[0]["id"].get("channelId")
    if not channel_id:
        raise RuntimeError(f"Search result did not include channelId: {value}")
    channel = run_yt(["channels", channel_id]).get("items", [None])[0]
    if not channel:
        raise RuntimeError(f"Channel details not found: {channel_id}")
    return channel


def uploads_playlist_id(channel: dict[str, Any]) -> str:
    related = channel.get("contentDetails", {}).get("relatedPlaylists", {})
    uploads = related.get("uploads")
    if not uploads:
        # UC... -> UU... is YouTube's uploads playlist convention; use as fallback.
        cid = channel["id"]
        uploads = "UU" + cid[2:] if cid.startswith("UC") else ""
    if not uploads:
        raise RuntimeError("Could not determine uploads playlist ID")
    return uploads


def channel_row(channel: dict[str, Any], source_url: str, niche: str | None, country: str | None) -> dict[str, Any]:
    sn = channel.get("snippet", {})
    return {
        "channel_id": channel["id"],
        "channel_name": sn.get("title") or channel["id"],
        "channel_handle": sn.get("customUrl"),
        "channel_url": source_url if source_url.startswith("http") else f"https://www.youtube.com/channel/{channel['id']}",
        "uploads_playlist_id": uploads_playlist_id(channel),
        "niche": niche,
        "country_code": country or sn.get("country"),
    }


def init_db(_args):
    with db() as conn:
        conn.execute(SCHEMA_PATH.read_text())
    print(json.dumps({"ok": True, "schema": str(SCHEMA_PATH)}))


def add_channel(args):
    channel = resolve_channel(args.channel)
    row = channel_row(channel, args.channel, args.niche, args.country)
    with db() as conn:
        active_count = conn.execute("select count(*) as n from yt_channels where is_active").fetchone()["n"]
        exists = conn.execute("select 1 from yt_channels where channel_id=%s", (row["channel_id"],)).fetchone()
        if not exists and active_count >= MAX_CHANNELS:
            raise SystemExit(f"Maximum active channels reached ({MAX_CHANNELS}).")
        conn.execute(
            """
            insert into yt_channels (channel_id, channel_name, channel_handle, channel_url, uploads_playlist_id, niche, country_code, check_interval_minutes, updated_at)
            values (%(channel_id)s,%(channel_name)s,%(channel_handle)s,%(channel_url)s,%(uploads_playlist_id)s,%(niche)s,%(country_code)s,%(interval)s,now())
            on conflict (channel_id) do update set
              channel_name=excluded.channel_name,
              channel_handle=excluded.channel_handle,
              channel_url=excluded.channel_url,
              uploads_playlist_id=excluded.uploads_playlist_id,
              niche=coalesce(excluded.niche, yt_channels.niche),
              country_code=coalesce(excluded.country_code, yt_channels.country_code),
              check_interval_minutes=excluded.check_interval_minutes,
              updated_at=now()
            """,
            {**row, "interval": args.interval},
        )
    print(json.dumps({"ok": True, "channel": row}, ensure_ascii=False, default=json_default))


def list_channels(_args):
    with db() as conn:
        rows = conn.execute("select * from yt_channels order by is_active desc, channel_name").fetchall()
    print(json.dumps({"channels": rows}, ensure_ascii=False, default=json_default, indent=2))


def insert_job(conn, name: str, typ: str, payload: dict[str, Any]) -> int:
    row = conn.execute(
        "insert into job_runs (job_name, job_type, scheduled_for, started_at, status, payload_json) values (%s,%s,now(),now(),'running',%s::jsonb) returning id",
        (name, typ, json.dumps(payload, default=json_default)),
    ).fetchone()
    return int(row["id"])


def finish_job(conn, job_id: int, status: str, result: dict[str, Any] | None = None, error: str | None = None):
    conn.execute(
        "update job_runs set finished_at=now(), status=%s, result_json=%s::jsonb, error_message=%s where id=%s",
        (status, json.dumps(result or {}, default=json_default), error, job_id),
    )


def get_channel_from_db(conn, channel_id: str) -> dict[str, Any]:
    row = conn.execute("select * from yt_channels where channel_id=%s", (channel_id,)).fetchone()
    if not row:
        raise RuntimeError(f"Channel not monitored: {channel_id}")
    return row


def poll_channel_logic(conn, channel_id: str, recent_limit: int = 10) -> dict[str, Any]:
    ch = get_channel_from_db(conn, channel_id)
    captured_at = now_utc()

    channel_data = run_yt(["channels", channel_id])
    item = channel_data.get("items", [None])[0]
    if not item:
        raise RuntimeError(f"YouTube channel not found: {channel_id}")
    stats = item.get("statistics", {})
    sn = item.get("snippet", {})

    conn.execute(
        """
        update yt_channels set channel_name=%s, channel_handle=coalesce(%s, channel_handle), updated_at=now()
        where channel_id=%s
        """,
        (sn.get("title"), sn.get("customUrl"), channel_id),
    )
    conn.execute(
        """
        insert into yt_channel_snapshots (channel_id, captured_at, subscriber_count, video_count, view_count_total)
        values (%s,%s,%s,%s,%s) on conflict do nothing
        """,
        (channel_id, captured_at, stats.get("subscriberCount"), stats.get("videoCount"), stats.get("viewCount")),
    )

    uploads = ch["uploads_playlist_id"]
    plist = run_yt(["playlist-items", "--playlist-id", uploads, "--max-results", str(recent_limit)])
    video_ids: list[str] = []
    today = local_date(captured_at)
    new_today: list[str] = []
    for p in plist.get("items", []):
        ps = p.get("snippet", {})
        rid = ps.get("resourceId", {})
        vid = rid.get("videoId")
        if not vid:
            continue
        video_ids.append(vid)
        published = datetime.fromisoformat(ps["publishedAt"].replace("Z", "+00:00"))
        is_today = published.astimezone(TZ).date() == today
        conn.execute(
            """
            insert into yt_videos (video_id, channel_id, title, published_at, video_url, is_today_upload, detected_last_at, updated_at)
            values (%s,%s,%s,%s,%s,%s,now(),now())
            on conflict (video_id) do update set
              title=excluded.title,
              detected_last_at=now(),
              is_today_upload=excluded.is_today_upload,
              updated_at=now()
            """,
            (vid, channel_id, ps.get("title") or vid, published, f"https://www.youtube.com/watch?v={vid}", is_today),
        )
        if is_today:
            new_today.append(vid)
            alert_key = f"new_upload:{channel_id}:{vid}"
            conn.execute(
                """
                insert into yt_alerts (channel_id, video_id, alert_type, severity, alert_key, message, metadata_json)
                values (%s,%s,'NEW_UPLOAD_TODAY','info',%s,%s,%s::jsonb)
                on conflict (alert_key) do nothing
                """,
                (channel_id, vid, alert_key, f"New upload today: {ps.get('title')}", json.dumps({"title": ps.get("title")})),
            )

    if video_ids:
        videos = run_yt(["videos", ",".join(video_ids)])
        for v in videos.get("items", []):
            vid = v["id"]
            vst = v.get("statistics", {})
            published_row = conn.execute("select published_at from yt_videos where video_id=%s", (vid,)).fetchone()
            published_at = published_row["published_at"] if published_row else captured_at
            age_hours = max((captured_at - published_at).total_seconds() / 3600.0, 0.01)
            views = int(vst.get("viewCount", 0)) if vst.get("viewCount") is not None else None
            vph = (views / age_hours) if views is not None else None
            conn.execute(
                """
                insert into yt_video_snapshots (video_id, channel_id, captured_at, view_count, like_count, comment_count, age_hours, views_per_hour_est)
                values (%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing
                """,
                (vid, channel_id, captured_at, views, vst.get("likeCount"), vst.get("commentCount"), round(age_hours, 2), vph),
            )

    check_alerts(conn, channel_id, today)
    return {"channel_id": channel_id, "videos_seen": len(video_ids), "new_today": new_today}


def check_alerts(conn, channel_id: str, today):
    # HIGH_VPH: latest today's video vs baseline median.
    rows = conn.execute(
        """
        select v.video_id, v.title, vs.view_count, vs.views_per_hour_est, vs.like_count, vs.comment_count, b.median_latest_video_vph_10,
               b.avg_latest_video_like_rate, b.avg_latest_video_comment_rate
        from vw_latest_video_today v
        join yt_video_snapshots vs on vs.video_id=v.video_id and vs.captured_at=v.captured_at
        left join yt_channel_baselines b on b.channel_id=v.channel_id
        where v.channel_id=%s
        """,
        (channel_id,),
    ).fetchall()
    for r in rows:
        median = r.get("median_latest_video_vph_10")
        vph = r.get("views_per_hour_est")
        if median and vph and float(vph) > 1.8 * float(median):
            hour = now_utc().astimezone(TZ).strftime("%Y-%m-%d-%H")
            key = f"high_vph:{channel_id}:{r['video_id']}:{hour}"
            conn.execute(
                """
                insert into yt_alerts (channel_id, video_id, alert_type, severity, alert_key, message, metadata_json)
                values (%s,%s,'HIGH_VPH','warning',%s,%s,%s::jsonb) on conflict (alert_key) do nothing
                """,
                (channel_id, r["video_id"], key, f"Video VPH {vph} is above channel baseline {median}", json.dumps(dict(r), default=json_default)),
            )

    # SUB_GROWTH_SPIKE via daily snapshots.
    growth = conn.execute(
        """
        with latest as (
          select distinct on ((captured_at at time zone 'Asia/Jakarta')::date) (captured_at at time zone 'Asia/Jakarta')::date d, subscriber_count
          from yt_channel_snapshots where channel_id=%s and subscriber_count is not null
          order by (captured_at at time zone 'Asia/Jakarta')::date desc, captured_at desc
        )
        select a.subscriber_count - b.subscriber_count as growth
        from latest a left join latest b on b.d = a.d - interval '1 day'
        where a.d=%s
        """,
        (channel_id, today),
    ).fetchone()
    base = conn.execute("select avg_sub_growth_7d from yt_channel_baselines where channel_id=%s", (channel_id,)).fetchone()
    if growth and growth.get("growth") is not None and base and base.get("avg_sub_growth_7d"):
        if float(growth["growth"]) > 2 * float(base["avg_sub_growth_7d"]):
            key = f"sub_spike:{channel_id}:{today}"
            conn.execute(
                """
                insert into yt_alerts (channel_id, alert_type, severity, alert_key, message, metadata_json)
                values (%s,'SUB_GROWTH_SPIKE','warning',%s,%s,%s::jsonb) on conflict (alert_key) do nothing
                """,
                (channel_id, key, f"Subscriber growth spike: {growth['growth']}", json.dumps({"growth": growth["growth"]}, default=json_default)),
            )


def poll_channel(args):
    with db() as conn:
        job = insert_job(conn, "poll-channel", "collector", {"channel_id": args.channel_id})
        try:
            result = poll_channel_logic(conn, args.channel_id, args.recent_limit)
            finish_job(conn, job, "success", result)
        except Exception as exc:
            finish_job(conn, job, "failed", error=str(exc))
            raise
    print(json.dumps({"ok": True, "result": result}, default=json_default, ensure_ascii=False))


def poll_due(_args):
    with db() as conn:
        rows = conn.execute(
            """
            select c.channel_id from yt_channels c
            where c.is_active and not exists (
              select 1 from yt_channel_snapshots s
              where s.channel_id=c.channel_id
                and s.captured_at > now() - make_interval(mins => c.check_interval_minutes)
            )
            order by c.updated_at asc
            """
        ).fetchall()
        results = []
        for row in rows:
            try:
                results.append(poll_channel_logic(conn, row["channel_id"]))
            except Exception as exc:
                results.append({"channel_id": row["channel_id"], "error": str(exc)})
    print(json.dumps({"checked": len(results), "results": results}, ensure_ascii=False, default=json_default))


def fast_track_today(_args):
    with db() as conn:
        rows = conn.execute(
            """
            select distinct channel_id from yt_videos
            where (published_at at time zone 'Asia/Jakarta')::date = (now() at time zone 'Asia/Jakarta')::date
              and published_at > now() - interval '24 hours'
            """
        ).fetchall()
        results = []
        for r in rows:
            try:
                results.append(poll_channel_logic(conn, r["channel_id"], recent_limit=5))
            except Exception as exc:
                results.append({"channel_id": r["channel_id"], "error": str(exc)})
    print(json.dumps({"checked": len(results), "results": results}, ensure_ascii=False, default=json_default))


def recalc_baselines(_args):
    with db() as conn:
        channels = conn.execute("select channel_id from yt_channels where is_active").fetchall()
        for c in channels:
            cid = c["channel_id"]
            conn.execute(
                """
                with daily_growth as (
                  select stat_date, subscriber_growth_abs from yt_channel_daily_stats
                  where channel_id=%s and subscriber_growth_abs is not null
                ), latest_vph as (
                  select views_per_hour_est from yt_video_snapshots
                  where channel_id=%s and views_per_hour_est is not null
                  order by captured_at desc limit 10
                ), rates as (
                  select (like_count::numeric/nullif(view_count,0)) like_rate,
                         (comment_count::numeric/nullif(view_count,0)) comment_rate
                  from yt_video_snapshots where channel_id=%s and view_count > 0
                  order by captured_at desc limit 30
                )
                insert into yt_channel_baselines (
                  channel_id, avg_sub_growth_7d, avg_sub_growth_30d, avg_uploads_per_7d,
                  median_latest_video_vph_10, avg_latest_video_like_rate, avg_latest_video_comment_rate, recalculated_at
                )
                values (
                  %s,
                  (select avg(subscriber_growth_abs) from daily_growth where stat_date >= (now() at time zone 'Asia/Jakarta')::date - interval '7 days'),
                  (select avg(subscriber_growth_abs) from daily_growth where stat_date >= (now() at time zone 'Asia/Jakarta')::date - interval '30 days'),
                  (select avg(upload_count_7d) from yt_channel_daily_stats where channel_id=%s and stat_date >= (now() at time zone 'Asia/Jakarta')::date - interval '30 days'),
                  (select percentile_cont(0.5) within group (order by views_per_hour_est) from latest_vph),
                  (select avg(like_rate) from rates),
                  (select avg(comment_rate) from rates),
                  now()
                )
                on conflict (channel_id) do update set
                  avg_sub_growth_7d=excluded.avg_sub_growth_7d,
                  avg_sub_growth_30d=excluded.avg_sub_growth_30d,
                  avg_uploads_per_7d=excluded.avg_uploads_per_7d,
                  median_latest_video_vph_10=excluded.median_latest_video_vph_10,
                  avg_latest_video_like_rate=excluded.avg_latest_video_like_rate,
                  avg_latest_video_comment_rate=excluded.avg_latest_video_comment_rate,
                  recalculated_at=now()
                """,
                (cid, cid, cid, cid, cid),
            )
    print(json.dumps({"ok": True, "baselines_recalculated": len(channels)}))


def upsert_daily_stats(conn, stat_date):
    conn.execute(
        """
        insert into yt_channel_daily_stats (
          stat_date, channel_id, subscriber_count_end, subscriber_growth_abs, subscriber_growth_pct,
          upload_count_1d, upload_count_7d, upload_count_30d,
          latest_video_id, latest_video_title, latest_video_views, latest_video_vph, latest_video_likes, latest_video_comments, updated_at
        )
        with latest_snap as (
          select distinct on (channel_id) channel_id, subscriber_count
          from yt_channel_snapshots
          where (captured_at at time zone 'Asia/Jakarta')::date = %s
          order by channel_id, captured_at desc
        ), prev_snap as (
          select distinct on (channel_id) channel_id, subscriber_count
          from yt_channel_snapshots
          where (captured_at at time zone 'Asia/Jakarta')::date = %s::date - interval '1 day'
          order by channel_id, captured_at desc
        ), uploads as (
          select c.channel_id,
            count(*) filter (where v.published_at >= now() - interval '1 day') upload_count_1d,
            count(*) filter (where v.published_at >= now() - interval '7 day') upload_count_7d,
            count(*) filter (where v.published_at >= now() - interval '30 day') upload_count_30d
          from yt_channels c left join yt_videos v on v.channel_id=c.channel_id group by c.channel_id
        ), latest_video as (
          select distinct on (v.channel_id) v.channel_id, v.video_id, v.title, vs.view_count, vs.views_per_hour_est, vs.like_count, vs.comment_count
          from yt_videos v left join yt_video_snapshots vs on vs.video_id=v.video_id
          where (v.published_at at time zone 'Asia/Jakarta')::date = %s
          order by v.channel_id, v.published_at desc, vs.captured_at desc nulls last
        )
        select %s, c.channel_id, ls.subscriber_count,
          case when ps.subscriber_count is not null and ls.subscriber_count is not null then ls.subscriber_count - ps.subscriber_count else null end,
          case when ps.subscriber_count > 0 and ls.subscriber_count is not null then round(((ls.subscriber_count-ps.subscriber_count)::numeric/ps.subscriber_count)*100,4) else null end,
          coalesce(u.upload_count_1d,0), coalesce(u.upload_count_7d,0), coalesce(u.upload_count_30d,0),
          lv.video_id, lv.title, lv.view_count, lv.views_per_hour_est, lv.like_count, lv.comment_count, now()
        from yt_channels c
        left join latest_snap ls on ls.channel_id=c.channel_id
        left join prev_snap ps on ps.channel_id=c.channel_id
        left join uploads u on u.channel_id=c.channel_id
        left join latest_video lv on lv.channel_id=c.channel_id
        where c.is_active
        on conflict (stat_date, channel_id) do update set
          subscriber_count_end=excluded.subscriber_count_end,
          subscriber_growth_abs=excluded.subscriber_growth_abs,
          subscriber_growth_pct=excluded.subscriber_growth_pct,
          upload_count_1d=excluded.upload_count_1d,
          upload_count_7d=excluded.upload_count_7d,
          upload_count_30d=excluded.upload_count_30d,
          latest_video_id=excluded.latest_video_id,
          latest_video_title=excluded.latest_video_title,
          latest_video_views=excluded.latest_video_views,
          latest_video_vph=excluded.latest_video_vph,
          latest_video_likes=excluded.latest_video_likes,
          latest_video_comments=excluded.latest_video_comments,
          updated_at=now()
        """,
        (stat_date, stat_date, stat_date, stat_date),
    )


def daily_digest(args):
    stat_date = local_date() if args.date == "today" else datetime.fromisoformat(args.date).date()
    with db() as conn:
        upsert_daily_stats(conn, stat_date)
        rows = conn.execute(
            """
            select c.channel_name, d.*,
              coalesce((select jsonb_agg(alert_type order by created_at) from yt_alerts a
                where a.channel_id=d.channel_id and (a.created_at at time zone 'Asia/Jakarta')::date=d.stat_date), '[]'::jsonb) alerts
            from yt_channel_daily_stats d join yt_channels c on c.channel_id=d.channel_id
            where d.stat_date=%s order by c.channel_name
            """,
            (stat_date,),
        ).fetchall()
    channels = []
    for r in rows:
        channels.append({
            "channel_id": r["channel_id"],
            "channel_name": r["channel_name"],
            "subscriber_growth_abs": r["subscriber_growth_abs"],
            "subscriber_growth_pct": r["subscriber_growth_pct"],
            "upload_count_1d": r["upload_count_1d"],
            "upload_count_7d": r["upload_count_7d"],
            "upload_count_30d": r["upload_count_30d"],
            "latest_video_today": None if not r["latest_video_id"] else {
                "video_id": r["latest_video_id"],
                "title": r["latest_video_title"],
                "views": r["latest_video_views"],
                "views_per_hour": r["latest_video_vph"],
                "likes": r["latest_video_likes"],
                "comments": r["latest_video_comments"],
            },
            "alerts": r["alerts"],
        })
    print(json.dumps({"date": str(stat_date), "channels": channels}, ensure_ascii=False, default=json_default, indent=2))


def cleanup(args):
    with db() as conn:
        conn.execute("delete from job_runs where status in ('success','failed') and created_at < now() - make_interval(days => %s)", (args.days,))
        conn.execute("delete from channel_check_queue where status in ('done','failed') and created_at < now() - make_interval(days => %s)", (args.days,))
    print(json.dumps({"ok": True, "retention_days": args.days}))


def main():
    parser = argparse.ArgumentParser(description="YouTube competitor monitor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init-db"); p.set_defaults(func=init_db)
    p = sub.add_parser("add-channel"); p.add_argument("channel"); p.add_argument("--niche"); p.add_argument("--country"); p.add_argument("--interval", type=int, default=60); p.set_defaults(func=add_channel)
    p = sub.add_parser("list-channels"); p.set_defaults(func=list_channels)
    p = sub.add_parser("poll-channel"); p.add_argument("channel_id"); p.add_argument("--recent-limit", type=int, default=10); p.set_defaults(func=poll_channel)
    p = sub.add_parser("poll-due"); p.set_defaults(func=poll_due)
    p = sub.add_parser("fast-track-today"); p.set_defaults(func=fast_track_today)
    p = sub.add_parser("daily-digest"); p.add_argument("--date", default="today"); p.set_defaults(func=daily_digest)
    p = sub.add_parser("recalc-baselines"); p.set_defaults(func=recalc_baselines)
    p = sub.add_parser("cleanup"); p.add_argument("--days", type=int, default=30); p.set_defaults(func=cleanup)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
