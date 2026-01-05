"""
TeemUp-n8n Service.

Fetches Meetup events and serves them as JSON for consumption by n8n or other tools.
"""

import os
import re
import urllib.request
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import yaml  # pip install pyyaml
from fastapi import FastAPI, HTTPException
from teemup import parse as teemup_parse


app = FastAPI()

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config.yaml")
RELOAD_CONFIG_EACH_REQUEST = os.environ.get("RELOAD_CONFIG_EACH_REQUEST", "false").lower() == "true"


def load_config() -> Dict[str, Any]:
    """Load and return configuration."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError as exc:
        raise RuntimeError(f"Config file not found: {CONFIG_PATH}") from exc
    except Exception as e:
        raise RuntimeError(f"Failed to load config {CONFIG_PATH}: {e!r}") from e

    # Normalize/validate expected keys
    cfg.setdefault("default_tz", "America/Los_Angeles")
    cfg.setdefault("meetup_groups", {})
    return cfg


# load once at startup by default
CONFIG: Dict[str, Any] = load_config()


def _get_config() -> Dict[str, Any]:
    global CONFIG
    if RELOAD_CONFIG_EACH_REQUEST:
        CONFIG = load_config()
    return CONFIG


def _pick_event_cfg(title: str, cfg: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    title_lc = (title or "").lower()
    chosen = cfg.get("default", {}) or {}
    for key in cfg.keys():
        if key == "default":
            continue
        if key.lower() in title_lc:
            chosen = cfg[key]
            break
    return chosen


def _ensure_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


def _format_time_disp(dt_local: datetime) -> str:
    return dt_local.strftime("%A, %B %d, %Y at %I:%M %p")


def _format_time_local_hm(dt_local: datetime) -> str:
    return dt_local.strftime("%I:%M %p")


def _format_time_iso_wall(dt_local: datetime) -> str:
    return dt_local.strftime("%Y-%m-%dT%H:%M:%S")


def _today_1am_epoch_ms(tz: ZoneInfo) -> int:
    now_local = datetime.now(tz)
    today_1am_local = datetime.combine(now_local.date(), time(1, 0, 0), tzinfo=tz)
    return int(today_1am_local.astimezone(timezone.utc).timestamp() * 1000)


def _fetch_html(url: str, timeout: int = 12, max_bytes: int = 3_000_000) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; teemup-n8n-service)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as f:
        data = f.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail=f"HTML exceeded {max_bytes} bytes cap")
        return data


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"ok": True}


def _determine_meetup_url(
    cfg: Dict[str, Any], group: Optional[str], url: Optional[str]
) -> str:
    meetup_groups = cfg.get("meetup_groups", {}) or {}
    if url:
        return url
    if group:
        meetup_url = meetup_groups.get(group)
        if not meetup_url:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown group '{group}'. Known: {sorted(meetup_groups.keys())}"
            )
        return meetup_url

    # if only one group in config, use it as default
    if len(meetup_groups) == 1:
        return next(iter(meetup_groups.values()))

    raise HTTPException(status_code=400, detail="Provide ?group=... or ?url=...")


@app.get("/events")
def events(
    group: Optional[str] = None,
    url: Optional[str] = None,
    tz: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch and parse events.
    """
    cfg = _get_config()

    default_tz = cfg.get("default_tz", "America/Los_Angeles")
    tz_name = tz or default_tz

    meetup_url = _determine_meetup_url(cfg, group, url)

    try:
        zone = ZoneInfo(tz_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid tz: {tz_name}") from exc

    baseline_ms = _today_1am_epoch_ms(zone)

    try:
        html = _fetch_html(meetup_url)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Fetch failed: {e!r}") from e

    try:
        raw_events = list(teemup_parse(html))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"teemup parse failed: {e!r}") from e

    event_cfg = cfg.get("event_config", {}) or {}
    items: List[Dict[str, Any]] = []

    for ev in raw_events:
        title = (ev.get("title") or "").strip()
        if not title:
            continue

        starts_at = _ensure_datetime(ev.get("starts_at"))
        if not starts_at:
            continue

        if starts_at.tzinfo is None:
            starts_local = starts_at.replace(tzinfo=zone)
        else:
            starts_local = starts_at.astimezone(zone)

        event_ms = int(starts_local.astimezone(timezone.utc).timestamp() * 1000)
        if event_ms < baseline_ms:
            continue

        days_diff = int((event_ms - baseline_ms) // (24 * 60 * 60 * 1000))

        link = (ev.get("url") or "").strip()
        if not link:
            desc = (ev.get("description") or "").strip()
            m = re.search(r"https?://\S+", desc)
            if m:
                link = m.group(0).rstrip(")")

        chosen = _pick_event_cfg(title, event_cfg)

        items.append({
            "main": title,
            "url": link or "",
            "timeDisp": _format_time_disp(starts_local),
            "timeLocalHM": _format_time_local_hm(starts_local),
            "timeISO": _format_time_iso_wall(starts_local),
            "isAllDay": False,
            "daysDiff": days_diff,
            "thread_id": chosen.get("thread_id") or None,
            "reminder": bool(chosen.get("reminder")),
        })

    items.sort(key=lambda e: e["timeISO"])
    return items
