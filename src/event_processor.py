"""
Event processing pipeline: filter, deduplicate, classify, and score events.

This module contains the business logic that decides which meetings matter
and how much preparation each one needs. It has NO external API calls -
everything is pure Python logic, making it highly testable.

Pipeline:
    raw CalendarEvents
      -> filter (remove noise)
      -> deduplicate (merge cross-calendar dupes)
      -> classify (what type of meeting?)
      -> score priority (how important is it?)
      -> sort (highest priority first)
"""

import re
import logging
from typing import List
from src.models import (
    CalendarEvent,
    ProcessedEvent,
    EventPriority,
    MeetingCategory,
)
from src.config import FilterConfig

logger = logging.getLogger(__name__)


class EventProcessor:
    """Filters, deduplicates, classifies, and prioritizes calendar events."""

    def __init__(self, config: FilterConfig):
        self.config = config
        # Pre-compile regex patterns for performance
        self._exclude_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in config.exclude_patterns
        ]

    def process(self, events: List[CalendarEvent]) -> List[ProcessedEvent]:
        """
        Run the full processing pipeline.

        Args:
            events: Raw calendar events from the API

        Returns:
            Processed events, sorted by priority (highest first)
        """
        logger.info(f"Processing {len(events)} raw events")

        # Step 1: Filter out noise
        filtered = self.filter_events(events)
        logger.info(f"After filtering: {len(filtered)} events")

        # Step 2: Remove duplicates across calendars
        deduped = self.deduplicate(filtered)
        logger.info(f"After dedup: {len(deduped)} events")

        # Step 3: Enrich with computed fields + classify + score
        processed = []
        for event in deduped:
            enriched = self._enrich_event(event)
            classified = self._classify_event(enriched)
            scored = self._score_priority(classified)
            processed.append(scored)

        # Step 4: Sort by priority score (highest first)
        processed.sort(key=lambda e: e.priority_score, reverse=True)

        logger.info(
            f"Final: {len(processed)} events "
            f"(HIGH: {sum(1 for e in processed if e.priority == EventPriority.HIGH)}, "
            f"MED: {sum(1 for e in processed if e.priority == EventPriority.MEDIUM)}, "
            f"LOW: {sum(1 for e in processed if e.priority == EventPriority.LOW)})"
        )

        return processed

    # ── Filter ─────────────────────────────────────────────────

    def filter_events(self, events: List[CalendarEvent]) -> List[CalendarEvent]:
        """
        Remove events that don't need preparation.

        Filters applied:
        1. All-day events (holidays, OOO markers)
        2. Events shorter than min_duration_minutes
        3. Events with too few attendees
        4. Events whose title matches exclude_patterns
        """
        filtered = []

        for event in events:
            # Skip all-day events
            if self.config.exclude_all_day and event.is_all_day:
                logger.debug(f"Filtered (all-day): {event.title}")
                continue

            # Skip very short events
            duration = self._calc_duration(event)
            if duration < self.config.min_duration_minutes:
                logger.debug(f"Filtered (too short: {duration}min): {event.title}")
                continue

            # Skip events with too few attendees
            if len(event.attendees) < self.config.min_attendees:
                logger.debug(f"Filtered (too few attendees): {event.title}")
                continue

            # Skip events matching exclude patterns
            if self._matches_exclude_pattern(event.title):
                logger.debug(f"Filtered (pattern match): {event.title}")
                continue

            filtered.append(event)

        return filtered

    def _matches_exclude_pattern(self, title: str) -> bool:
        """Check if event title matches any exclude pattern."""
        for pattern in self._exclude_patterns:
            if pattern.search(title):
                return True
        return False

    def _calc_duration(self, event: CalendarEvent) -> int:
        """Calculate event duration in minutes."""
        delta = event.end_time - event.start_time
        return int(delta.total_seconds() / 60)

    # ── Deduplicate ────────────────────────────────────────────

    def deduplicate(self, events: List[CalendarEvent]) -> List[CalendarEvent]:
        """
        Remove duplicate events that appear across multiple calendars.

        Dedup strategy: Two events are duplicates if they have:
        - Same title (case-insensitive, whitespace-normalized)
        - Start times within 5 minutes of each other

        When duplicates found, keep the one with the most detail
        (longest description).
        """
        if not events:
            return []

        seen = {}  # key -> CalendarEvent (best version)

        for event in events:
            key = self._dedup_key(event)

            if key in seen:
                existing = seen[key]
                # Keep the version with more detail
                existing_desc_len = len(existing.description or "")
                new_desc_len = len(event.description or "")
                if new_desc_len > existing_desc_len:
                    seen[key] = event
                    logger.debug(f"Dedup: replaced with more detailed version: {event.title}")
                else:
                    logger.debug(f"Dedup: skipped duplicate: {event.title}")
            else:
                seen[key] = event

        return list(seen.values())

    def _dedup_key(self, event: CalendarEvent) -> str:
        """
        Generate a deduplication key for an event.

        Normalizes the title and rounds start time to nearest 5 minutes
        to catch near-duplicates.
        """
        # Normalize title: lowercase, strip, collapse whitespace
        normalized_title = re.sub(r"\s+", " ", event.title.lower().strip())

        # Round start time to nearest 5 minutes
        start = event.start_time
        rounded_minute = (start.minute // 5) * 5
        rounded_start = start.replace(minute=rounded_minute, second=0, microsecond=0)

        return f"{normalized_title}|{rounded_start.isoformat()}"

    # ── Enrich ─────────────────────────────────────────────────

    def _enrich_event(self, event: CalendarEvent) -> ProcessedEvent:
        """
        Add computed fields to an event.

        Computes:
        - attendee_count
        - duration_minutes
        - is_one_on_one (exactly 2 people including organizer)
        - tags (inferred from title keywords)
        """
        duration = self._calc_duration(event)
        attendee_count = len(event.attendees)

        # A 1:1 is when there are exactly 2 attendees (you + 1 other)
        is_one_on_one = attendee_count == 2

        # Infer tags from title
        tags = self._infer_tags(event.title)

        return ProcessedEvent(
            event=event,
            attendee_count=attendee_count,
            duration_minutes=duration,
            is_one_on_one=is_one_on_one,
            tags=tags,
        )

    def _infer_tags(self, title: str) -> List[str]:
        """
        Infer meeting tags from the title using keyword matching.

        Examples:
          "Weekly Team Standup" -> ["standup", "recurring"]
          "1:1 with Sarah"     -> ["one-on-one"]
          "Client Review"      -> ["client", "review"]
        """
        title_lower = title.lower()
        tags = []

        tag_keywords = {
            "standup": ["standup", "stand-up", "daily sync", "daily scrum"],
            "one-on-one": ["1:1", "1-1", "one on one", "1on1"],
            "review": ["review", "feedback", "retro", "retrospective"],
            "planning": ["planning", "sprint", "roadmap", "strategy"],
            "interview": ["interview", "screening", "hiring"],
            "client": ["client", "customer", "external", "vendor"],
            "all-hands": ["all-hands", "all hands", "town hall", "company meeting"],
            "networking": ["networking", "coffee chat", "meet & greet", "intro"],
            "workshop": ["workshop", "training", "onboarding"],
        }

        for tag, keywords in tag_keywords.items():
            if any(kw in title_lower for kw in keywords):
                tags.append(tag)

        return tags

    # ── Classify ───────────────────────────────────────────────

    def _classify_event(self, event: ProcessedEvent) -> ProcessedEvent:
        """
        Classify the meeting type based on tags and attendee count.

        Classification rules (in priority order):
        1. Tags contain "interview" -> INTERVIEW
        2. Tags contain "standup" -> STANDUP
        3. Tags contain "all-hands" -> ALL_HANDS
        4. Tags contain "client" -> CLIENT
        5. Tags contain "networking" -> NETWORKING
        6. is_one_on_one -> ONE_ON_ONE
        7. attendee_count >= 3 -> TEAM
        8. Default -> OTHER
        """
        tags = event.tags

        if "interview" in tags:
            category = MeetingCategory.INTERVIEW
        elif "standup" in tags:
            category = MeetingCategory.STANDUP
        elif "all-hands" in tags:
            category = MeetingCategory.ALL_HANDS
        elif "client" in tags:
            category = MeetingCategory.CLIENT
        elif "networking" in tags:
            category = MeetingCategory.NETWORKING
        elif event.is_one_on_one:
            category = MeetingCategory.ONE_ON_ONE
        elif event.attendee_count >= 3:
            category = MeetingCategory.TEAM
        else:
            category = MeetingCategory.OTHER

        event.category = category
        return event

    # ── Priority Scoring ───────────────────────────────────────

    def _score_priority(self, event: ProcessedEvent) -> ProcessedEvent:
        """
        Calculate a priority score (0.0 to 1.0) for an event.

        Scoring factors (weights sum to ~1.0):
        - Category weight:        0.30  (interviews > 1:1 > client > team > standup)
        - Attendee count:         0.20  (more people = higher stakes)
        - Duration:               0.15  (longer = more important)
        - Has external attendees: 0.15  (cross-company = higher stakes)
        - Is non-recurring:       0.10  (one-offs need more prep)
        - Has description:        0.10  (agenda provided = worth preparing)
        """
        score = 0.0

        # Category weight (0.30)
        category_scores = {
            MeetingCategory.INTERVIEW: 1.0,
            MeetingCategory.CLIENT: 0.9,
            MeetingCategory.ONE_ON_ONE: 0.7,
            MeetingCategory.NETWORKING: 0.7,
            MeetingCategory.TEAM: 0.5,
            MeetingCategory.ALL_HANDS: 0.3,
            MeetingCategory.STANDUP: 0.2,
            MeetingCategory.OTHER: 0.4,
        }
        score += 0.30 * category_scores.get(event.category, 0.4)

        # Attendee count (0.20) - caps at 10 attendees
        attendee_factor = min(event.attendee_count / 10.0, 1.0)
        score += 0.20 * attendee_factor

        # Duration (0.15) - caps at 60 minutes
        duration_factor = min(event.duration_minutes / 60.0, 1.0)
        score += 0.15 * duration_factor

        # Has external attendees (0.15)
        # Heuristic: if any attendee email domain differs from organizer domain
        if event.event.organizer and event.event.attendees:
            org_domain = event.event.organizer.split("@")[-1] if "@" in event.event.organizer else ""
            has_external = any(
                "@" in a and a.split("@")[-1] != org_domain
                for a in event.event.attendees
            )
            if has_external:
                score += 0.15

        # Is non-recurring (0.10)
        if not event.event.is_recurring:
            score += 0.10

        # Has description/agenda (0.10)
        if event.event.description and len(event.event.description) > 20:
            score += 0.10

        # Clamp to [0, 1]
        score = max(0.0, min(1.0, score))

        # Map score to priority level
        if score >= 0.6:
            priority = EventPriority.HIGH
        elif score >= 0.35:
            priority = EventPriority.MEDIUM
        else:
            priority = EventPriority.LOW

        event.priority = priority
        event.priority_score = round(score, 3)

        return event
