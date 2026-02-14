"""Tests for data models."""

import pytest
from datetime import datetime
from src.models import (
    CalendarEvent,
    ProcessedEvent,
    PrepBrief,
    TalkingPoint,
    DailyDigest,
    EventPriority,
    MeetingCategory,
)


class TestCalendarEvent:
    """Tests for CalendarEvent model and Google API parsing."""

    def test_basic_creation(self):
        event = CalendarEvent(
            event_id="test-1",
            title="Team Standup",
            start_time=datetime(2026, 2, 14, 10, 0),
            end_time=datetime(2026, 2, 14, 10, 30),
        )
        assert event.title == "Team Standup"
        assert event.source == "google_calendar"
        assert event.attendees == []
        assert event.is_all_day is False

    def test_from_google_api_timed_event(self):
        raw = {
            "id": "abc123",
            "summary": "1:1 with Sarah",
            "start": {"dateTime": "2026-02-14T10:00:00-05:00"},
            "end": {"dateTime": "2026-02-14T10:30:00-05:00"},
            "description": "Weekly sync",
            "location": "Room 101",
            "attendees": [
                {"email": "sarah@example.com", "responseStatus": "accepted"},
                {"email": "me@example.com", "responseStatus": "accepted"},
            ],
            "organizer": {"email": "me@example.com"},
            "hangoutLink": "https://meet.google.com/abc",
        }
        event = CalendarEvent.from_google_api(raw, "primary")
        assert event.event_id == "abc123"
        assert event.title == "1:1 with Sarah"
        assert event.description == "Weekly sync"
        assert event.location == "Room 101"
        assert len(event.attendees) == 2
        assert "sarah@example.com" in event.attendees
        assert event.organizer == "me@example.com"
        assert event.meeting_link == "https://meet.google.com/abc"
        assert event.is_all_day is False
        assert event.calendar_id == "primary"

    def test_from_google_api_all_day_event(self):
        raw = {
            "id": "def456",
            "summary": "Company Holiday",
            "start": {"date": "2026-02-14"},
            "end": {"date": "2026-02-15"},
        }
        event = CalendarEvent.from_google_api(raw)
        assert event.is_all_day is True
        assert event.title == "Company Holiday"

    def test_from_google_api_no_title(self):
        raw = {
            "id": "no-title",
            "start": {"dateTime": "2026-02-14T10:00:00-05:00"},
            "end": {"dateTime": "2026-02-14T10:30:00-05:00"},
        }
        event = CalendarEvent.from_google_api(raw)
        assert event.title == "(No Title)"

    def test_from_google_api_conference_data_link(self):
        raw = {
            "id": "conf-1",
            "summary": "Zoom Call",
            "start": {"dateTime": "2026-02-14T14:00:00-05:00"},
            "end": {"dateTime": "2026-02-14T15:00:00-05:00"},
            "conferenceData": {
                "entryPoints": [
                    {"entryPointType": "video", "uri": "https://zoom.us/j/123"}
                ]
            },
        }
        event = CalendarEvent.from_google_api(raw)
        assert event.meeting_link == "https://zoom.us/j/123"

    def test_from_google_api_recurring_event(self):
        raw = {
            "id": "rec-1",
            "summary": "Weekly Sync",
            "start": {"dateTime": "2026-02-14T09:00:00-05:00"},
            "end": {"dateTime": "2026-02-14T09:30:00-05:00"},
            "recurringEventId": "parent-123",
        }
        event = CalendarEvent.from_google_api(raw)
        assert event.is_recurring is True


class TestProcessedEvent:
    """Tests for ProcessedEvent model."""

    def _make_event(self, **kwargs):
        defaults = {
            "event_id": "test-1",
            "title": "Test Meeting",
            "start_time": datetime(2026, 2, 14, 10, 0),
            "end_time": datetime(2026, 2, 14, 10, 30),
        }
        defaults.update(kwargs)
        return CalendarEvent(**defaults)

    def test_default_values(self):
        event = self._make_event()
        processed = ProcessedEvent(event=event)
        assert processed.priority == EventPriority.MEDIUM
        assert processed.priority_score == 0.0
        assert processed.category == MeetingCategory.OTHER
        assert processed.is_one_on_one is False

    def test_custom_values(self):
        event = self._make_event()
        processed = ProcessedEvent(
            event=event,
            priority=EventPriority.HIGH,
            priority_score=0.85,
            category=MeetingCategory.INTERVIEW,
            is_one_on_one=False,
            attendee_count=3,
            duration_minutes=60,
            tags=["interview"],
        )
        assert processed.priority == EventPriority.HIGH
        assert processed.priority_score == 0.85
        assert processed.category == MeetingCategory.INTERVIEW


class TestPrepBrief:
    """Tests for PrepBrief model."""

    def test_default_brief(self):
        event = CalendarEvent(
            event_id="t1",
            title="Test",
            start_time=datetime(2026, 2, 14, 10, 0),
            end_time=datetime(2026, 2, 14, 10, 30),
        )
        processed = ProcessedEvent(event=event)
        brief = PrepBrief(event=processed, summary="A test meeting.")
        assert brief.summary == "A test meeting."
        assert brief.talking_points == []
        assert brief.suggested_questions == []
        assert brief.preparation_time_minutes == 5

    def test_talking_point(self):
        tp = TalkingPoint(point="Discuss roadmap", category="discussion", priority="high")
        assert tp.point == "Discuss roadmap"
        assert tp.category == "discussion"
        assert tp.priority == "high"


class TestDailyDigest:
    """Tests for DailyDigest model."""

    def test_empty_digest(self):
        digest = DailyDigest(
            date=datetime(2026, 2, 14),
            total_meetings=0,
            total_meeting_hours=0.0,
        )
        assert digest.total_meetings == 0
        assert digest.briefs == []

    def test_to_email_context(self):
        digest = DailyDigest(
            date=datetime(2026, 2, 14),
            total_meetings=3,
            total_meeting_hours=2.5,
            high_priority_count=1,
        )
        ctx = digest.to_email_context()
        assert ctx["date"] == "Saturday, February 14, 2026"
        assert ctx["total_meetings"] == 3
        assert ctx["total_hours"] == "2.5"
        assert ctx["high_priority_count"] == 1
