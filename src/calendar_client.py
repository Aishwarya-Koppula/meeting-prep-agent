"""
Google Calendar API client.

Handles OAuth 2.0 authentication and event fetching.

OAuth 2.0 Flow (first-time setup):
    1. User downloads credentials.json from Google Cloud Console
    2. First run opens a browser for user to grant calendar access
    3. After approval, token.json is saved locally
    4. Future runs use the saved token (auto-refreshes when expired)

To set up Google Calendar API:
    1. Go to https://console.cloud.google.com
    2. Create a project (or select existing)
    3. Enable "Google Calendar API"
    4. Create OAuth 2.0 credentials (Desktop Application type)
    5. Download the JSON file and save as credentials.json
    6. Run this module - it will open a browser for authentication

See docs/SETUP.md for detailed instructions with screenshots.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.models import CalendarEvent
from src.config import GoogleCalendarConfig

logger = logging.getLogger(__name__)


class GoogleCalendarClient:
    """
    Fetches events from Google Calendar using the official API.

    Usage:
        client = GoogleCalendarClient(config)
        client.authenticate()  # handles OAuth flow
        events = client.fetch_todays_events()
    """

    def __init__(self, config: GoogleCalendarConfig):
        self.config = config
        self._creds: Optional[Credentials] = None
        self._service = None

    def authenticate(self) -> None:
        """
        Handle the OAuth 2.0 authentication flow.

        This method:
        1. Checks if token.json exists and has valid credentials
        2. If token exists but expired, refreshes it automatically
        3. If no token exists, launches browser for user consent
        4. Saves the token for future use

        After calling this, self._service is ready to make API calls.
        """
        creds = None
        token_path = Path(self.config.token_path)
        credentials_path = Path(self.config.credentials_path)

        # Step 1: Try to load existing token
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(token_path), self.config.scopes
            )
            logger.info("Loaded existing token from %s", token_path)

        # Step 2: If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                # Token expired but has refresh token - refresh it
                logger.info("Token expired, refreshing...")
                creds.refresh(Request())
            else:
                # No token at all - need user to authenticate via browser
                if not credentials_path.exists():
                    raise FileNotFoundError(
                        f"credentials.json not found at {credentials_path}. "
                        "Download it from Google Cloud Console. "
                        "See docs/SETUP.md for instructions."
                    )
                logger.info("No valid token found. Opening browser for authentication...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), self.config.scopes
                )
                creds = flow.run_local_server(port=0)

            # Step 3: Save the token for next time
            with open(token_path, "w") as token_file:
                token_file.write(creds.to_json())
            logger.info("Token saved to %s", token_path)

        self._creds = creds
        self._service = build("calendar", "v3", credentials=creds)
        logger.info("Google Calendar API service initialized")

    def fetch_events(
        self, time_min: datetime, time_max: datetime
    ) -> List[CalendarEvent]:
        """
        Fetch events from all configured calendars within a time range.

        Args:
            time_min: Start of time range (inclusive)
            time_max: End of time range (exclusive)

        Returns:
            List of CalendarEvent models parsed from the API response
        """
        if not self._service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        all_events = []

        for calendar_id in self.config.calendar_ids:
            try:
                events = self._fetch_from_calendar(calendar_id, time_min, time_max)
                all_events.extend(events)
                logger.info(
                    "Fetched %d events from calendar '%s'", len(events), calendar_id
                )
            except HttpError as e:
                logger.error(
                    "Error fetching from calendar '%s': %s", calendar_id, e
                )
                continue

        return all_events

    def _fetch_from_calendar(
        self, calendar_id: str, time_min: datetime, time_max: datetime
    ) -> List[CalendarEvent]:
        """
        Fetch events from a single calendar.

        Handles pagination (Google returns max 250 events per page).
        Uses singleEvents=True to expand recurring events into individual instances.
        """
        events = []
        page_token = None

        # Ensure times are in UTC ISO format for the API
        time_min_str = time_min.astimezone(timezone.utc).isoformat()
        time_max_str = time_max.astimezone(timezone.utc).isoformat()

        while True:
            # Make the API call
            result = (
                self._service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min_str,
                    timeMax=time_max_str,
                    singleEvents=True,  # Expand recurring events
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=page_token,
                )
                .execute()
            )

            # Parse each event
            for raw_event in result.get("items", []):
                # Skip cancelled events
                if raw_event.get("status") == "cancelled":
                    continue

                try:
                    event = CalendarEvent.from_google_api(raw_event, calendar_id)
                    events.append(event)
                except Exception as e:
                    logger.warning(
                        "Failed to parse event '%s': %s",
                        raw_event.get("summary", "Unknown"),
                        e,
                    )

            # Check for more pages
            page_token = result.get("nextPageToken")
            if not page_token:
                break

        return events

    def fetch_todays_events(self) -> List[CalendarEvent]:
        """
        Convenience method: fetch events for the next `lookahead_hours`.

        This is the most common usage - called by the daily pipeline.
        """
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(hours=self.config.lookahead_hours)
        return self.fetch_events(now, time_max)
