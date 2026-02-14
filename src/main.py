"""
Main entry point for the AI Meeting Prep Agent.

This module ties everything together into a pipeline:
    1. Fetch calendar events (Google Calendar API + manual meetings)
    2. Process events (filter, dedup, prioritize)
    3. Generate AI prep briefs (Claude API)
    4. Assemble daily digest
    5. Send email notification

CLI Usage:
    # Run once immediately (sends email)
    python -m src.main --run

    # Run once without sending email (preview mode)
    python -m src.main --dry-run

    # Start the scheduler (runs daily at configured time)
    python -m src.main --schedule

    # Add a meeting manually (interactive prompts)
    python -m src.main --add-meeting

    # List upcoming manual meetings
    python -m src.main --list-meetings

    # Remove a manual meeting by ID
    python -m src.main --remove-meeting <id>

    # Use a custom config file
    python -m src.main --run --config my_config.yaml

    # Verbose logging (shows debug messages)
    python -m src.main --run --verbose
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from src.config import load_config, AppConfig
from src.calendar_client import GoogleCalendarClient
from src.outlook_client import OutlookCalendarClient
from src.event_processor import EventProcessor
from src.ai_briefer import AIBriefer
from src.email_sender import EmailSender
from src.scheduler import MeetingPrepScheduler
from src.meeting_store import MeetingStore
from src.university_events import UniversityEventsClient, UNIVERSITY_ENDPOINTS
from src.reference_docs import ReferenceDocsStore
from src.meeting_notes import MeetingNotesStore
from src.ical_client import fetch_all_ical_events, load_ical_sources, save_ical_sources
from src.models import DailyDigest, EventPriority

logger = logging.getLogger(__name__)


def run_pipeline(
    config: AppConfig,
    dry_run: bool = False,
    log_collector: Optional[List[str]] = None,
) -> Optional[Tuple["DailyDigest", bool]]:
    """
    Execute the full meeting prep pipeline.

    Returns:
        (digest, email_sent) if pipeline completed, or (None, False) on early exit.
        If log_collector is provided, log lines are appended to it instead of printed.
    """
    def out(msg: str) -> None:
        if log_collector is not None:
            log_collector.append(msg)
        else:
            print(msg)

    out("\n" + "=" * 60)
    out("  AI Meeting Prep Agent - Running Pipeline")
    out("=" * 60 + "\n")

    # ── Step 1: Fetch calendar events ──────────────────────────
    out("[1/5] Fetching calendar events...")
    raw_events = []

    # 1a: Google Calendar events
    if config.google.enabled:
        try:
            calendar_client = GoogleCalendarClient(config.google)
            calendar_client.authenticate()
            google_events = calendar_client.fetch_todays_events()
            raw_events.extend(google_events)
            out(f"  -> Found {len(google_events)} events from Google Calendar")
        except FileNotFoundError as e:
            out(f"  WARN: Google Calendar not configured ({e})")
        except Exception as e:
            out(f"  WARN: Could not fetch Google Calendar events: {e}")

    # 1b: Outlook Calendar + Teams events
    if config.outlook.enabled:
        try:
            outlook_client = OutlookCalendarClient(config.outlook)
            outlook_client.authenticate()
            outlook_events = outlook_client.fetch_todays_events()
            teams_count = sum(1 for e in outlook_events if e.source == "outlook_teams")
            outlook_only = len(outlook_events) - teams_count
            raw_events.extend(outlook_events)
            out(f"  -> Found {outlook_only} events from Outlook Calendar")
            if teams_count:
                out(f"  -> Found {teams_count} Teams meetings")
        except Exception as e:
            out(f"  WARN: Could not fetch Outlook/Teams events: {e}")

    # 1c: Manual meetings from local store
    store = MeetingStore()
    manual_meetings = store.to_calendar_events()
    if manual_meetings:
        raw_events.extend(manual_meetings)
        out(f"  -> Found {len(manual_meetings)} manually added meetings")

    # 1d: iCal / UniTime subscriptions (university timetables, etc.)
    if config.ical.enabled:
        try:
            ical_events = fetch_all_ical_events(
                lookahead_hours=config.ical.lookahead_hours,
                sources_path=config.ical.sources_path,
            )
            if ical_events:
                raw_events.extend(ical_events)
                out(f"  -> Found {len(ical_events)} events from iCal / UniTime")
        except Exception as e:
            out(f"  WARN: Could not fetch iCal subscriptions: {e}")

    if not raw_events:
        out("  -> No event sources returned data.")
        out("  Configure Google Calendar, Outlook, or use --add-meeting.")

    out(f"  -> Total: {len(raw_events)} raw events")

    # ── Step 2: Process events ─────────────────────────────────
    out("\n[2/5] Processing events (filter, dedup, prioritize)...")
    processor = EventProcessor(config.filters)
    processed_events = processor.process(raw_events)
    out(f"  -> {len(processed_events)} events after processing")

    if not processed_events:
        out("\n  No meetings need preparation today!")
        if not dry_run:
            digest = DailyDigest(
                date=datetime.now(),
                total_meetings=0,
                total_meeting_hours=0.0,
            )
            sender = EmailSender(config.email)
            ok = sender.send_digest(digest)
            out("  Sent 'no meetings' notification." if ok else "  Failed to send email.")
            return (digest, ok)
        return (None, False)

    # Show processed events summary
    for event in processed_events:
        priority_icon = {"high": "!!!", "medium": " ! ", "low": "   "}
        icon = priority_icon.get(event.priority.value, "   ")
        source_tag = f" [{event.event.source}]" if event.event.source != "google_calendar" else ""
        out(
            f"  [{icon}] {event.event.start_time.strftime('%I:%M %p')} "
            f"- {event.event.title} "
            f"({event.category.value}, {event.duration_minutes}min){source_tag}"
        )

    # ── Step 3: Generate AI briefs ─────────────────────────────
    out(f"\n[3/5] Generating AI prep briefs for {len(processed_events)} events...")
    briefer = AIBriefer(config.anthropic)

    # Inject reference docs and past notes for better context
    ref_docs_store = ReferenceDocsStore()
    notes_store = MeetingNotesStore()
    briefer.set_reference_docs_store(ref_docs_store)
    briefer.set_notes_store(notes_store)

    briefs = briefer.generate_briefs(processed_events)
    out(f"  -> Generated {len(briefs)} briefs")

    # ── Step 4: Assemble digest ────────────────────────────────
    out("\n[4/5] Assembling daily digest...")
    digest = DailyDigest(
        date=datetime.now(),
        briefs=briefs,
        total_meetings=len(briefs),
        total_meeting_hours=sum(b.event.duration_minutes for b in briefs) / 60.0,
        high_priority_count=sum(
            1 for b in briefs if b.event.priority == EventPriority.HIGH
        ),
    )
    out(f"  -> {digest.total_meetings} meetings, {digest.total_meeting_hours:.1f} hours total")

    # ── Step 5: Send or preview ────────────────────────────────
    email_sent = False
    if dry_run:
        out("\n[5/5] DRY RUN - Previewing digest (no email sent)")
        out("\n" + "-" * 60)
        for line in _digest_preview_lines(digest):
            out(line)
        out("-" * 60)
        output_file = "digest_preview.json"
        with open(output_file, "w") as f:
            json.dump(digest.model_dump(mode="json"), f, indent=2, default=str)
        out(f"\n  Full digest saved to: {output_file}")
    else:
        out("\n[5/5] Sending digest email...")
        sender = EmailSender(config.email)
        email_sent = sender.send_digest(digest)
        if email_sent:
            out(f"  -> Email sent to {config.email.recipient}")
        else:
            out("  -> ERROR: Failed to send email. Check logs for details.")

    out("\n" + "=" * 60)
    out("  Pipeline complete!")
    out("=" * 60 + "\n")
    return (digest, email_sent)


def _digest_preview_lines(digest: DailyDigest) -> List[str]:
    """Return digest preview as a list of lines (for CLI or web)."""
    lines = []
    lines.append(f"\nMeeting Prep Brief - {digest.date.strftime('%A, %B %d, %Y')}")
    lines.append(f"Total: {digest.total_meetings} meetings, {digest.total_meeting_hours:.1f} hours\n")
    for i, brief in enumerate(digest.briefs, 1):
        event = brief.event.event
        priority = brief.event.priority.value.upper()
        lines.append(f"--- [{priority}] Meeting {i}: {event.title} ---")
        lines.append(f"Time: {event.start_time.strftime('%I:%M %p')} - {event.end_time.strftime('%I:%M %p')}")
        lines.append(f"Category: {brief.event.category.value}")
        if event.attendees:
            lines.append(f"Attendees: {', '.join(event.attendees[:5])}")
        lines.append(f"\nSummary: {brief.summary}")
        if brief.talking_points:
            lines.append("\nTalking Points:")
            for tp in brief.talking_points:
                lines.append(f"  [{tp.category}] {tp.point}")
        if brief.suggested_questions:
            lines.append("\nQuestions to Ask:")
            for q in brief.suggested_questions:
                lines.append(f'  - "{q}"')
        if brief.context_notes:
            lines.append(f"\nPrep: {brief.context_notes}")
        lines.append("")
    return lines


def _print_digest_preview(digest: DailyDigest) -> None:
    """Print a text preview of the digest to the console."""
    for line in _digest_preview_lines(digest):
        print(line)


def _add_meeting_interactive() -> None:
    """Interactive CLI flow to add a new meeting."""
    store = MeetingStore()

    print("\n" + "=" * 60)
    print("  Add a New Meeting")
    print("=" * 60 + "\n")

    # Title (required)
    title = input("Meeting title: ").strip()
    if not title:
        print("Error: Title is required.")
        return

    # Date
    date_str = input("Date (YYYY-MM-DD) [today]: ").strip()
    if not date_str:
        meeting_date = datetime.now().date()
    else:
        try:
            meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            print("Error: Invalid date format. Use YYYY-MM-DD.")
            return

    # Start time
    start_str = input("Start time (HH:MM, 24h format) [09:00]: ").strip()
    if not start_str:
        start_str = "09:00"
    try:
        start_parts = start_str.split(":")
        start_hour, start_min = int(start_parts[0]), int(start_parts[1])
        start_time = datetime.combine(meeting_date, datetime.min.time().replace(hour=start_hour, minute=start_min))
    except (ValueError, IndexError):
        print("Error: Invalid time format. Use HH:MM (24h).")
        return

    # Duration
    duration_str = input("Duration in minutes [30]: ").strip()
    if not duration_str:
        duration = 30
    else:
        try:
            duration = int(duration_str)
        except ValueError:
            print("Error: Duration must be a number.")
            return

    end_time = start_time + timedelta(minutes=duration)

    # Attendees
    attendees_str = input("Attendees (comma-separated emails/names, or blank): ").strip()
    attendees = [a.strip() for a in attendees_str.split(",") if a.strip()] if attendees_str else []

    # Description
    description = input("Description/agenda (optional): ").strip() or None

    # Location
    location = input("Location (optional): ").strip() or None

    # Meeting link
    meeting_link = input("Meeting link - Zoom/Meet/Teams URL (optional): ").strip() or None

    # Recurring
    recurring_str = input("Is this recurring? (y/N): ").strip().lower()
    is_recurring = recurring_str in ("y", "yes")

    # Confirm
    print("\n" + "-" * 40)
    print(f"  Title:     {title}")
    print(f"  Date:      {meeting_date}")
    print(f"  Time:      {start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')} ({duration} min)")
    if attendees:
        print(f"  Attendees: {', '.join(attendees)}")
    if description:
        print(f"  Agenda:    {description}")
    if location:
        print(f"  Location:  {location}")
    if meeting_link:
        print(f"  Link:      {meeting_link}")
    print("-" * 40)

    confirm = input("\nSave this meeting? (Y/n): ").strip().lower()
    if confirm in ("n", "no"):
        print("Cancelled.")
        return

    meeting = store.add_meeting(
        title=title,
        start_time=start_time,
        end_time=end_time,
        attendees=attendees,
        description=description,
        location=location,
        meeting_link=meeting_link,
        is_recurring=is_recurring,
    )

    print(f"\nMeeting saved! (ID: {meeting['id']})")
    print("It will be included in your next prep brief run.\n")


def _list_meetings() -> None:
    """
    List all manually added meetings.

    For upcoming meetings that don't have a description, prompts the user
    to add a quick 1-2 line description. This makes the AI prep briefs
    significantly better because Claude has context about what the meeting is for.
    """
    store = MeetingStore()
    meetings = store.get_all_meetings()

    if not meetings:
        print("\nNo manually added meetings found.")
        print("Use --add-meeting to add one.\n")
        return

    print("\n" + "=" * 60)
    print("  Manually Added Meetings")
    print("=" * 60 + "\n")

    now = datetime.now()
    needs_description = []

    for m in sorted(meetings, key=lambda x: x.get("start_time", "")):
        try:
            start = datetime.fromisoformat(m["start_time"])
            end = datetime.fromisoformat(m["end_time"])
            is_past = end < now

            status = " (past)" if is_past else ""
            duration = int((end - start).total_seconds() / 60)

            print(f"  [{m['id']}] {m['title']}{status}")
            print(f"    {start.strftime('%b %d, %Y  %I:%M %p')} - {end.strftime('%I:%M %p')} ({duration} min)")
            if m.get("attendees"):
                print(f"    Attendees: {', '.join(m['attendees'])}")
            if m.get("description"):
                print(f"    About: {m['description'][:100]}")
            else:
                print(f"    About: (no description - AI prep will be generic)")
                # Track upcoming meetings without descriptions
                if not is_past:
                    needs_description.append(m)
            print()
        except (ValueError, KeyError):
            print(f"  [{m.get('id', '?')}] (invalid meeting data)")
            print()

    print(f"Total: {len(meetings)} meeting(s)")

    # Prompt for missing descriptions on upcoming meetings
    if needs_description:
        print(f"\n{len(needs_description)} upcoming meeting(s) have no description.")
        print("Adding a quick 1-2 line description helps the AI generate better prep.\n")

        for m in needs_description:
            print(f"  >> {m['title']}")
            desc = input("     What is this meeting about? (Enter to skip): ").strip()
            if desc:
                store.update_meeting(m["id"], description=desc)
                print(f"     Saved!\n")
            else:
                print()

    print()


def _remove_meeting(meeting_id: str) -> None:
    """Remove a meeting by ID."""
    store = MeetingStore()
    if store.remove_meeting(meeting_id):
        print(f"\nMeeting {meeting_id} removed.\n")
    else:
        print(f"\nMeeting {meeting_id} not found.\n")
        print("Use --list-meetings to see all meetings.\n")


def _browse_university_events(university: str, days: int) -> None:
    """
    Browse upcoming university events, pick ones you're interested in,
    and add them to your personal calendar for AI prep.
    """
    try:
        client = UniversityEventsClient(university)
    except ValueError as e:
        print(f"\nError: {e}")
        print(f"Available universities: {', '.join(UNIVERSITY_ENDPOINTS.keys())}\n")
        return

    uni_name = UNIVERSITY_ENDPOINTS[university]["name"]
    print(f"\nFetching events from {uni_name} (next {days} days)...")

    events = client.fetch_upcoming_events(days=days)

    if not events:
        print(f"No events found at {uni_name} for the next {days} days.\n")
        return

    store = MeetingStore()
    client.pick_and_save(events, store)


def _tag_document(file_path: str, category: str) -> None:
    """Tag a reference document to a meeting category."""
    store = ReferenceDocsStore()

    label = input(f"Short label for '{file_path}' (Enter for auto): ").strip() or None

    if store.tag_to_category(file_path, category, label=label):
        print(f"\nTagged '{file_path}' -> {category} meetings")
        print("This doc will be injected into AI prep for all future", category, "meetings.\n")
    else:
        print(f"\nError: Could not tag '{file_path}'. File not found?\n")


def _list_documents() -> None:
    """List all tagged reference documents (with order)."""
    store = ReferenceDocsStore()
    data = store.list_all()

    has_docs = False

    if data.get("by_category"):
        print("\n" + "=" * 60)
        print("  Reference Documents by Category (order = priority)")
        print("=" * 60 + "\n")
        for category, docs in sorted(data["by_category"].items()):
            if docs:
                has_docs = True
                ordered = sorted(docs, key=lambda d: d.get("order", 0))
                print(f"  [{category.upper()}]")
                for i, doc in enumerate(ordered):
                    path_or_id = doc.get("path", "")
                    kind = "inline" if path_or_id.startswith("inline:") else "file"
                    print(f"    {i}. {doc.get('filename', doc.get('label', ''))}  ({doc.get('label', '')})  [{kind}]")
                print()

    if data.get("by_meeting"):
        for mid, docs in data["by_meeting"].items():
            if docs:
                has_docs = True
                print(f"  [Meeting: {mid}]")
                for doc in docs:
                    print(f"    - {doc['filename']}  ({doc.get('label', '')})")
                print()

    if not has_docs:
        print("\nNo reference documents tagged yet.")
        print("Use --tag-doc <file> <category> or --add-inline-doc to add.")
        print("Example: --tag-doc networking_tips.pdf networking\n")


def _remove_document(file_path_or_id: str) -> None:
    """Remove a reference doc from all tags (file path or inline id)."""
    store = ReferenceDocsStore()
    if store.remove_doc(file_path_or_id):
        print(f"\nRemoved '{file_path_or_id}' from all tags.\n")
    else:
        print(f"\nNo document found for '{file_path_or_id}'.\n")


def _reorder_docs(category: str, ordered_paths: list) -> None:
    """Set doc order for a category (first in list = highest priority)."""
    store = ReferenceDocsStore()
    if store.set_category_order(category, ordered_paths):
        print(f"\nOrder updated for category '{category}'.\n")
    else:
        print(f"\nCategory '{category}' not found or no docs.\n")


def _add_inline_doc_interactive() -> None:
    """Add pasted content (e.g. from Google Doc) as a reference doc."""
    store = ReferenceDocsStore()
    print("\n" + "=" * 60)
    print("  Add pasted reference (e.g. Google Doc)")
    print("=" * 60 + "\n")
    print("Categories: 1:1, team, client, interview, networking, standup, all-hands, other")
    category = input("Category: ").strip().lower()
    if not category:
        print("Cancelled.\n")
        return
    label = input("Short label (e.g. 'Interview STAR tips'): ").strip() or None
    print("Paste content below (Enter twice when done):")
    lines = []
    while True:
        line = input("  ")
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    content = "\n".join(lines).strip()
    if not content:
        print("No content. Cancelled.\n")
        return
    doc_id = store.add_inline_doc(category, content, label=label)
    print(f"\nAdded inline doc -> {category} (id: {doc_id})\n")


def _detect_redundancy(category: Optional[str]) -> None:
    """Show potentially redundant doc pairs in a category (or all)."""
    store = ReferenceDocsStore()
    pairs = store.detect_redundancy(category=category)
    if not pairs:
        print("\nNo redundant pairs found (or category has < 2 docs).\n")
        return
    print("\n" + "=" * 60)
    print("  Possibly redundant reference docs (consider removing one)")
    print("=" * 60 + "\n")
    for d1, d2, sim in pairs:
        n1 = d1.get("filename", d1.get("label", d1.get("path", "")))
        n2 = d2.get("filename", d2.get("label", d2.get("path", "")))
        print(f"  Similarity {sim:.0%}: '{n1}' <-> '{n2}'")
    print("\nUse --remove-doc <path-or-id> to remove one.\n")


def _search_notes(query: str) -> None:
    """Search meeting notes by keyword and show results for reuse."""
    store = MeetingNotesStore()
    notes = store.search_notes(query)
    if not notes:
        print(f"\nNo notes matching '{query}'.\n")
        return
    print("\n" + "=" * 60)
    print(f"  Meeting notes matching '{query}'")
    print("=" * 60 + "\n")
    for note in notes:
        print(f"  [{note.get('date')}] {note.get('meeting_title')} (id: {note.get('id')})")
        content = note.get("content", "")[:200]
        if content:
            print(f"    {content}...")
        print()
    print(f"Total: {len(notes)}. Use these in prep by title/attendee overlap.\n")


def _export_notes(output_path: Optional[str]) -> None:
    """Export all meeting notes (for backup or reuse elsewhere)."""
    store = MeetingNotesStore()
    notes = store.get_all_notes()
    path = output_path or "meeting_notes_export.json"
    with open(path, "w") as f:
        json.dump(notes, f, indent=2, default=str)
    print(f"\nExported {len(notes)} notes to {path}\n")


def _add_note_interactive() -> None:
    """Interactive CLI flow to add meeting notes."""
    store = MeetingNotesStore()
    meeting_store = MeetingStore()

    print("\n" + "=" * 60)
    print("  Add Meeting Notes")
    print("=" * 60 + "\n")

    # Show recent meetings for context
    meetings = meeting_store.get_all_meetings()
    recent = sorted(meetings, key=lambda x: x.get("start_time", ""), reverse=True)[:5]

    if recent:
        print("  Recent meetings:")
        for i, m in enumerate(recent, 1):
            try:
                start = datetime.fromisoformat(m["start_time"])
                print(f"    {i}. {m['title']} ({start.strftime('%b %d')})")
            except (ValueError, KeyError):
                print(f"    {i}. {m['title']}")
        print()

    # Meeting title
    title = input("Meeting title (or number from above): ").strip()
    if not title:
        print("Error: Title is required.")
        return

    # If user entered a number, map to recent meeting
    meeting_id = None
    if title.isdigit() and recent:
        idx = int(title) - 1
        if 0 <= idx < len(recent):
            title = recent[idx]["title"]
            meeting_id = recent[idx].get("id")
            print(f"  -> {title}")

    # Attendees
    attendees_str = input("Attendees (comma-separated, or blank): ").strip()
    attendees = [a.strip() for a in attendees_str.split(",") if a.strip()] if attendees_str else []

    # Notes content
    print("\nKey takeaways / discussion notes (Enter twice to finish):")
    lines = []
    while True:
        line = input("  ")
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    content = "\n".join(lines).strip()

    if not content:
        print("No notes entered. Cancelled.\n")
        return

    # Action items
    print("\nAction items (one per line, Enter twice to finish):")
    action_items = []
    while True:
        item = input("  - ").strip()
        if not item:
            break
        action_items.append(item)

    # Decisions
    print("\nDecisions made (one per line, Enter twice to finish):")
    decisions = []
    while True:
        decision = input("  - ").strip()
        if not decision:
            break
        decisions.append(decision)

    # Date
    date_str = input("\nMeeting date (YYYY-MM-DD) [today]: ").strip()
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    note = store.add_note(
        meeting_title=title,
        content=content,
        meeting_id=meeting_id,
        attendees=attendees,
        action_items=action_items,
        decisions=decisions,
        date=date_str,
    )

    print(f"\nNotes saved! (ID: {note['id']})")
    if action_items:
        print(f"  {len(action_items)} action item(s) tracked")
    if decisions:
        print(f"  {len(decisions)} decision(s) recorded")
    print("These notes will inform future prep briefs for similar meetings.\n")


def _list_notes() -> None:
    """List all saved meeting notes."""
    store = MeetingNotesStore()
    notes = store.get_all_notes()

    if not notes:
        print("\nNo meeting notes saved yet.")
        print("Use --add-note after a meeting to save notes.\n")
        return

    print("\n" + "=" * 60)
    print("  Meeting Notes")
    print("=" * 60 + "\n")

    for note in sorted(notes, key=lambda x: x.get("date", ""), reverse=True):
        print(f"  [{note.get('date', '?')}] {note['meeting_title']}")
        print(f"    ID: {note['id']}")

        content = note.get("content", "")
        if content:
            short = content[:120] + "..." if len(content) > 120 else content
            print(f"    Notes: {short}")

        actions = note.get("action_items", [])
        if actions:
            print(f"    Action items: {len(actions)}")

        decisions = note.get("decisions", [])
        if decisions:
            print(f"    Decisions: {', '.join(decisions[:3])}")

        print()

    print(f"Total: {len(notes)} note(s)\n")


def _show_action_items() -> None:
    """Show all open action items from meeting notes."""
    store = MeetingNotesStore()
    items = store.get_open_action_items()

    if not items:
        print("\nNo action items found.")
        print("Add meeting notes with --add-note to track action items.\n")
        return

    print("\n" + "=" * 60)
    print("  Open Action Items")
    print("=" * 60 + "\n")

    for item in sorted(items, key=lambda x: x.get("date", ""), reverse=True):
        print(f"  [ ] {item['action']}")
        print(f"      From: {item['meeting']} ({item['date']})")
        print()

    print(f"Total: {len(items)} action item(s)\n")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AI Meeting Prep Agent - Automated meeting intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main --run              Run once, send email
  python -m src.main --dry-run          Run once, preview only (no email)
  python -m src.main --schedule         Start daily scheduler
  python -m src.main --add-meeting      Add a meeting manually
  python -m src.main --list-meetings    List all manual meetings
  python -m src.main --remove-meeting ID  Remove a manual meeting
  python -m src.main --events           Browse Purdue university events
  python -m src.main --events --days 14 Browse next 14 days of events
  python -m src.main --run -v           Run with verbose logging
        """,
    )

    # Action arguments (mutually exclusive)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--run", action="store_true",
        help="Run the pipeline once immediately",
    )
    action.add_argument(
        "--dry-run", action="store_true",
        help="Run pipeline without sending email (preview mode)",
    )
    action.add_argument(
        "--schedule", action="store_true",
        help="Start the scheduler (runs daily at configured time)",
    )
    action.add_argument(
        "--add-meeting", action="store_true",
        help="Add a meeting manually (interactive prompts)",
    )
    action.add_argument(
        "--list-meetings", action="store_true",
        help="List all manually added meetings",
    )
    action.add_argument(
        "--remove-meeting", metavar="ID",
        help="Remove a manually added meeting by its ID",
    )
    action.add_argument(
        "--events", action="store_true",
        help="Browse university events and add ones you're interested in",
    )
    action.add_argument(
        "--tag-doc", nargs=2, metavar=("FILE", "CATEGORY"),
        help="Tag a reference doc (PDF/txt) to a meeting category (e.g. --tag-doc tips.pdf interview)",
    )
    action.add_argument(
        "--list-docs", action="store_true",
        help="List all tagged reference documents",
    )
    action.add_argument(
        "--add-note", action="store_true",
        help="Add meeting notes (interactive prompts)",
    )
    action.add_argument(
        "--list-notes", action="store_true",
        help="List all saved meeting notes",
    )
    action.add_argument(
        "--action-items", action="store_true",
        help="Show all open action items from meeting notes",
    )
    action.add_argument(
        "--remove-doc", metavar="PATH_OR_ID",
        help="Remove a reference doc from all tags (file path or inline id)",
    )
    action.add_argument(
        "--reorder-docs", nargs="+", metavar=("CATEGORY", "PATH", "..."),
        help="Set doc order for a category: --reorder-docs interview doc1.pdf doc2.txt",
    )
    action.add_argument(
        "--add-inline-doc", action="store_true",
        help="Add pasted content (e.g. Google Doc) as reference (interactive)",
    )
    action.add_argument(
        "--detect-redundancy", nargs="?", metavar="CATEGORY", const="",
        help="Find possibly redundant docs in a category (or all if no category)",
    )
    action.add_argument(
        "--search-notes", metavar="QUERY",
        help="Search meeting notes by keyword (for reuse)",
    )
    action.add_argument(
        "--export-notes", nargs="?", metavar="FILE", const="",
        help="Export all meeting notes to JSON (default: meeting_notes_export.json)",
    )

    # Optional arguments
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to YAML config file (default: config.yaml)",
    )
    parser.add_argument(
        "--university", default="purdue",
        choices=list(UNIVERSITY_ENDPOINTS.keys()),
        help="University to browse events from (default: purdue)",
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Number of days ahead to look for events (default: 7)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # ── Setup logging ──────────────────────────────────────────
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Execute action ─────────────────────────────────────────
    if args.add_meeting:
        _add_meeting_interactive()
    elif args.list_meetings:
        _list_meetings()
    elif args.remove_meeting:
        _remove_meeting(args.remove_meeting)
    elif args.events:
        _browse_university_events(args.university, args.days)
    elif args.tag_doc:
        _tag_document(args.tag_doc[0], args.tag_doc[1])
    elif args.list_docs:
        _list_documents()
    elif args.remove_doc:
        _remove_document(args.remove_doc)
    elif args.reorder_docs:
        if len(args.reorder_docs) < 2:
            print("Usage: --reorder-docs CATEGORY PATH1 PATH2 ...")
        else:
            _reorder_docs(args.reorder_docs[0], args.reorder_docs[1:])
    elif args.add_inline_doc:
        _add_inline_doc_interactive()
    elif args.detect_redundancy is not None:
        _detect_redundancy(args.detect_redundancy or None)
    elif args.add_note:
        _add_note_interactive()
    elif args.list_notes:
        _list_notes()
    elif args.action_items:
        _show_action_items()
    elif args.search_notes:
        _search_notes(args.search_notes)
    elif args.export_notes is not None:
        _export_notes(args.export_notes if args.export_notes else None)
    else:
        # Pipeline actions need config
        config = load_config(args.config)
        logger.debug("Configuration loaded from %s", args.config)

        if args.run:
            run_pipeline(config, dry_run=False)
        elif args.dry_run:
            run_pipeline(config, dry_run=True)
        elif args.schedule:
            scheduler = MeetingPrepScheduler(
                config.scheduler,
                lambda: run_pipeline(config),
            )
            scheduler.start()


if __name__ == "__main__":
    main()
