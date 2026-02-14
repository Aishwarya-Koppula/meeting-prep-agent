"""
AI-powered meeting brief generation using Claude (Anthropic API).

This is the intelligence core of the system. It takes processed calendar
events and generates personalized preparation briefs with:
- Meeting context summary
- Talking points (categorized)
- Suggested questions to ask
- Context notes for preparation

Key concepts:
- System prompt: Defines Claude's role and output format
- User prompt: Contains specific event details for each meeting
- Structured output: We ask for JSON to make parsing reliable
- Category-aware: Different meeting types get tailored prompts
- Reference docs: Tagged documents (PDFs, notes) are injected for context
- Meeting notes: Past notes from similar meetings inform new briefs
"""

import json
import logging
import re
from typing import List, Optional

import anthropic

from src.models import (
    ProcessedEvent,
    PrepBrief,
    TalkingPoint,
    MeetingCategory,
)
from src.config import AnthropicConfig

logger = logging.getLogger(__name__)


# ── Prompt Templates ───────────────────────────────────────────
# These are the prompts sent to Claude. The system prompt defines
# the AI's role. The user prompt contains event-specific details.

SYSTEM_PROMPT = """You are an expert meeting preparation assistant. Generate concise, \
actionable meeting prep. No fluff, no filler, no generic advice, no obvious tips.

Rules:
- Every talking point must be SPECIFIC to this meeting, not generic
- Every question must be something only someone prepared would ask
- If reference documents are provided, USE them -- extract the most relevant points only; align to the order and remove redundancy
- If past meeting notes are provided, build on them -- don't repeat what was already discussed; reuse outcomes and follow-ups
- Cut anything a smart person could figure out on their own
- Do not add introductory or motivational filler. Output only the JSON.

ALWAYS respond with valid JSON matching this exact schema:
{
    "summary": "2-3 sentences. What this meeting is about and what YOU need to get out of it.",
    "talking_points": [
        {
            "point": "Specific, actionable point tied to this meeting's context",
            "category": "discussion|question|update|follow-up",
            "priority": "high|medium|low"
        }
    ],
    "suggested_questions": [
        "A targeted question that shows preparation and moves the meeting forward"
    ],
    "context_notes": "Specific things to review beforehand (not generic advice)",
    "preparation_time_minutes": 5
}

Guidelines:
- 3-5 talking points, each one actionable and specific
- 2-4 questions that demonstrate you did your homework
- Summary: what matters and why, nothing else
- High priority = more depth. Low priority = bare minimum
- If reference docs mention specific strategies, frameworks, or tips -- weave them in
- If past meeting notes exist, reference outcomes and build forward
- ONLY output valid JSON, no markdown wrapping, no extra text"""

CATEGORY_PROMPTS = {
    MeetingCategory.ONE_ON_ONE: (
        "1:1 meeting. Skip generic relationship advice. Focus on: "
        "specific topics to raise, updates to share, feedback to give/request. "
        "Questions should be about THEIR priorities and how to unblock each other."
    ),
    MeetingCategory.TEAM: (
        "Team meeting. Focus on: your status update (concrete deliverables), "
        "blockers you need help on, decisions that need the group. "
        "No generic 'align on goals' fluff."
    ),
    MeetingCategory.CLIENT: (
        "Client meeting. Focus on: specific value you're delivering, "
        "their pain points to address, concrete next steps to propose. "
        "Every talking point should move the relationship forward."
    ),
    MeetingCategory.INTERVIEW: (
        "Interview. Use any reference docs (company research, role prep) to generate "
        "SPECIFIC questions about the company/role. Prepare 2-3 STAR examples "
        "relevant to likely questions. No generic interview advice."
    ),
    MeetingCategory.NETWORKING: (
        "Networking/coffee chat. Focus on: 2-3 specific questions about their work, "
        "what you can offer them, a concrete follow-up action. "
        "Natural conversation starters, not interrogation."
    ),
    MeetingCategory.STANDUP: (
        "Standup. Keep it minimal: yesterday's done, today's plan, blockers. "
        "No prep brief needed beyond organizing your own status."
    ),
    MeetingCategory.ALL_HANDS: (
        "All-hands. List topics to listen for based on the agenda. "
        "Prepare 1-2 questions for Q&A if applicable. Minimal prep."
    ),
}


class AIBriefer:
    """
    Uses Claude to generate meeting preparation briefs.

    Supports injecting reference documents and past meeting notes into
    the prompt for more targeted, context-aware briefs.

    Usage:
        briefer = AIBriefer(config)
        brief = briefer.generate_brief(event, ref_docs_content="...", past_notes="...")
        briefs = briefer.generate_briefs(events)
    """

    def __init__(self, config: AnthropicConfig):
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.api_key)
        self._ref_docs_store = None
        self._notes_store = None

    def set_reference_docs_store(self, store) -> None:
        """Set the ReferenceDocsStore for automatic doc injection."""
        self._ref_docs_store = store

    def set_notes_store(self, store) -> None:
        """Set the MeetingNotesStore for automatic past notes injection."""
        self._notes_store = store

    def generate_brief(
        self,
        event: ProcessedEvent,
        ref_docs_content: Optional[str] = None,
        past_notes: Optional[str] = None,
    ) -> PrepBrief:
        """
        Generate a prep brief for a single meeting.

        Steps:
        1. Auto-fetch reference docs and past notes if stores are set
        2. Build the user prompt with event details + category context + docs + notes
        3. Call Claude API
        4. Parse JSON response into PrepBrief model
        5. Handle errors gracefully (fallback to minimal brief)

        Args:
            event: The processed event to generate a brief for
            ref_docs_content: Pre-formatted reference doc content (optional)
            past_notes: Pre-formatted past meeting notes (optional)
        """
        # Auto-fetch reference docs if store is set and no explicit content
        if ref_docs_content is None and self._ref_docs_store is not None:
            ref_docs_content = self._get_auto_ref_docs(event)

        # Auto-fetch past notes if store is set and no explicit content
        if past_notes is None and self._notes_store is not None:
            past_notes = self._get_auto_past_notes(event)

        user_prompt = self._build_event_prompt(event, ref_docs_content, past_notes)

        try:
            logger.info(f"Generating brief for: {event.event.title}")

            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Extract the text content from Claude's response
            response_text = response.content[0].text
            return self._parse_response(response_text, event)

        except anthropic.APIError as e:
            logger.error(f"Claude API error for '{event.event.title}': {e}")
            return self._fallback_brief(event, f"API error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error generating brief for '{event.event.title}': {e}")
            return self._fallback_brief(event, f"Error: {e}")

    def generate_briefs(self, events: List[ProcessedEvent]) -> List[PrepBrief]:
        """
        Generate briefs for all events.

        Reference docs and past notes are auto-injected if stores are set.
        """
        briefs = []
        for event in events:
            brief = self.generate_brief(event)
            briefs.append(brief)
        return briefs

    def _get_auto_ref_docs(self, event: ProcessedEvent) -> Optional[str]:
        """Auto-fetch reference docs for the event's category and meeting ID."""
        try:
            category = event.category.value
            meeting_id = event.event.event_id
            docs = self._ref_docs_store.get_relevant_docs(category, meeting_id)

            if not docs:
                return None

            parts = []
            for doc in docs:
                content = self._ref_docs_store.extract_content(doc)
                if content and not content.startswith("["):
                    parts.append(f"--- {doc.get('label', doc['filename'])} ---\n{content}")

            return "\n\n".join(parts) if parts else None
        except Exception as e:
            logger.warning("Failed to auto-fetch reference docs: %s", e)
            return None

    def _get_auto_past_notes(self, event: ProcessedEvent) -> Optional[str]:
        """Auto-fetch relevant past meeting notes."""
        try:
            notes = self._notes_store.get_relevant_notes(
                title=event.event.title,
                attendees=event.event.attendees,
                limit=3,
            )
            if not notes:
                return None

            parts = []
            for note in notes:
                date_str = note.get("date", "unknown date")
                content = note.get("content", "")
                if content:
                    parts.append(f"[{date_str}] {content}")

            return "\n\n".join(parts) if parts else None
        except Exception as e:
            logger.warning("Failed to auto-fetch past notes: %s", e)
            return None

    def _build_event_prompt(
        self,
        event: ProcessedEvent,
        ref_docs_content: Optional[str] = None,
        past_notes: Optional[str] = None,
    ) -> str:
        """
        Build the user prompt containing event details + category-specific guidance.

        The prompt includes:
        - Event title, time, duration
        - Attendees (names/emails)
        - Description (if any)
        - Meeting category and priority
        - Category-specific instructions
        - Reference document content (if tagged)
        - Past meeting notes (if available)
        """
        # Format attendees list
        attendees_str = ", ".join(event.event.attendees) if event.event.attendees else "No attendees listed"

        # Format time
        time_str = event.event.start_time.strftime("%I:%M %p")
        end_str = event.event.end_time.strftime("%I:%M %p")

        # Get category-specific guidance
        category_hint = CATEGORY_PROMPTS.get(event.category, "")

        prompt = f"""Generate a meeting preparation brief for the following meeting:

MEETING DETAILS:
- Title: {event.event.title}
- Time: {time_str} - {end_str} ({event.duration_minutes} minutes)
- Attendees: {attendees_str}
- Organizer: {event.event.organizer or "Not specified"}
- Location: {event.event.location or "Not specified"}
- Meeting Link: {event.event.meeting_link or "None"}
- Category: {event.category.value}
- Priority: {event.priority.value}
- Recurring: {"Yes" if event.event.is_recurring else "No"}

DESCRIPTION/AGENDA:
{event.event.description or "No description provided"}"""

        # Inject reference documents if available
        if ref_docs_content:
            prompt += f"""

REFERENCE DOCUMENTS (use these for specific, targeted prep):
{ref_docs_content}

IMPORTANT: Extract the most relevant points from these docs. Don't summarize the whole doc -- \
only pull what's directly useful for THIS meeting."""

        # Inject past meeting notes if available
        if past_notes:
            prompt += f"""

PAST MEETING NOTES (build on these, don't repeat):
{past_notes}

IMPORTANT: Reference outcomes from past meetings. Identify what was discussed before \
and what needs follow-up. Don't rehash old ground."""

        prompt += f"""

MEETING TYPE GUIDANCE:
{category_hint}

Priority level is {event.priority.value.upper()}, so {"provide detailed, thorough preparation" if event.priority.value == "high" else "keep preparation concise" if event.priority.value == "low" else "provide moderate preparation"}.

Be specific and actionable. No generic advice. Respond with valid JSON only."""

        return prompt

    def _parse_response(self, response_text: str, event: ProcessedEvent) -> PrepBrief:
        """
        Parse Claude's JSON response into a PrepBrief model.

        Handles multiple response formats:
        1. Clean JSON (ideal)
        2. JSON wrapped in markdown code blocks (```json ... ```)
        3. Malformed JSON -> fallback to minimal brief
        """
        # Try parsing as-is first
        try:
            data = json.loads(response_text)
            return self._build_brief_from_dict(data, event)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return self._build_brief_from_dict(data, event)
            except json.JSONDecodeError:
                pass

        # Try finding JSON object in the response
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                return self._build_brief_from_dict(data, event)
            except json.JSONDecodeError:
                pass

        # All parsing failed - use raw text as summary
        logger.warning(f"Could not parse JSON response for '{event.event.title}', using raw text")
        return PrepBrief(
            event=event,
            summary=response_text[:500],
            context_notes="Note: AI response was not in expected format.",
        )

    def _build_brief_from_dict(self, data: dict, event: ProcessedEvent) -> PrepBrief:
        """Convert a parsed JSON dict into a PrepBrief model."""
        talking_points = [
            TalkingPoint(
                point=tp.get("point", ""),
                category=tp.get("category", "discussion"),
                priority=tp.get("priority", "medium"),
            )
            for tp in data.get("talking_points", [])
        ]

        return PrepBrief(
            event=event,
            summary=data.get("summary", ""),
            talking_points=talking_points,
            suggested_questions=data.get("suggested_questions", []),
            context_notes=data.get("context_notes", ""),
            preparation_time_minutes=data.get("preparation_time_minutes", 5),
        )

    def _fallback_brief(self, event: ProcessedEvent, error_msg: str) -> PrepBrief:
        """
        Create a minimal brief when AI generation fails.

        This ensures the user still gets basic meeting info even if
        Claude is unavailable or returns an error.
        """
        return PrepBrief(
            event=event,
            summary=f"Meeting: {event.event.title} ({event.duration_minutes} min)",
            talking_points=[
                TalkingPoint(
                    point="Review meeting agenda and any shared documents",
                    category="update",
                    priority="medium",
                ),
            ],
            suggested_questions=["What are the key outcomes we need from this meeting?"],
            context_notes=f"AI brief generation failed ({error_msg}). Review event description for context.",
            preparation_time_minutes=5,
        )
