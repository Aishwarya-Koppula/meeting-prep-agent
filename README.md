# AI Meeting Prep Agent

**Never walk into a meeting unprepared again.**

Automated meeting intelligence system that aggregates events from **multiple calendar sources** (Google Calendar, Outlook, Microsoft Teams, + manual input), generates AI-powered prep briefs via Claude, and delivers a prioritized daily digest to your inbox every morning.

**100% free to run** -- uses free-tier APIs and $5 free Claude credit (~500 briefs).

---

## What It Does

Every morning at 8 AM, you receive an email with:

- AI-generated context summaries for each meeting
- Talking points categorized by type (discussion, follow-up, update)
- Suggested questions to ask
- Priority scoring (high/medium/low) based on meeting type, attendees, and duration
- One-click join links for virtual meetings (Meet, Teams, Zoom)

Works with **all your calendars at once** -- Google Calendar, Outlook, Teams meetings, and manually added events are merged, deduplicated, and prioritized together.

---

## Features

**Multi-Calendar Aggregation**
- Google Calendar (OAuth 2.0, multi-calendar support)
- Outlook Calendar (Microsoft Graph API)
- Microsoft Teams meetings (auto-detected from Outlook)
- **iCal / UniTime** — university course timetables (subscribe via “Copy iCalendar URL” from UniTime Personal Timetable)
- University events discovery (Purdue, via Localist API)
- Manual meeting input via CLI (`--add-meeting`) or web app
- Smart cross-source deduplication (same meeting in multiple sources = one brief)
- **Calendar options** — enable/disable each source in `config.yaml` or in the web app (**Calendars** page)

**AI-Powered Prep Briefs**
- Claude API with category-specific prompts
- Different prompts for 1:1, Team, Client, Interview, Networking, Standup, All-Hands
- Talking points, questions to ask, context notes, preparation time estimates
- Graceful fallbacks when API is unavailable

**Intelligent Processing**
- Filter out noise (focus blocks, OOO, lunch, short events)
- Priority scoring: category (30%), attendees (20%), duration (15%), external attendees (15%), non-recurring (10%), has agenda (10%)
- Sorted highest priority first

**Delivery**
- Beautiful responsive HTML email digest
- Color-coded priority bars (red/orange/green)
- Join meeting buttons
- Daily scheduling via APScheduler (8 AM weekdays)

---

## Quick Start

### Prerequisites
- Python 3.9+
- Claude API key ([sign up for $5 free credit](https://console.anthropic.com))
- Gmail account with App Password for sending emails
- (Optional) Google Calendar credentials
- (Optional) Microsoft Azure app registration for Outlook/Teams

### Installation

```bash
git clone https://github.com/yourusername/meeting-prep-agent.git
cd meeting-prep-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

1. Copy the environment template:
```bash
cp .env.example .env
```

2. Edit `.env` with your credentials:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
EMAIL_SENDER=you@gmail.com
EMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
EMAIL_RECIPIENT=you@gmail.com
```

3. Review `config.yaml` — enable/disable calendar sources:
```yaml
google:
  enabled: true        # Google Calendar
outlook:
  enabled: false      # Outlook + Teams (set true + add OUTLOOK_CLIENT_ID to .env)
ical:
  enabled: true       # iCal / UniTime (add URLs in web app → Calendars)
```
Or use the **web app** → **Calendars** to see all options and add iCal/UniTime URLs.

### Usage

**Web app (browser):**
```bash
python -m src.app
# Open http://127.0.0.1:5000 — run pipeline, add meetings, manage reference docs & notes
```

**CLI:**
```bash
# Add a meeting manually (interactive prompts for title, time, attendees, etc.)
python -m src.main --add-meeting

# List your manual meetings
python -m src.main --list-meetings

# Preview your daily digest (no email sent)
python -m src.main --dry-run

# Run once and send the email
python -m src.main --run

# Start the daily scheduler (runs at 8 AM)
python -m src.main --schedule

# Remove a manual meeting
python -m src.main --remove-meeting <ID>

# Browse Purdue university events and add ones you're interested in
python -m src.main --events

# Browse next 14 days of events
python -m src.main --events --days 14
```

---

## Calendar Setup

### Google Calendar (free)
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project -> Enable "Google Calendar API"
3. Credentials -> OAuth 2.0 Client ID -> Desktop App
4. Download JSON, save as `credentials.json` in project root
5. First run opens browser for authorization

### Outlook + Teams (free)
1. Go to [Azure Portal](https://portal.azure.com) -> App Registrations
2. New Registration -> Name: "Meeting Prep Agent" -> Personal + Org accounts
3. API Permissions -> Add: `Calendars.Read`, `OnlineMeetings.Read`
4. Authentication -> Allow public client flows -> Yes
5. Copy the Application (client) ID to `.env`:
   ```
   OUTLOOK_CLIENT_ID=your-client-id-here
   ```
6. Set `enabled: true` under `outlook:` in `config.yaml`
7. First run shows a device code -- open the URL and enter the code

### Gmail App Password (for sending emails)
1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable 2-Step Verification
3. Search "App Passwords" -> Generate for "Mail"
4. Use the 16-character password as `EMAIL_APP_PASSWORD`

### Reference docs (PDFs / Google Docs – no fluff, right order)
- **Tag a file:** `python -m src.main --tag-doc networking_tips.pdf networking`
- **Paste Google Doc content:** `python -m src.main --add-inline-doc` (paste when prompted)
- **List & order:** `python -m src.main --list-docs` (shows order); reorder with  
  `python -m src.main --reorder-docs interview doc1.pdf doc2.txt`
- **Remove redundancy:** `python -m src.main --detect-redundancy interview` then  
  `python -m src.main --remove-doc <path-or-inline-id>`

### Manual Meetings (no setup needed)
```bash
python -m src.main --add-meeting
# Follow prompts: title, date, time, duration, attendees, description, link
```

### University Events - Purdue (no setup needed)
```bash
python -m src.main --events
# Fetches events from events.purdue.edu
# Shows a numbered list -- pick which ones you want to attend
# Selected events get added to your calendar with AI prep
```
Uses the public Localist API — no credentials required, completely free.

### UniTime (university students / course timetables)
If your school uses **UniTime** for scheduling:
1. Log in to UniTime → **Personal Timetable** → **Export** → **Copy iCalendar URL**.
2. In the **web app** go to **Calendars** → add that URL under “iCal / UniTime”.  
   Or create `ical_sources.json`: `{"subscriptions": [{"url": "PASTE_URL_HERE", "name": "UniTime"}]}`.
3. Ensure `ical.enabled: true` in `config.yaml` (default). Your classes and exams will then be merged into the daily digest with AI prep.
Any other **iCal (.ics) feed URL** (course schedules, event calendars) can be added the same way.

---

## How It Works

```
Google Calendar ──────┐
Outlook Calendar ─────┤
Microsoft Teams ──────┤── Merge ── Filter ── Dedup ── Classify ── Score Priority
University Events ────┤                                    │
Manual Meetings ──────┘                                    │
                                                           ▼
                                                    Claude AI API
                                                    (Category-Aware Briefs)
                                                           │
                                                           ▼
                                                    HTML Email Digest
                                                    (Gmail SMTP @ 8 AM)
```

**Tech Stack:**
- **Python 3.9+** with Pydantic models for type safety
- **Claude API** (Anthropic) for AI brief generation
- **Google Calendar API** (OAuth 2.0) for Google events
- **Microsoft Graph API** for Outlook + Teams events
- **Localist API** for university events (Purdue)
- **APScheduler** for daily cron scheduling
- **Jinja2** for responsive HTML email templates
- **Gmail SMTP** for email delivery

---

## Project Structure

```
src/
  config.py           # Two-layer config (YAML + .env)
  models.py           # Pydantic data models (CalendarEvent -> PrepBrief -> Digest)
  calendar_client.py  # Google Calendar OAuth + event fetching
  outlook_client.py   # Outlook + Teams via Microsoft Graph API
  university_events.py # University event discovery (Purdue Localist API)
  meeting_store.py    # Manual meeting JSON storage + CLI
  event_processor.py  # Filter, dedup, classify, priority score (pure Python)
  ai_briefer.py       # Claude API with category-specific prompts
  email_sender.py     # Gmail SMTP + Jinja2 HTML rendering
  scheduler.py        # APScheduler daily cron trigger
  main.py             # CLI entry point + pipeline orchestration
  templates/
    email_template.html  # Responsive HTML email template
tests/
  test_models.py           # 10 tests - data model validation
  test_event_processor.py  # 17 tests - filtering, dedup, classification, scoring
  test_meeting_store.py    # 12 tests - CRUD, persistence, conversion
  test_ai_briefer.py       # 9 tests  - JSON parsing, fallbacks, mocked API
  test_outlook_client.py   # 13 tests - Graph API parsing, Teams detection
  test_university_events.py # 18 tests - Localist API, event parsing, selection
  test_config.py           # 8 tests  - config loading, defaults, merging
```

---

## Cost

```
Claude API:            $0 first 3-5 months ($5 free credit, ~$0.01/brief)
Google Calendar API:   $0 (free tier - 1M requests/day)
Microsoft Graph API:   $0 (free tier - 10K requests/10 min)
Localist API:          $0 (public API, no auth needed)
Gmail SMTP:            $0
─────────────────────────────────────────
Total:                 $0 to start, ~$2-3/month after free credit
```

---

## Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
# 97 tests, all passing
```

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built with Python + Claude AI. Saves 5+ hours/week of meeting prep.
