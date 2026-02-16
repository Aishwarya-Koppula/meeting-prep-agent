"""
Data models for the Meeting Prep Agent.

These Pydantic models define the shape of data flowing through the pipeline:
  CalendarEvent (raw from API)
    -> ProcessedEvent (filtered, enriched)
      -> PrepBrief (AI-generated prep)
        -> DailyDigest (collection of all briefs for the day)

Why Pydantic?
- Automatic type validation (catches bugs early)
- .model_dump() / .model_dump_json() for serialization
- Field defaults and Optional fields handled cleanly
- Works great with FastAPI if we add a web UI later
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────

class EventPriority(str, Enum):
    """Priority level for a meeting. Determines how detailed the prep brief is."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MeetingCategory(str, Enum):
    """Classification of meeting type. Different categories get different prompts."""
    ONE_ON_ONE = "1:1"
    TEAM = "team"
    CLIENT = "client"
    INTERVIEW = "interview"
    NETWORKING = "networking"
    STANDUP = "standup"
    ALL_HANDS = "all-hands"
    OFFICE_HOURS = "office-hours"
    CLASS = "class"
    PART_TIME = "part-time"
    CLUB = "club"
    CAREER_FAIR = "career-fair"
    OTHER = "other"


# ── Calendar Event (raw from API) ─────────────────────────────

class CalendarEvent(BaseModel):
    """
    A raw event fetched from the Google Calendar API.

    This is the first data structure in the pipeline. The calendar_client
    module parses the Google API JSON response into this model.

    Example Google API response fields -> our fields:
      event['id']                    -> event_id
      event['summary']              -> title
      event['start']['dateTime']    -> start_time
      event['end']['dateTime']      -> end_time
      event.get('description', '')  -> description
      event.get('location', '')     -> location
      [a['email'] for a in event.get('attendees', [])] -> attendees
    """
    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: List[str] = Field(default_factory=list)
    organizer: Optional[str] = None
    is_recurring: bool = False
    is_all_day: bool = False
    meeting_link: Optional[str] = None
    calendar_id: str = "primary"
    source: str = "google_calendar"

    @classmethod
    def from_google_api(cls, raw_event: dict, calendar_id: str = "primary") -> "CalendarEvent":
        """
        Parse a Google Calendar API event dict into a CalendarEvent.

        Google Calendar API returns events in this format:
        {
            "id": "abc123",
            "summary": "Team Standup",
            "start": {"dateTime": "2026-02-14T10:00:00-05:00"},  # or {"date": "2026-02-14"} for all-day
            "end": {"dateTime": "2026-02-14T10:30:00-05:00"},
            "description": "Daily sync",
            "location": "Conference Room A",
            "attendees": [{"email": "alice@co.com", "responseStatus": "accepted"}],
            "organizer": {"email": "bob@co.com"},
            "recurringEventId": "def456",  # present if recurring
            "hangoutLink": "https://meet.google.com/...",
            "conferenceData": {"entryPoints": [{"uri": "https://..."}]}
        }
        """
        # Determine if all-day event (uses 'date' instead of 'dateTime')
        is_all_day = "date" in raw_event.get("start", {})

        if is_all_day:
            start_str = raw_event["start"]["date"]
            end_str = raw_event["end"]["date"]
            start_time = datetime.fromisoformat(start_str)
            end_time = datetime.fromisoformat(end_str)
        else:
            start_str = raw_event["start"]["dateTime"]
            end_str = raw_event["end"]["dateTime"]
            start_time = datetime.fromisoformat(start_str)
            end_time = datetime.fromisoformat(end_str)

        # Extract attendee emails
        attendees = [
            a.get("email", "")
            for a in raw_event.get("attendees", [])
            if a.get("email")
        ]

        # Extract meeting link (try hangoutLink first, then conferenceData)
        meeting_link = raw_event.get("hangoutLink")
        if not meeting_link:
            conference_data = raw_event.get("conferenceData", {})
            entry_points = conference_data.get("entryPoints", [])
            for ep in entry_points:
                if ep.get("entryPointType") == "video":
                    meeting_link = ep.get("uri")
                    break

        return cls(
            event_id=raw_event["id"],
            title=raw_event.get("summary", "(No Title)"),
            start_time=start_time,
            end_time=end_time,
            description=raw_event.get("description"),
            location=raw_event.get("location"),
            attendees=attendees,
            organizer=raw_event.get("organizer", {}).get("email"),
            is_recurring=raw_event.get("recurringEventId") is not None,
            is_all_day=is_all_day,
            meeting_link=meeting_link,
            calendar_id=calendar_id,
        )


# ── Processed Event (after filtering & enrichment) ────────────

class ProcessedEvent(BaseModel):
    """
    An event after filtering, deduplication, and priority scoring.

    The event_processor module takes raw CalendarEvents and produces these.
    Added fields: priority, category, duration, attendee count, tags.
    """
    event: CalendarEvent
    priority: EventPriority = EventPriority.MEDIUM
    priority_score: float = Field(default=0.0, ge=0.0, le=1.0)
    category: MeetingCategory = MeetingCategory.OTHER
    is_one_on_one: bool = False
    attendee_count: int = 0
    duration_minutes: int = 0
    tags: List[str] = Field(default_factory=list)


# ── AI-Generated Prep Brief ───────────────────────────────────

class TalkingPoint(BaseModel):
    """A single talking point for a meeting, with category and priority."""
    point: str
    category: str = "discussion"  # question, discussion, update, follow-up
    priority: str = "medium"       # high, medium, low


class PrepBrief(BaseModel):
    """
    AI-generated preparation brief for a single meeting.

    This is what Claude produces for each event. It contains everything
    the user needs to walk into the meeting prepared.
    """
    event: ProcessedEvent
    summary: str = ""
    talking_points: List[TalkingPoint] = Field(default_factory=list)
    suggested_questions: List[str] = Field(default_factory=list)
    context_notes: str = ""
    preparation_time_minutes: int = 5
    generated_at: datetime = Field(default_factory=datetime.now)


# ── Daily Digest (the final output) ───────────────────────────

class DailyDigest(BaseModel):
    """
    The complete morning digest containing all prep briefs for the day.

    This is what gets rendered into the HTML email template and sent
    to the user every morning.
    """
    date: datetime
    briefs: List[PrepBrief] = Field(default_factory=list)
    total_meetings: int = 0
    total_meeting_hours: float = 0.0
    high_priority_count: int = 0
    generated_at: datetime = Field(default_factory=datetime.now)

    def to_email_context(self) -> dict:
        """Convert digest to a dict suitable for Jinja2 template rendering."""
        return {
            "date": self.date.strftime("%A, %B %d, %Y"),
            "briefs": self.briefs,
            "total_meetings": self.total_meetings,
            "total_hours": f"{self.total_meeting_hours:.1f}",
            "high_priority_count": self.high_priority_count,
            "generated_at": self.generated_at.strftime("%I:%M %p"),
        }
