"""Tests for university events discovery."""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from src.university_events import UniversityEventsClient, UNIVERSITY_ENDPOINTS


def make_localist_event(
    event_id=1,
    title="AI Research Symposium",
    start_hour=14,
    start_min=0,
    duration_hours=2,
    location="Stewart Center",
    description="A talk about AI research at Purdue.",
    event_types=None,
    experience="inperson",
    is_all_day=False,
):
    """Create a mock Localist API event."""
    start = datetime(2026, 2, 20, start_hour, start_min, tzinfo=timezone.utc)
    end = start + timedelta(hours=duration_hours)

    return {
        "event": {
            "id": event_id,
            "title": title,
            "event_instances": [
                {
                    "event_instance": {
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "all_day": is_all_day,
                    }
                }
            ],
            "location_name": location,
            "description_text": description,
            "localist_url": f"https://events.purdue.edu/event/{event_id}",
            "filters": {
                "event_types": [
                    {"name": et} for et in (event_types or ["Lectures and Seminars"])
                ],
            },
            "experience": experience,
        }
    }


class TestUniversityEventsClient:
    """Tests for university event fetching and parsing."""

    def test_init_valid_university(self):
        client = UniversityEventsClient("purdue")
        assert client.university == "purdue"
        assert "purdue" in client.uni["base_url"]

    def test_init_invalid_university(self):
        with pytest.raises(ValueError, match="Unknown university"):
            UniversityEventsClient("nonexistent")

    def test_parse_basic_event(self):
        client = UniversityEventsClient("purdue")
        raw = make_localist_event()["event"]
        parsed = client._parse_event(raw)

        assert parsed is not None
        assert parsed["title"] == "AI Research Symposium"
        assert parsed["location"] == "Stewart Center"
        assert parsed["source"] == "university_purdue"
        assert isinstance(parsed["start_time"], datetime)
        assert "Lectures and Seminars" in parsed["event_types"]

    def test_parse_virtual_event(self):
        client = UniversityEventsClient("purdue")
        raw = make_localist_event(experience="virtual")["event"]
        parsed = client._parse_event(raw)

        assert parsed["experience"] == "virtual"

    def test_parse_all_day_event(self):
        client = UniversityEventsClient("purdue")
        raw = make_localist_event(is_all_day=True)["event"]
        parsed = client._parse_event(raw)

        assert parsed["is_all_day"] is True

    def test_parse_event_no_title_returns_none(self):
        client = UniversityEventsClient("purdue")
        raw = make_localist_event()["event"]
        raw["title"] = ""
        parsed = client._parse_event(raw)

        assert parsed is None

    def test_parse_long_description_truncated(self):
        client = UniversityEventsClient("purdue")
        long_desc = "A" * 500
        raw = make_localist_event(description=long_desc)["event"]
        parsed = client._parse_event(raw)

        assert len(parsed["description"]) <= 303  # 297 + "..."

    def test_parse_time_iso_format(self):
        result = UniversityEventsClient._parse_time("2026-02-20T14:00:00+00:00")
        assert result is not None
        assert result.hour == 14

    def test_parse_time_with_z(self):
        result = UniversityEventsClient._parse_time("2026-02-20T14:00:00Z")
        assert result is not None

    def test_parse_time_date_only(self):
        result = UniversityEventsClient._parse_time("2026-02-20")
        assert result is not None
        assert result.year == 2026

    def test_parse_time_invalid(self):
        result = UniversityEventsClient._parse_time("not-a-date")
        assert result is None

    def test_parse_time_empty(self):
        result = UniversityEventsClient._parse_time("")
        assert result is None


class TestFetchEvents:
    """Tests for API fetching with mocked HTTP."""

    @patch("src.university_events.requests.get")
    def test_fetch_events_success(self, mock_get):
        client = UniversityEventsClient("purdue")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "events": [
                make_localist_event(event_id=1, title="Event 1"),
                make_localist_event(event_id=2, title="Event 2"),
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        events = client.fetch_upcoming_events(days=7)

        assert len(events) == 2
        assert events[0]["title"] == "Event 1"
        mock_get.assert_called_once()

    @patch("src.university_events.requests.get")
    def test_fetch_events_api_error(self, mock_get):
        client = UniversityEventsClient("purdue")

        import requests
        mock_get.side_effect = requests.RequestException("Connection failed")

        events = client.fetch_upcoming_events()

        assert events == []

    @patch("src.university_events.requests.get")
    def test_fetch_events_empty_response(self, mock_get):
        client = UniversityEventsClient("purdue")

        mock_response = MagicMock()
        mock_response.json.return_value = {"events": []}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        events = client.fetch_upcoming_events()
        assert events == []


class TestPickAndSave:
    """Tests for the interactive event selection and saving."""

    @patch("builtins.input")
    def test_pick_none(self, mock_input):
        client = UniversityEventsClient("purdue")
        mock_input.return_value = "none"
        store = MagicMock()

        event = {
            "title": "Test Event",
            "start_time": datetime(2026, 2, 20, 14, 0, tzinfo=timezone.utc),
            "end_time": datetime(2026, 2, 20, 16, 0, tzinfo=timezone.utc),
            "is_all_day": False,
            "location": "Room 101",
            "description": "A test event",
            "event_types": ["Lecture"],
            "experience": "inperson",
        }
        result = client.pick_and_save([event], store)
        assert result == 0

    def test_pick_empty_events(self):
        client = UniversityEventsClient("purdue")
        store = MagicMock()

        result = client.pick_and_save([], store)
        assert result == 0


class TestEndpoints:
    """Tests for university endpoint configuration."""

    def test_purdue_endpoint_exists(self):
        assert "purdue" in UNIVERSITY_ENDPOINTS
        assert "base_url" in UNIVERSITY_ENDPOINTS["purdue"]
        assert "api_path" in UNIVERSITY_ENDPOINTS["purdue"]
