"""
Meeting notes storage and retrieval.

After a meeting, save notes (key takeaways, action items, decisions).
These notes are reused in future meeting prep when:
- The same recurring meeting comes up again
- A meeting with overlapping attendees is scheduled
- The user explicitly references past notes

Storage:
    meeting_notes.json - array of note entries with meeting metadata

No fluff -- notes should be concise and actionable. The system
encourages structured notes (decisions, action items, follow-ups)
over free-form rambling. Notes are reused automatically in future
prep for similar meetings (same title or overlapping attendees) and
can be searched/exported for manual reuse.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_NOTES_PATH = "./meeting_notes.json"


class MeetingNotesStore:
    """
    JSON-based storage for post-meeting notes.

    Notes are linked to meetings by title and attendees, so they can be
    automatically pulled into future prep briefs for similar meetings.

    Each note entry:
    {
        "id": "note-abc123",
        "meeting_title": "1:1 with Alex",
        "meeting_id": "manual-abc123" or "google-event-id",
        "date": "2026-02-14",
        "attendees": ["alex@company.com"],
        "content": "Discussed Q1 roadmap. Alex is blocked on...",
        "action_items": ["Follow up on API design doc", "Schedule review"],
        "decisions": ["Moving to weekly cadence"],
        "created_at": "2026-02-14T17:00:00"
    }
    """

    def __init__(self, store_path: str = DEFAULT_NOTES_PATH):
        self.store_path = Path(store_path)
        self._ensure_store_exists()

    def _ensure_store_exists(self) -> None:
        if not self.store_path.exists():
            self.store_path.write_text("[]")

    def _load(self) -> List[dict]:
        try:
            data = json.loads(self.store_path.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []

    def _save(self, notes: List[dict]) -> None:
        self.store_path.write_text(json.dumps(notes, indent=2, default=str))

    def add_note(
        self,
        meeting_title: str,
        content: str,
        meeting_id: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        action_items: Optional[List[str]] = None,
        decisions: Optional[List[str]] = None,
        date: Optional[str] = None,
    ) -> dict:
        """
        Save a meeting note.

        Args:
            meeting_title: Title of the meeting these notes are for
            content: The actual notes (key takeaways, discussion summary)
            meeting_id: Optional meeting ID for exact matching
            attendees: List of attendee emails/names
            action_items: List of action items from the meeting
            decisions: List of decisions made
            date: Date of the meeting (defaults to today)

        Returns:
            The created note dict
        """
        import uuid

        note = {
            "id": f"note-{str(uuid.uuid4())[:8]}",
            "meeting_title": meeting_title,
            "meeting_id": meeting_id or "",
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "attendees": attendees or [],
            "content": content.strip(),
            "action_items": action_items or [],
            "decisions": decisions or [],
            "created_at": datetime.now().isoformat(),
        }

        notes = self._load()
        notes.append(note)
        self._save(notes)

        logger.info("Saved note for: %s", meeting_title)
        return note

    def get_notes_for_meeting(self, meeting_id: str) -> List[dict]:
        """Get all notes for a specific meeting ID."""
        notes = self._load()
        return [n for n in notes if n.get("meeting_id") == meeting_id]

    def get_relevant_notes(
        self,
        title: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[dict]:
        """
        Find relevant past notes based on meeting title similarity and attendee overlap.

        Matching logic:
        1. Exact title match (strongest signal - recurring meetings)
        2. Attendee overlap (same people = likely related context)
        3. Title word overlap (similar topic)

        Args:
            title: Current meeting title to match against
            attendees: Current meeting attendees to match against
            limit: Max number of notes to return

        Returns:
            List of relevant notes, most relevant first
        """
        notes = self._load()
        if not notes:
            return []

        scored = []
        title_words = set((title or "").lower().split()) - {"with", "and", "the", "for", "a", "an"}
        attendees_set = set(a.lower() for a in (attendees or []))

        for note in notes:
            score = 0

            # Exact title match (recurring meetings)
            note_title = note.get("meeting_title", "").lower()
            if title and note_title == title.lower():
                score += 10

            # Title word overlap
            note_words = set(note_title.split()) - {"with", "and", "the", "for", "a", "an"}
            if title_words and note_words:
                overlap = len(title_words & note_words)
                score += overlap * 2

            # Attendee overlap
            note_attendees = set(a.lower() for a in note.get("attendees", []))
            if attendees_set and note_attendees:
                attendee_overlap = len(attendees_set & note_attendees)
                score += attendee_overlap * 3

            if score > 0:
                scored.append((score, note))

        # Sort by score descending, then by date descending (most recent first)
        scored.sort(key=lambda x: (x[0], x[1].get("date", "")), reverse=True)

        return [note for _, note in scored[:limit]]

    def get_all_notes(self) -> List[dict]:
        """Get all stored notes."""
        return self._load()

    def get_open_action_items(self) -> List[Dict[str, Any]]:
        """
        Get all action items across all notes.

        Returns a flat list of action items with their meeting context.
        """
        notes = self._load()
        items = []
        for note in notes:
            for item in note.get("action_items", []):
                items.append({
                    "action": item,
                    "meeting": note.get("meeting_title", ""),
                    "date": note.get("date", ""),
                    "note_id": note.get("id", ""),
                })
        return items

    def remove_note(self, note_id: str) -> bool:
        """Remove a note by its ID."""
        notes = self._load()
        original = len(notes)
        notes = [n for n in notes if n.get("id") != note_id]
        if len(notes) < original:
            self._save(notes)
            return True
        return False

    def search_notes(self, query: str) -> List[dict]:
        """Search notes by keyword in title or content."""
        query_lower = query.lower()
        notes = self._load()
        results = []
        for note in notes:
            title = note.get("meeting_title", "").lower()
            content = note.get("content", "").lower()
            if query_lower in title or query_lower in content:
                results.append(note)
        return results
