"""
Microsoft Outlook Calendar + Teams client via Microsoft Graph API.

Fetches events from Outlook Calendar and Teams meetings using a single
API (Microsoft Graph), since Teams meetings are exposed as calendar events.

Microsoft Graph API overview:
    - Single endpoint for Outlook Calendar + Teams meetings
    - Teams meetings appear as calendar events with an onlineMeeting property
    - OAuth 2.0 authentication (device code flow for CLI apps)

Setup:
    1. Go to https://portal.azure.com -> Azure Active Directory
    2. App Registrations -> New Registration
    3. Name: "Meeting Prep Agent", Accounts: Personal + Org
    4. Add API permissions: Calendars.Read, OnlineMeetings.Read
    5. Under Authentication -> Allow public client flows -> Yes
    6. Copy the Application (client) ID into your .env

Free tier limits:
    - 10,000 requests per 10 minutes (more than enough)
    - No cost for personal Microsoft accounts
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from pathlib import Path

import requests

from src.models import CalendarEvent
from src.config import OutlookConfig

logger = logging.getLogger(__name__)

# Microsoft Graph endpoints
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookCalendarClient:
    """
    Fetches events from Outlook Calendar and Teams via Microsoft Graph API.

    Teams meetings automatically appear as Outlook calendar events with
    onlineMeeting data, so a single calendar fetch gets both.

    Usage:
        client = OutlookCalendarClient(config)
        client.authenticate()
        events = client.fetch_todays_events()  # includes Teams meetings
    """

    def __init__(self, config: OutlookConfig):
        self.config = config
        self._access_token: Optional[str] = None
        tenant = getattr(config, "tenant_id", "common") or "common"
        self._auth_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"

    def authenticate(self) -> None:
        """
        Authenticate with Microsoft Graph using device code flow.

        Device code flow works for CLI apps:
        1. App displays a code and a URL
        2. User opens URL in browser, enters the code
        3. User grants consent
        4. App receives access token

        Tokens are cached in outlook_token.json for reuse.
        """
        token_path = Path(self.config.token_path)

        # Try loading cached token
        if token_path.exists():
            try:
                token_data = json.loads(token_path.read_text())
                # Check if we have a refresh token to get a new access token
                if "refresh_token" in token_data:
                    self._access_token = self._refresh_token(token_data["refresh_token"])
                    if self._access_token:
                        logger.info("Outlook token refreshed successfully")
                        return
            except (json.JSONDecodeError, KeyError):
                pass

        # No valid cached token - start device code flow
        if not self.config.client_id:
            raise ValueError(
                "OUTLOOK_CLIENT_ID not set. "
                "Register an app at https://portal.azure.com -> App Registrations. "
                "See README for setup instructions."
            )

        device_code_data = self._request_device_code()
        if not device_code_data:
            raise RuntimeError("Failed to initiate device code flow")

        # Show user the code to enter
        print("\n" + "=" * 50)
        print("  Microsoft Account Authentication")
        print("=" * 50)
        print(f"\n  1. Open: {device_code_data['verification_uri']}")
        print(f"  2. Enter code: {device_code_data['user_code']}")
        print(f"\n  Waiting for you to authorize...")
        print("=" * 50 + "\n")

        # Poll for token
        token_data = self._poll_for_token(device_code_data)
        if not token_data:
            raise RuntimeError("Authentication timed out or was denied")

        self._access_token = token_data["access_token"]

        # Cache the token
        token_path.write_text(json.dumps(token_data, indent=2))
        logger.info("Outlook token saved to %s", token_path)

    def _request_device_code(self) -> Optional[dict]:
        """Request a device code from Microsoft."""
        try:
            resp = requests.post(
                f"{self._auth_url}/devicecode",
                data={
                    "client_id": self.config.client_id,
                    "scope": " ".join(self.config.scopes),
                },
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("Failed to request device code: %s", e)
            return None

    def _poll_for_token(self, device_code_data: dict) -> Optional[dict]:
        """Poll Microsoft for the access token after user authorizes."""
        interval = device_code_data.get("interval", 5)
        expires_in = device_code_data.get("expires_in", 900)
        device_code = device_code_data["device_code"]

        import time
        start = time.time()

        while time.time() - start < expires_in:
            time.sleep(interval)
            try:
                resp = requests.post(
                    f"{self._auth_url}/token",
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "client_id": self.config.client_id,
                        "device_code": device_code,
                    },
                    timeout=10,
                )
                data = resp.json()

                if "access_token" in data:
                    return data
                elif data.get("error") == "authorization_pending":
                    continue
                elif data.get("error") == "slow_down":
                    interval += 5
                else:
                    logger.error("Auth error: %s", data.get("error_description", data.get("error")))
                    return None
            except requests.RequestException:
                continue

        return None

    def _refresh_token(self, refresh_token: str) -> Optional[str]:
        """Refresh an expired access token."""
        try:
            resp = requests.post(
                f"{self._auth_url}/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.config.client_id,
                    "refresh_token": refresh_token,
                    "scope": " ".join(self.config.scopes),
                },
                timeout=10,
            )
            data = resp.json()
            if "access_token" in data:
                # Update cached token
                token_path = Path(self.config.token_path)
                token_path.write_text(json.dumps(data, indent=2))
                return data["access_token"]
        except requests.RequestException as e:
            logger.warning("Token refresh failed: %s", e)
        return None

    def fetch_events(
        self, time_min: datetime, time_max: datetime
    ) -> List[CalendarEvent]:
        """
        Fetch events from Outlook Calendar (includes Teams meetings).

        Microsoft Graph returns Teams meetings as regular calendar events
        with an additional onlineMeeting property containing the join URL.
        """
        if not self._access_token:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        time_min_str = time_min.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max_str = time_max.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        events = []
        url = (
            f"{GRAPH_BASE}/me/calendarview"
            f"?startDateTime={time_min_str}"
            f"&endDateTime={time_max_str}"
            f"&$select=id,subject,start,end,body,location,attendees,"
            f"organizer,isOnlineMeeting,onlineMeeting,recurrence,isCancelled"
            f"&$orderby=start/dateTime"
            f"&$top=100"
        )

        while url:
            try:
                resp = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                for raw_event in data.get("value", []):
                    if raw_event.get("isCancelled"):
                        continue
                    try:
                        event = self._parse_event(raw_event)
                        events.append(event)
                    except Exception as e:
                        logger.warning(
                            "Failed to parse Outlook event '%s': %s",
                            raw_event.get("subject", "Unknown"), e,
                        )

                # Handle pagination
                url = data.get("@odata.nextLink")

            except requests.RequestException as e:
                logger.error("Error fetching Outlook events: %s", e)
                break

        logger.info("Fetched %d events from Outlook/Teams", len(events))
        return events

    @staticmethod
    def _parse_graph_datetime(dt_str: str) -> datetime:
        """
        Parse a Microsoft Graph datetime string.

        Graph returns formats like: 2026-02-14T10:00:00.0000000Z
        or 2026-02-14T10:00:00.0000000 (no Z).
        Python 3.9 fromisoformat can't handle 7-digit fractional seconds,
        so we truncate to 6 digits.
        """
        import re
        # Remove trailing Z, we'll add UTC timezone explicitly
        dt_str = dt_str.rstrip("Z")
        # Truncate fractional seconds to 6 digits max (microseconds)
        dt_str = re.sub(r"(\.\d{6})\d+", r"\1", dt_str)
        # Parse and set UTC
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _parse_event(self, raw: dict) -> CalendarEvent:
        """Parse a Microsoft Graph calendar event into our CalendarEvent model."""
        start_str = raw["start"]["dateTime"]
        end_str = raw["end"]["dateTime"]

        start_time = self._parse_graph_datetime(start_str)
        end_time = self._parse_graph_datetime(end_str)

        # Check if all-day event
        is_all_day = (
            start_time.hour == 0 and start_time.minute == 0
            and end_time.hour == 0 and end_time.minute == 0
            and (end_time - start_time).days >= 1
        )

        # Extract attendees
        attendees = []
        for att in raw.get("attendees", []):
            email = att.get("emailAddress", {}).get("address", "")
            if email:
                attendees.append(email)

        # Extract organizer
        organizer = raw.get("organizer", {}).get("emailAddress", {}).get("address")

        # Extract meeting link (Teams or other online meeting)
        meeting_link = None
        is_teams = raw.get("isOnlineMeeting", False)
        online_meeting = raw.get("onlineMeeting")
        if online_meeting and isinstance(online_meeting, dict):
            meeting_link = online_meeting.get("joinUrl")

        # Determine source
        source = "outlook_teams" if is_teams else "outlook"

        # Location
        location_data = raw.get("location", {})
        location = location_data.get("displayName") if isinstance(location_data, dict) else None

        return CalendarEvent(
            event_id=raw["id"],
            title=raw.get("subject", "(No Subject)"),
            start_time=start_time,
            end_time=end_time,
            description=raw.get("body", {}).get("content", ""),
            location=location,
            attendees=attendees,
            organizer=organizer,
            is_recurring=raw.get("recurrence") is not None,
            is_all_day=is_all_day,
            meeting_link=meeting_link,
            calendar_id="outlook",
            source=source,
        )

    def fetch_todays_events(self) -> List[CalendarEvent]:
        """Fetch events for the next lookahead_hours (includes Teams meetings)."""
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(hours=self.config.lookahead_hours)
        return self.fetch_events(now, time_max)
