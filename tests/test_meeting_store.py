"""Tests for the manual meeting store."""

import pytest
import json
from datetime import datetime, date, timedelta
from pathlib import Path
from src.meeting_store import MeetingStore


@pytest.fixture
def store(tmp_path):
    """Create a MeetingStore with a temporary file."""
    store_path = tmp_path / "test_meetings.json"
    return MeetingStore(store_path=str(store_path))


@pytest.fixture
def future_time():
    """Return a start time 2 hours from now."""
    now = datetime.now()
    return now.replace(second=0, microsecond=0) + timedelta(hours=2)


class TestMeetingStore:
    """Tests for MeetingStore CRUD operations."""

    def test_creates_store_file(self, tmp_path):
        store_path = tmp_path / "new_store.json"
        assert not store_path.exists()
        MeetingStore(store_path=str(store_path))
        assert store_path.exists()
        assert json.loads(store_path.read_text()) == []

    def test_add_meeting(self, store, future_time):
        end_time = future_time + timedelta(minutes=30)
        meeting = store.add_meeting(
            title="Test Meeting",
            start_time=future_time,
            end_time=end_time,
        )
        assert meeting["title"] == "Test Meeting"
        assert "id" in meeting
        assert meeting["source"] == "manual"

    def test_add_meeting_with_all_fields(self, store, future_time):
        end_time = future_time + timedelta(minutes=60)
        meeting = store.add_meeting(
            title="Client Sync",
            start_time=future_time,
            end_time=end_time,
            attendees=["alice@co.com", "bob@co.com"],
            description="Discuss Q1 roadmap",
            location="Room 204",
            meeting_link="https://meet.google.com/abc",
            is_recurring=True,
        )
        assert meeting["attendees"] == ["alice@co.com", "bob@co.com"]
        assert meeting["description"] == "Discuss Q1 roadmap"
        assert meeting["location"] == "Room 204"
        assert meeting["meeting_link"] == "https://meet.google.com/abc"
        assert meeting["is_recurring"] is True

    def test_get_all_meetings(self, store, future_time):
        end = future_time + timedelta(minutes=30)
        store.add_meeting(title="Meeting 1", start_time=future_time, end_time=end)
        store.add_meeting(title="Meeting 2", start_time=future_time, end_time=end)

        meetings = store.get_all_meetings()
        assert len(meetings) == 2

    def test_get_meetings_for_date(self, store):
        today = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        store.add_meeting(
            title="Today's Meeting",
            start_time=today,
            end_time=today + timedelta(minutes=30),
        )
        store.add_meeting(
            title="Tomorrow's Meeting",
            start_time=tomorrow,
            end_time=tomorrow + timedelta(minutes=30),
        )

        today_meetings = store.get_meetings_for_date(today.date())
        assert len(today_meetings) == 1
        assert today_meetings[0]["title"] == "Today's Meeting"

    def test_get_upcoming_meetings(self, store):
        now = datetime.now()
        future = now + timedelta(hours=1)
        past = now - timedelta(hours=2)

        store.add_meeting(
            title="Upcoming",
            start_time=future,
            end_time=future + timedelta(minutes=30),
        )
        store.add_meeting(
            title="Past",
            start_time=past,
            end_time=past + timedelta(minutes=30),
        )

        upcoming = store.get_upcoming_meetings(hours=24)
        assert len(upcoming) == 1
        assert upcoming[0]["title"] == "Upcoming"

    def test_remove_meeting(self, store, future_time):
        end = future_time + timedelta(minutes=30)
        meeting = store.add_meeting(title="To Remove", start_time=future_time, end_time=end)

        assert store.remove_meeting(meeting["id"]) is True
        assert len(store.get_all_meetings()) == 0

    def test_remove_nonexistent_meeting(self, store):
        assert store.remove_meeting("nonexistent-id") is False

    def test_clear_past_meetings(self, store):
        now = datetime.now()
        past = now - timedelta(hours=3)
        future = now + timedelta(hours=1)

        store.add_meeting(
            title="Past Meeting",
            start_time=past,
            end_time=past + timedelta(minutes=30),
        )
        store.add_meeting(
            title="Future Meeting",
            start_time=future,
            end_time=future + timedelta(minutes=30),
        )

        removed = store.clear_past_meetings()
        assert removed == 1
        meetings = store.get_all_meetings()
        assert len(meetings) == 1
        assert meetings[0]["title"] == "Future Meeting"

    def test_to_calendar_events(self, store, future_time):
        end = future_time + timedelta(minutes=45)
        store.add_meeting(
            title="Converted Meeting",
            start_time=future_time,
            end_time=end,
            attendees=["alice@example.com"],
            description="Test agenda",
            location="Room A",
            meeting_link="https://zoom.us/j/123",
        )

        events = store.to_calendar_events()
        assert len(events) == 1

        event = events[0]
        assert event.title == "Converted Meeting"
        assert event.source == "manual"
        assert event.calendar_id == "manual"
        assert event.event_id.startswith("manual-")
        assert len(event.attendees) == 1
        assert event.meeting_link == "https://zoom.us/j/123"

    def test_to_calendar_events_empty_store(self, store):
        events = store.to_calendar_events()
        assert events == []

    def test_persistence_across_instances(self, tmp_path, future_time):
        store_path = str(tmp_path / "persist.json")
        end = future_time + timedelta(minutes=30)

        # Write with one instance
        store1 = MeetingStore(store_path=store_path)
        store1.add_meeting(title="Persisted", start_time=future_time, end_time=end)

        # Read with another instance
        store2 = MeetingStore(store_path=store_path)
        meetings = store2.get_all_meetings()
        assert len(meetings) == 1
        assert meetings[0]["title"] == "Persisted"
