"""Tests for Outlook Calendar + Teams client (with mocked API calls)."""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.outlook_client import OutlookCalendarClient
from src.config import OutlookConfig


@pytest.fixture
def config():
    return OutlookConfig(
        enabled=True,
        client_id="test-client-id",
        token_path="./test_outlook_token.json",
    )


def make_graph_event(
    event_id="evt-1",
    subject="Team Meeting",
    start_hour=10,
    start_min=0,
    duration_min=30,
    attendees=None,
    is_teams=False,
    teams_url=None,
    is_cancelled=False,
    is_recurring=False,
    location=None,
):
    """Create a mock Microsoft Graph calendar event."""
    start = f"2026-02-14T{start_hour:02d}:{start_min:02d}:00.0000000Z"
    end_hour = start_hour + (start_min + duration_min) // 60
    end_min = (start_min + duration_min) % 60
    end = f"2026-02-14T{end_hour:02d}:{end_min:02d}:00.0000000Z"

    event = {
        "id": event_id,
        "subject": subject,
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "body": {"content": ""},
        "location": {"displayName": location or ""},
        "attendees": [
            {"emailAddress": {"address": a}} for a in (attendees or [])
        ],
        "organizer": {"emailAddress": {"address": "organizer@example.com"}},
        "isOnlineMeeting": is_teams,
        "onlineMeeting": {"joinUrl": teams_url} if teams_url else None,
        "isCancelled": is_cancelled,
        "recurrence": "daily" if is_recurring else None,
    }
    return event


class TestOutlookEventParsing:
    """Tests for parsing Microsoft Graph events into CalendarEvent models."""

    def test_parse_basic_event(self, config):
        client = OutlookCalendarClient(config)
        raw = make_graph_event(subject="Sprint Planning", start_hour=14, duration_min=60)
        event = client._parse_event(raw)

        assert event.title == "Sprint Planning"
        assert event.source == "outlook"
        assert event.calendar_id == "outlook"
        assert event.is_all_day is False

    def test_parse_teams_meeting(self, config):
        client = OutlookCalendarClient(config)
        raw = make_graph_event(
            subject="1:1 with Manager",
            is_teams=True,
            teams_url="https://teams.microsoft.com/l/meetup-join/123",
        )
        event = client._parse_event(raw)

        assert event.source == "outlook_teams"
        assert event.meeting_link == "https://teams.microsoft.com/l/meetup-join/123"

    def test_parse_attendees(self, config):
        client = OutlookCalendarClient(config)
        raw = make_graph_event(
            attendees=["alice@example.com", "bob@example.com"],
        )
        event = client._parse_event(raw)

        assert len(event.attendees) == 2
        assert "alice@example.com" in event.attendees

    def test_parse_recurring_event(self, config):
        client = OutlookCalendarClient(config)
        raw = make_graph_event(is_recurring=True)
        event = client._parse_event(raw)

        assert event.is_recurring is True

    def test_parse_event_with_location(self, config):
        client = OutlookCalendarClient(config)
        raw = make_graph_event(location="Building 40, Room 1234")
        event = client._parse_event(raw)

        assert event.location == "Building 40, Room 1234"

    def test_parse_no_subject(self, config):
        client = OutlookCalendarClient(config)
        raw = make_graph_event()
        del raw["subject"]
        event = client._parse_event(raw)

        assert event.title == "(No Subject)"

    def test_non_teams_online_meeting(self, config):
        client = OutlookCalendarClient(config)
        raw = make_graph_event(is_teams=False)
        event = client._parse_event(raw)

        assert event.source == "outlook"
        assert event.meeting_link is None


class TestOutlookFetchEvents:
    """Tests for fetching events with mocked HTTP responses."""

    @patch("src.outlook_client.requests.get")
    def test_fetch_events_success(self, mock_get, config):
        client = OutlookCalendarClient(config)
        client._access_token = "test-token"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [
                make_graph_event(subject="Meeting 1"),
                make_graph_event(subject="Meeting 2", event_id="evt-2"),
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        now = datetime(2026, 2, 14, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
        events = client.fetch_events(now, end)

        assert len(events) == 2
        mock_get.assert_called_once()

    @patch("src.outlook_client.requests.get")
    def test_fetch_skips_cancelled(self, mock_get, config):
        client = OutlookCalendarClient(config)
        client._access_token = "test-token"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [
                make_graph_event(subject="Active Meeting"),
                make_graph_event(subject="Cancelled", is_cancelled=True, event_id="c1"),
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        now = datetime(2026, 2, 14, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
        events = client.fetch_events(now, end)

        assert len(events) == 1
        assert events[0].title == "Active Meeting"

    def test_fetch_without_auth_raises(self, config):
        client = OutlookCalendarClient(config)
        now = datetime(2026, 2, 14, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)

        with pytest.raises(RuntimeError, match="Not authenticated"):
            client.fetch_events(now, end)

    @patch("src.outlook_client.requests.get")
    def test_fetch_separates_teams_from_outlook(self, mock_get, config):
        client = OutlookCalendarClient(config)
        client._access_token = "test-token"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [
                make_graph_event(subject="Outlook Meeting", event_id="o1"),
                make_graph_event(
                    subject="Teams Call",
                    event_id="t1",
                    is_teams=True,
                    teams_url="https://teams.microsoft.com/123",
                ),
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        now = datetime(2026, 2, 14, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc)
        events = client.fetch_events(now, end)

        outlook_events = [e for e in events if e.source == "outlook"]
        teams_events = [e for e in events if e.source == "outlook_teams"]

        assert len(outlook_events) == 1
        assert len(teams_events) == 1
        assert teams_events[0].meeting_link == "https://teams.microsoft.com/123"


class TestOutlookConfig:
    """Tests for Outlook configuration."""

    def test_default_disabled(self):
        config = OutlookConfig()
        assert config.enabled is False

    def test_missing_client_id_raises(self):
        config = OutlookConfig(enabled=True, client_id="")
        client = OutlookCalendarClient(config)
        with pytest.raises(ValueError, match="OUTLOOK_CLIENT_ID not set"):
            client.authenticate()
