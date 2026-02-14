"""Tests for the event processing pipeline."""

import pytest
from datetime import datetime
from src.models import (
    CalendarEvent,
    ProcessedEvent,
    EventPriority,
    MeetingCategory,
)
from src.event_processor import EventProcessor
from src.config import FilterConfig


@pytest.fixture
def default_config():
    return FilterConfig()


@pytest.fixture
def processor(default_config):
    return EventProcessor(default_config)


def make_event(
    title="Team Meeting",
    start_hour=10,
    start_min=0,
    duration_min=30,
    attendees=None,
    description=None,
    organizer=None,
    is_all_day=False,
    is_recurring=False,
    calendar_id="primary",
):
    """Helper to create test CalendarEvents."""
    start = datetime(2026, 2, 14, start_hour, start_min)
    end = datetime(2026, 2, 14, start_hour, start_min + duration_min) if start_min + duration_min < 60 else datetime(
        2026, 2, 14, start_hour + (start_min + duration_min) // 60, (start_min + duration_min) % 60
    )
    return CalendarEvent(
        event_id=f"evt-{title.lower().replace(' ', '-')}",
        title=title,
        start_time=start,
        end_time=end,
        attendees=attendees or [],
        description=description,
        organizer=organizer,
        is_all_day=is_all_day,
        is_recurring=is_recurring,
        calendar_id=calendar_id,
    )


class TestFiltering:
    """Tests for event filtering logic."""

    def test_filters_all_day_events(self, processor):
        events = [make_event(title="Holiday", is_all_day=True)]
        result = processor.filter_events(events)
        assert len(result) == 0

    def test_keeps_timed_events(self, processor):
        events = [make_event(title="1:1 with Sarah")]
        result = processor.filter_events(events)
        assert len(result) == 1

    def test_filters_short_events(self, processor):
        events = [make_event(title="Quick ping", duration_min=5)]
        result = processor.filter_events(events)
        assert len(result) == 0

    def test_filters_by_exclude_pattern(self, processor):
        events = [
            make_event(title="OOO - Vacation"),
            make_event(title="Focus Time"),
            make_event(title="Lunch Break"),
            make_event(title="Product Review"),  # should pass
        ]
        result = processor.filter_events(events)
        titles = [e.title for e in result]
        assert "Product Review" in titles
        assert "OOO - Vacation" not in titles
        assert "Focus Time" not in titles

    def test_custom_filter_patterns(self):
        config = FilterConfig(exclude_patterns=["standup", "daily sync"])
        processor = EventProcessor(config)
        events = [
            make_event(title="Team Standup"),
            make_event(title="Daily Sync"),
            make_event(title="Sprint Planning"),  # should pass
        ]
        result = processor.filter_events(events)
        assert len(result) == 1
        assert result[0].title == "Sprint Planning"

    def test_filters_by_min_attendees(self):
        config = FilterConfig(min_attendees=2)
        processor = EventProcessor(config)
        events = [
            make_event(title="Solo Focus", attendees=[]),
            make_event(title="Pair Meeting", attendees=["a@x.com", "b@x.com"]),
        ]
        result = processor.filter_events(events)
        assert len(result) == 1
        assert result[0].title == "Pair Meeting"


class TestDeduplication:
    """Tests for cross-calendar deduplication."""

    def test_removes_exact_duplicates(self, processor):
        events = [
            make_event(title="Team Meeting", calendar_id="work"),
            make_event(title="Team Meeting", calendar_id="personal"),
        ]
        result = processor.deduplicate(events)
        assert len(result) == 1

    def test_case_insensitive_dedup(self, processor):
        events = [
            make_event(title="Team Meeting"),
            make_event(title="team meeting"),
        ]
        result = processor.deduplicate(events)
        assert len(result) == 1

    def test_keeps_different_meetings(self, processor):
        events = [
            make_event(title="Team Meeting", start_hour=10),
            make_event(title="Client Call", start_hour=14),
        ]
        result = processor.deduplicate(events)
        assert len(result) == 2

    def test_keeps_version_with_more_detail(self, processor):
        events = [
            make_event(title="Team Meeting", description=None),
            make_event(title="Team Meeting", description="Detailed agenda for the meeting"),
        ]
        result = processor.deduplicate(events)
        assert len(result) == 1
        assert result[0].description == "Detailed agenda for the meeting"

    def test_empty_events_list(self, processor):
        assert processor.deduplicate([]) == []


class TestClassification:
    """Tests for meeting type classification."""

    def test_classifies_standup(self, processor):
        events = [make_event(title="Daily Standup")]
        result = processor.process(events)
        assert result[0].category == MeetingCategory.STANDUP

    def test_classifies_one_on_one(self, processor):
        events = [make_event(title="Sync with Alex", attendees=["alex@x.com", "me@x.com"])]
        result = processor.process(events)
        assert result[0].category == MeetingCategory.ONE_ON_ONE

    def test_classifies_interview(self, processor):
        events = [make_event(title="Interview - Senior Engineer")]
        result = processor.process(events)
        assert result[0].category == MeetingCategory.INTERVIEW

    def test_classifies_client_meeting(self, processor):
        events = [make_event(title="Client Review - Acme Corp")]
        result = processor.process(events)
        assert result[0].category == MeetingCategory.CLIENT

    def test_classifies_team_meeting(self, processor):
        events = [make_event(
            title="Sprint Planning",
            attendees=["a@x.com", "b@x.com", "c@x.com", "d@x.com"],
        )]
        result = processor.process(events)
        assert result[0].category == MeetingCategory.TEAM

    def test_classifies_networking(self, processor):
        events = [make_event(title="Coffee Chat with Alumni")]
        result = processor.process(events)
        assert result[0].category == MeetingCategory.NETWORKING

    def test_classifies_all_hands(self, processor):
        events = [make_event(title="All-Hands Company Meeting")]
        result = processor.process(events)
        assert result[0].category == MeetingCategory.ALL_HANDS


class TestPriorityScoring:
    """Tests for priority scoring logic."""

    def test_interview_is_high_priority(self, processor):
        events = [make_event(
            title="Interview - Product Manager",
            attendees=["hr@company.com", "me@example.com"],
            duration_min=45,
            description="Technical phone screen",
        )]
        result = processor.process(events)
        assert result[0].priority == EventPriority.HIGH

    def test_standup_is_low_priority(self, processor):
        events = [make_event(
            title="Daily Standup",
            is_recurring=True,
            attendees=["a@x.com", "b@x.com"],
            duration_min=15,
        )]
        result = processor.process(events)
        assert result[0].priority == EventPriority.LOW

    def test_sorted_by_priority_descending(self, processor):
        events = [
            make_event(title="Daily Standup", is_recurring=True, start_hour=9),
            make_event(
                title="Interview - Senior Engineer",
                start_hour=14,
                duration_min=45,
                description="Final round",
            ),
            make_event(title="Team Sprint Planning", start_hour=11, attendees=["a@x.com", "b@x.com", "c@x.com"]),
        ]
        result = processor.process(events)
        # Interview should be first (highest priority)
        assert result[0].category == MeetingCategory.INTERVIEW

    def test_external_attendees_boost_priority(self, processor):
        events = [make_event(
            title="Vendor Discussion",
            organizer="me@company.com",
            attendees=["me@company.com", "contact@vendor.com"],
            duration_min=30,
        )]
        result = processor.process(events)
        # External attendees should boost score
        assert result[0].priority_score > 0.35


class TestFullPipeline:
    """Integration tests for the full processing pipeline."""

    def test_full_pipeline_with_mixed_events(self, processor):
        events = [
            make_event(title="Holiday", is_all_day=True),
            make_event(title="OOO - Sick Day", duration_min=30),
            make_event(title="Quick ping", duration_min=5),
            make_event(title="Interview - ML Engineer", start_hour=10, duration_min=45),
            make_event(title="Team Standup", start_hour=9, is_recurring=True, duration_min=15),
            make_event(title="1:1 with Manager", start_hour=14, attendees=["mgr@x.com", "me@x.com"], duration_min=30),
        ]
        result = processor.process(events)

        # Holiday (all-day), OOO (pattern), Quick ping (too short) should be filtered
        assert len(result) == 3

        # Interview should be highest priority
        assert result[0].event.title == "Interview - ML Engineer"

    def test_pipeline_with_no_events(self, processor):
        result = processor.process([])
        assert result == []
