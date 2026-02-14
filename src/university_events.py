"""
University events discovery via Localist API.

Many universities use the Localist platform (events.purdue.edu, etc.) to
publish campus events. This module fetches upcoming events, displays them
interactively, and lets the user pick which ones to add to their personal
meeting store for AI prep.

Supported universities (Localist-powered):
    - Purdue University: events.purdue.edu
    - Many others use the same platform (easy to extend)

Localist API:
    - Public JSON API, no auth required, free unlimited access
    - Endpoint: /api/2/events?days=N&pp=N
    - Returns: title, date, time, location, description, category, URL

Usage:
    client = UniversityEventsClient(config)
    events = client.fetch_upcoming_events(days=7)
    # User picks events interactively
    # Selected events are saved to MeetingStore
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import requests

from src.meeting_store import MeetingStore

logger = logging.getLogger(__name__)

# Pre-configured university Localist endpoints
UNIVERSITY_ENDPOINTS = {
    "purdue": {
        "name": "Purdue University",
        "base_url": "https://events.purdue.edu",
        "api_path": "/api/2/events",
    },
}


class UniversityEventsClient:
    """
    Fetches and displays university events from Localist-powered event pages.

    Usage:
        client = UniversityEventsClient("purdue")
        events = client.fetch_upcoming_events(days=7)
        client.display_and_pick(events)  # interactive selection
    """

    def __init__(self, university: str = "purdue"):
        """
        Args:
            university: University key from UNIVERSITY_ENDPOINTS
        """
        if university not in UNIVERSITY_ENDPOINTS:
            raise ValueError(
                f"Unknown university: '{university}'. "
                f"Available: {', '.join(UNIVERSITY_ENDPOINTS.keys())}"
            )
        self.uni = UNIVERSITY_ENDPOINTS[university]
        self.university = university

    def fetch_upcoming_events(
        self, days: int = 7, max_events: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Fetch upcoming events from the university events page.

        Args:
            days: How many days ahead to look (default: 7)
            max_events: Maximum events to return (default: 30)

        Returns:
            List of parsed event dicts with: title, start, end, location,
            description, url, category, event_type
        """
        api_url = f"{self.uni['base_url']}{self.uni['api_path']}"

        try:
            resp = requests.get(
                api_url,
                params={
                    "days": days,
                    "pp": max_events,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("Failed to fetch %s events: %s", self.uni["name"], e)
            return []
        except ValueError as e:
            logger.error("Invalid JSON from %s: %s", self.uni["name"], e)
            return []

        events = []
        for raw in data.get("events", []):
            event_data = raw.get("event", raw)
            parsed = self._parse_event(event_data)
            if parsed:
                events.append(parsed)

        logger.info("Fetched %d events from %s", len(events), self.uni["name"])
        return events

    def _parse_event(self, raw: dict) -> Optional[Dict[str, Any]]:
        """Parse a single Localist API event into a clean dict."""
        try:
            title = raw.get("title", "").strip()
            if not title:
                return None

            # Get the first event instance for timing
            instances = raw.get("event_instances", [])
            if instances:
                instance = instances[0].get("event_instance", instances[0])
                start_str = instance.get("start")
                end_str = instance.get("end")
                is_all_day = instance.get("all_day", False)
            else:
                start_str = raw.get("first_date")
                end_str = raw.get("last_date")
                is_all_day = True

            # Parse times
            start_time = self._parse_time(start_str) if start_str else None
            end_time = self._parse_time(end_str) if end_str else None

            if not start_time:
                return None

            # Description: strip HTML tags for clean text
            description = raw.get("description_text", "") or ""
            description = description.strip()
            # Truncate long descriptions
            if len(description) > 300:
                description = description[:297] + "..."

            # Location
            location = raw.get("location_name") or raw.get("location") or ""

            # Categories
            filters = raw.get("filters", {})
            event_types = []
            for et in filters.get("event_types", []):
                if isinstance(et, dict):
                    event_types.append(et.get("name", ""))
                elif isinstance(et, str):
                    event_types.append(et)

            # URL
            url = raw.get("localist_url", "")

            # Experience type
            experience = raw.get("experience", "inperson")

            return {
                "id": str(raw.get("id", "")),
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "is_all_day": is_all_day,
                "location": location,
                "description": description,
                "url": url,
                "event_types": event_types,
                "experience": experience,
                "source": f"university_{self.university}",
            }

        except Exception as e:
            logger.warning("Failed to parse university event: %s", e)
            return None

    @staticmethod
    def _parse_time(time_str: str) -> Optional[datetime]:
        """Parse various time formats from Localist API."""
        if not time_str:
            return None

        # Try ISO format first
        try:
            # Handle Z suffix
            clean = time_str.replace("Z", "+00:00")
            return datetime.fromisoformat(clean)
        except ValueError:
            pass

        # Try common formats
        for fmt in [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S %z",
            "%Y-%m-%d",
        ]:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        return None

    def display_events(self, events: List[Dict[str, Any]]) -> None:
        """Display events in a numbered list for the user to browse."""
        if not events:
            print(f"\nNo upcoming events found at {self.uni['name']}.\n")
            return

        print(f"\n{'=' * 60}")
        print(f"  Upcoming Events - {self.uni['name']}")
        print(f"{'=' * 60}\n")

        for i, event in enumerate(events, 1):
            start = event["start_time"]
            time_str = start.strftime("%b %d, %a  %I:%M %p") if start else "TBD"
            is_all_day = event.get("is_all_day", False)
            if is_all_day and start:
                time_str = start.strftime("%b %d, %a") + "  (all day)"

            types = ", ".join(event.get("event_types", [])) or "Event"
            location = event.get("location", "")
            experience = event.get("experience", "")
            loc_str = f" | {location}" if location else ""
            virtual_tag = " [Virtual]" if experience == "virtual" else ""

            print(f"  {i:>2}. {event['title']}{virtual_tag}")
            print(f"      {time_str}{loc_str}")
            print(f"      [{types}]")

            # Show brief description if available
            desc = event.get("description", "")
            if desc:
                # Show first sentence or first 120 chars
                short_desc = desc.split(".")[0]
                if len(short_desc) > 120:
                    short_desc = short_desc[:117] + "..."
                print(f"      {short_desc}")
            print()

    def pick_and_save(
        self, events: List[Dict[str, Any]], store: Optional[MeetingStore] = None
    ) -> int:
        """
        Interactive: let user pick events to add to their calendar.

        Shows the event list, asks the user to enter numbers of events
        they're interested in, and saves selected ones to the MeetingStore.

        Args:
            events: List of parsed events from fetch_upcoming_events()
            store: MeetingStore instance (creates default if None)

        Returns:
            Number of events added
        """
        if not events:
            return 0

        if store is None:
            store = MeetingStore()

        self.display_events(events)

        print("  Enter the numbers of events you're interested in")
        print("  (comma-separated, e.g. '1,3,5' or 'all' or 'none')\n")
        selection = input("  Your picks: ").strip().lower()

        if selection in ("none", "n", ""):
            print("\n  No events added.\n")
            return 0

        if selection == "all":
            selected_indices = list(range(len(events)))
        else:
            try:
                selected_indices = [
                    int(s.strip()) - 1
                    for s in selection.split(",")
                    if s.strip().isdigit()
                ]
                # Filter out of range
                selected_indices = [i for i in selected_indices if 0 <= i < len(events)]
            except ValueError:
                print("\n  Invalid input. No events added.\n")
                return 0

        if not selected_indices:
            print("\n  No valid selections. No events added.\n")
            return 0

        added = 0
        print()
        for idx in selected_indices:
            event = events[idx]
            start = event["start_time"]
            end = event["end_time"]

            if not start:
                continue

            # If no end time, default to start + 1 hour
            if not end:
                from datetime import timedelta
                end = start + timedelta(hours=1)

            # Ask for a quick personal note about why they're interested
            print(f"  >> {event['title']}")
            note = input("     Quick note - why are you going? (Enter to skip): ").strip()

            # Combine API description with personal note
            full_description = ""
            if event.get("description"):
                full_description = event["description"]
            if note:
                if full_description:
                    full_description += f"\n\nPersonal note: {note}"
                else:
                    full_description = note

            store.add_meeting(
                title=event["title"],
                start_time=start,
                end_time=end,
                description=full_description or None,
                location=event.get("location") or None,
                meeting_link=event.get("url") or None,
            )
            added += 1
            print(f"     Added!\n")

        print(f"  {added} event(s) added to your calendar.")
        print("  They'll appear in your next prep brief.\n")
        return added
