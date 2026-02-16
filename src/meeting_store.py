"""
Local meeting storage for manually added events.

When you have meetings that aren't on Google Calendar (ad-hoc meetings,
events from other platforms, or meetings you want to track manually),
this module provides a simple JSON-based store to persist them.

Storage format:
    meetings.json - a JSON array of meeting objects in the project root

Usage:
    store = MeetingStore()
    store.add_meeting(title="1:1 with Alex", start="2026-02-14 10:00", ...)
    meetings = store.get_meetings_for_date(date.today())
    store.remove_meeting(meeting_id)
"""

import json
import logging
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional

from src.models import CalendarEvent

logger = logging.getLogger(__name__)

DEFAULT_STORE_PATH = "./meetings.json"


class MeetingStore:
    """
    JSON file-based storage for manually added meetings.

    Meetings are stored in a simple JSON file so they persist across runs
    without needing a database. Each meeting gets a unique ID.
    """

    def __init__(self, store_path: str = DEFAULT_STORE_PATH):
        self.store_path = Path(store_path)
        self._ensure_store_exists()

    def _ensure_store_exists(self) -> None:
        """Create the store file if it doesn't exist."""
        if not self.store_path.exists():
            self.store_path.write_text("[]")
            logger.info("Created meeting store at %s", self.store_path)

    def _load(self) -> List[dict]:
        """Load all meetings from the JSON file."""
        try:
            data = json.loads(self.store_path.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to load meeting store: %s", e)
            return []

    def _save(self, meetings: List[dict]) -> None:
        """Save all meetings to the JSON file."""
        self.store_path.write_text(json.dumps(meetings, indent=2, default=str))

    def add_meeting(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendees: Optional[List[str]] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        meeting_link: Optional[str] = None,
        is_recurring: bool = False,
        category: Optional[str] = None,
        person_linkedin: Optional[str] = None,
        person_notes: Optional[str] = None,
    ) -> dict:
        """
        Add a new meeting to the store.

        Args:
            title: Meeting title/subject
            start_time: When the meeting starts
            end_time: When the meeting ends
            attendees: List of attendee emails/names
            description: Meeting description or agenda
            location: Physical location or room name
            meeting_link: Video call URL (Zoom, Meet, Teams)
            is_recurring: Whether this is a recurring meeting
            category: Meeting category (interview, networking, class, etc.)
            person_linkedin: LinkedIn URL for key person in the meeting
            person_notes: Notes about the person (role, company, context)

        Returns:
            The created meeting dict (with generated ID)
        """
        meeting = {
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "attendees": attendees or [],
            "description": description or "",
            "location": location or "",
            "meeting_link": meeting_link or "",
            "is_recurring": is_recurring,
            "category": category or "",
            "person_linkedin": person_linkedin or "",
            "person_notes": person_notes or "",
            "source": "manual",
            "created_at": datetime.now().isoformat(),
        }

        meetings = self._load()
        meetings.append(meeting)
        self._save(meetings)

        logger.info("Added meeting: %s at %s", title, start_time)
        return meeting

    def get_all_meetings(self) -> List[dict]:
        """Get all stored meetings."""
        return self._load()

    def get_meetings_for_date(self, target_date: date) -> List[dict]:
        """
        Get meetings scheduled for a specific date.

        Args:
            target_date: The date to filter by

        Returns:
            List of meetings on that date
        """
        meetings = self._load()
        result = []

        for m in meetings:
            try:
                start = datetime.fromisoformat(m["start_time"])
                if start.date() == target_date:
                    result.append(m)
            except (ValueError, KeyError):
                continue

        return result

    def get_upcoming_meetings(self, hours: int = 24) -> List[dict]:
        """
        Get meetings in the next N hours (matches Google Calendar lookahead).

        Args:
            hours: How far ahead to look (default: 24)

        Returns:
            List of upcoming meetings
        """
        now = datetime.now()
        cutoff = now + timedelta(hours=hours)
        meetings = self._load()
        result = []

        for m in meetings:
            try:
                start = datetime.fromisoformat(m["start_time"])
                if now <= start <= cutoff:
                    result.append(m)
            except (ValueError, KeyError):
                continue

        return result

    def update_meeting(self, meeting_id: str, **fields) -> bool:
        """
        Update fields on an existing meeting.

        Args:
            meeting_id: The unique ID of the meeting to update
            **fields: Key-value pairs to update (e.g., description="new desc")

        Returns:
            True if updated, False if not found
        """
        meetings = self._load()
        for m in meetings:
            if m.get("id") == meeting_id:
                m.update(fields)
                self._save(meetings)
                logger.info("Updated meeting %s: %s", meeting_id, list(fields.keys()))
                return True
        return False

    def remove_meeting(self, meeting_id: str) -> bool:
        """
        Remove a meeting by its ID.

        Args:
            meeting_id: The unique ID of the meeting to remove

        Returns:
            True if removed, False if not found
        """
        meetings = self._load()
        original_count = len(meetings)
        meetings = [m for m in meetings if m.get("id") != meeting_id]

        if len(meetings) < original_count:
            self._save(meetings)
            logger.info("Removed meeting: %s", meeting_id)
            return True

        logger.warning("Meeting not found: %s", meeting_id)
        return False

    def clear_past_meetings(self) -> int:
        """
        Remove all meetings that have already ended.

        Returns:
            Number of meetings removed
        """
        now = datetime.now()
        meetings = self._load()
        original_count = len(meetings)

        active = []
        for m in meetings:
            try:
                end = datetime.fromisoformat(m["end_time"])
                if end >= now:
                    active.append(m)
            except (ValueError, KeyError):
                active.append(m)  # keep unparseable ones

        self._save(active)
        removed = original_count - len(active)
        if removed:
            logger.info("Cleared %d past meetings", removed)
        return removed

    def to_calendar_events(self, meetings: Optional[List[dict]] = None) -> List[CalendarEvent]:
        """
        Convert stored meetings to CalendarEvent models for the pipeline.

        This bridges manual meetings into the same format as Google Calendar
        events, so the rest of the pipeline (processor, AI briefer, email)
        can handle them identically.

        Args:
            meetings: Specific meetings to convert. If None, uses upcoming.

        Returns:
            List of CalendarEvent models
        """
        if meetings is None:
            meetings = self.get_upcoming_meetings()

        events = []
        for m in meetings:
            try:
                event = CalendarEvent(
                    event_id=f"manual-{m['id']}",
                    title=m["title"],
                    start_time=datetime.fromisoformat(m["start_time"]),
                    end_time=datetime.fromisoformat(m["end_time"]),
                    description=m.get("description"),
                    location=m.get("location"),
                    attendees=m.get("attendees", []),
                    organizer=None,
                    is_recurring=m.get("is_recurring", False),
                    is_all_day=False,
                    meeting_link=m.get("meeting_link"),
                    calendar_id="manual",
                    source="manual",
                )
                events.append(event)
            except Exception as e:
                logger.warning("Failed to convert manual meeting '%s': %s", m.get("title"), e)

        return events
