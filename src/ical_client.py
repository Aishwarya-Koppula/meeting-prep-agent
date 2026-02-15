"""
iCal / ICS subscription client for calendar feeds.

Supports:
- UniTime: university course timetables (students/instructors copy "iCalendar URL"
  from Personal Timetable → Export → Copy iCalendar URL).
- Any public or private .ics URL (course schedules, event feeds, etc.).

Events are fetched over HTTP, parsed with the icalendar library, and converted
to CalendarEvent so they merge with Google, Outlook, and manual meetings.
"""

import json
import logging
from datetime import datetime, timedelta, timezone as _tz
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import requests

from src.models import CalendarEvent

logger = logging.getLogger(__name__)

DEFAULT_SOURCES_PATH = "./ical_sources.json"


def load_ical_sources(path: str = DEFAULT_SOURCES_PATH) -> List[dict]:
    """
    Load iCal subscription URLs from JSON file.

    Format: {"subscriptions": [{"url": "https://...", "name": "UniTime"}, ...]}
    Returns empty list if file missing or invalid.
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        subs = data.get("subscriptions", [])
        return subs if isinstance(subs, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def save_ical_sources(subscriptions: List[dict], path: str = DEFAULT_SOURCES_PATH) -> None:
    """Save iCal subscription list to JSON."""
    Path(path).write_text(json.dumps({"subscriptions": subscriptions}, indent=2))


def fetch_events_from_ical_url(
    url: str,
    lookahead_hours: int = 24,
    source_label: str = "ical",
) -> List[CalendarEvent]:
    """
    Fetch an iCal feed from URL and return events within lookahead.

    Args:
        url: Full URL to .ics feed (e.g. UniTime "Copy iCalendar URL").
        lookahead_hours: Only include events starting within this many hours.
        source_label: CalendarEvent.source value (e.g. "ical", "unitime").

    Returns:
        List of CalendarEvent (may be empty on parse/network error).
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        ics_data = resp.content
    except requests.RequestException as e:
        logger.warning("Failed to fetch iCal URL %s: %s", url[:60], e)
        return []

    try:
        import icalendar
    except ImportError:
        logger.warning("icalendar package not installed. pip install icalendar")
        return []

    try:
        cal = icalendar.Calendar.from_ical(ics_data)
    except Exception as e:
        logger.warning("Failed to parse iCal from %s: %s", url[:60], e)
        return []

    events = []
    now_utc = datetime.now(_tz.utc)
    until_utc = now_utc + timedelta(hours=lookahead_hours)

    for component in cal.walk("VEVENT"):
        ev = _vevent_to_calendar_event(component, source_label, url)
        if ev is None:
            continue
        # Normalise to UTC for comparison (handle naive & aware datetimes)
        st = ev.start_time if ev.start_time.tzinfo else ev.start_time.replace(tzinfo=_tz.utc)
        et = ev.end_time if ev.end_time.tzinfo else ev.end_time.replace(tzinfo=_tz.utc)
        if st <= until_utc and et >= now_utc:
            events.append(ev)

    return events


def _vevent_to_calendar_event(vevent, source_label: str, feed_url: str) -> Optional[CalendarEvent]:
    """Convert an icalendar VEVENT to CalendarEvent."""
    try:
        uid = str(vevent.get("UID", "") or "")
        summary = vevent.get("SUMMARY")
        if summary is None:
            summary = "(No Title)"
        title = str(summary).strip() or "(No Title)"

        dtstart = vevent.get("DTSTART")
        dtend = vevent.get("DTEND")
        if not dtstart:
            return None
        start_dt = dtstart.dt
        if hasattr(start_dt, "tzinfo") and start_dt.tzinfo is None:
            # All-day or naive; treat as local
            pass
        end_dt = dtend.dt if dtend else (start_dt + timedelta(hours=1))
        if hasattr(end_dt, "tzinfo") and end_dt.tzinfo is None:
            pass

        # Ensure we have datetime (not date)
        if hasattr(start_dt, "hour"):
            start_time = start_dt
        else:
            start_time = datetime.combine(start_dt, datetime.min.time())
        if hasattr(end_dt, "hour"):
            end_time = end_dt
        else:
            end_time = datetime.combine(end_dt, datetime.min.time())

        description = vevent.get("DESCRIPTION")
        desc_str = str(description).strip() if description else None
        location = vevent.get("LOCATION")
        loc_str = str(location).strip() if location else None

        event_id = uid or f"ical-{hash((feed_url, title, start_time)) % 2**32}"
        is_all_day = not hasattr(dtstart.dt, "hour") if dtstart else False

        return CalendarEvent(
            event_id=event_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            description=desc_str,
            location=loc_str,
            attendees=[],
            organizer=None,
            is_recurring=bool(vevent.get("RRULE")),
            is_all_day=is_all_day,
            meeting_link=None,
            calendar_id=urlparse(feed_url).netloc or "ical",
            source=source_label,
        )
    except Exception as e:
        logger.debug("Skip VEVENT: %s", e)
        return None


def fetch_all_ical_events(
    lookahead_hours: int = 24,
    sources_path: str = DEFAULT_SOURCES_PATH,
) -> List[CalendarEvent]:
    """
    Load all iCal subscription URLs and fetch their events.

    Uses ical_sources.json by default. Each subscription can have "url" and
    optional "name"; if name contains "unitime" we set source=unitime.
    """
    subs = load_ical_sources(sources_path)
    all_events = []
    for sub in subs:
        url = (sub if isinstance(sub, str) else sub.get("url", "") or "").strip()
        if not url:
            continue
        name = (sub.get("name", "") if isinstance(sub, dict) else "") or ""
        source_label = "unitime" if "unitime" in name.lower() or "unitime" in url.lower() else "ical"
        events = fetch_events_from_ical_url(url, lookahead_hours=lookahead_hours, source_label=source_label)
        all_events.extend(events)
        logger.info("iCal %s: %d events", name or url[:40], len(events))
    return all_events
