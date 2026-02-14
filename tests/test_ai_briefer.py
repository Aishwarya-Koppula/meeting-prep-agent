"""Tests for AI brief generation (with mocked API calls)."""

import pytest
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.ai_briefer import AIBriefer, SYSTEM_PROMPT, CATEGORY_PROMPTS
from src.models import (
    CalendarEvent,
    ProcessedEvent,
    PrepBrief,
    EventPriority,
    MeetingCategory,
)
from src.config import AnthropicConfig


@pytest.fixture
def config():
    return AnthropicConfig(api_key="test-key", model="claude-sonnet-4-20250514")


@pytest.fixture
def sample_event():
    event = CalendarEvent(
        event_id="test-1",
        title="1:1 with Sarah",
        start_time=datetime(2026, 2, 14, 10, 0),
        end_time=datetime(2026, 2, 14, 10, 30),
        attendees=["sarah@example.com", "me@example.com"],
        organizer="me@example.com",
        description="Weekly sync",
    )
    return ProcessedEvent(
        event=event,
        priority=EventPriority.HIGH,
        priority_score=0.75,
        category=MeetingCategory.ONE_ON_ONE,
        is_one_on_one=True,
        attendee_count=2,
        duration_minutes=30,
        tags=["one-on-one"],
    )


class TestAIBriefer:
    """Tests for AIBriefer with mocked Anthropic API."""

    def test_parse_clean_json(self, config, sample_event):
        briefer = AIBriefer(config)

        response_json = json.dumps({
            "summary": "Weekly sync with Sarah about project updates.",
            "talking_points": [
                {"point": "Review sprint progress", "category": "update", "priority": "high"},
                {"point": "Discuss blockers", "category": "discussion", "priority": "medium"},
            ],
            "suggested_questions": [
                "How is the team feeling about the timeline?",
                "Any support needed from my side?",
            ],
            "context_notes": "Review last week's notes.",
            "preparation_time_minutes": 10,
        })

        brief = briefer._parse_response(response_json, sample_event)
        assert brief.summary == "Weekly sync with Sarah about project updates."
        assert len(brief.talking_points) == 2
        assert len(brief.suggested_questions) == 2
        assert brief.preparation_time_minutes == 10

    def test_parse_markdown_wrapped_json(self, config, sample_event):
        briefer = AIBriefer(config)

        response_text = """```json
{
    "summary": "A meeting brief.",
    "talking_points": [],
    "suggested_questions": ["Question 1"],
    "context_notes": "",
    "preparation_time_minutes": 5
}
```"""

        brief = briefer._parse_response(response_text, sample_event)
        assert brief.summary == "A meeting brief."
        assert len(brief.suggested_questions) == 1

    def test_parse_json_with_surrounding_text(self, config, sample_event):
        briefer = AIBriefer(config)

        response_text = """Here's the meeting brief:
{
    "summary": "Extracted from surrounding text.",
    "talking_points": [],
    "suggested_questions": [],
    "context_notes": "",
    "preparation_time_minutes": 5
}
Hope this helps!"""

        brief = briefer._parse_response(response_text, sample_event)
        assert brief.summary == "Extracted from surrounding text."

    def test_parse_unparseable_response(self, config, sample_event):
        briefer = AIBriefer(config)

        response_text = "This is not JSON at all, just a plain text response."
        brief = briefer._parse_response(response_text, sample_event)
        # Should fall back to using raw text as summary
        assert "This is not JSON" in brief.summary

    def test_fallback_brief(self, config, sample_event):
        briefer = AIBriefer(config)
        brief = briefer._fallback_brief(sample_event, "API timeout")

        assert "1:1 with Sarah" in brief.summary
        assert len(brief.talking_points) == 1
        assert "API timeout" in brief.context_notes

    def test_build_event_prompt_contains_details(self, config, sample_event):
        briefer = AIBriefer(config)
        prompt = briefer._build_event_prompt(sample_event)

        assert "1:1 with Sarah" in prompt
        assert "sarah@example.com" in prompt
        assert "10:00 AM" in prompt
        assert "30 minutes" in prompt
        assert "Weekly sync" in prompt
        assert "1:1" in prompt

    def test_category_prompts_exist_for_all_categories(self):
        for category in MeetingCategory:
            if category != MeetingCategory.OTHER:
                assert category in CATEGORY_PROMPTS

    @patch("src.ai_briefer.anthropic.Anthropic")
    def test_generate_brief_api_call(self, mock_anthropic_class, config, sample_event):
        # Mock the API response
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "summary": "Mocked response.",
            "talking_points": [],
            "suggested_questions": [],
            "context_notes": "",
            "preparation_time_minutes": 5,
        }))]
        mock_client.messages.create.return_value = mock_response

        briefer = AIBriefer(config)
        briefer.client = mock_client
        brief = briefer.generate_brief(sample_event)

        assert brief.summary == "Mocked response."
        mock_client.messages.create.assert_called_once()

    @patch("src.ai_briefer.anthropic.Anthropic")
    def test_generate_briefs_multiple(self, mock_anthropic_class, config, sample_event):
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "summary": "Brief",
            "talking_points": [],
            "suggested_questions": [],
            "context_notes": "",
            "preparation_time_minutes": 5,
        }))]
        mock_client.messages.create.return_value = mock_response

        briefer = AIBriefer(config)
        briefer.client = mock_client
        briefs = briefer.generate_briefs([sample_event, sample_event])

        assert len(briefs) == 2
        assert mock_client.messages.create.call_count == 2
