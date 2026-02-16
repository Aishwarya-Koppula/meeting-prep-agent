# AI Meeting Prep Agent for Students

**Your centralized calendar + AI-powered meeting coach.**

A student-focused web app that aggregates all your calendars in one place, uses AI to classify meetings, generate prep briefs, provide post-meeting coaching, and draft follow-up emails. Built for busy college students juggling classes, interviews, networking, clubs, and part-time work.

**100% free to run** -- uses free-tier APIs and $5 free Claude credit (~500 AI actions).

---

## The Problem

Students have meetings scattered across 5+ calendars (Google, Outlook, iCloud, UniTime, school events), each needing different preparation. An interview needs company research. A networking coffee chat needs talking points. Office hours need specific questions ready. There's no single place that brings it all together and helps you prepare.

## The Solution

**Connect** all your calendars -> **See** everything in one weekly view -> **Classify** each meeting (AI + manual) -> **Prep** with AI-generated briefs -> **Reflect** after meetings -> **Act** on follow-ups.

---

## Features

### Centralized Calendar
- **Google Calendar** (OAuth 2.0)
- **Outlook Calendar** (iCal subscription - works with Purdue/school accounts)
- **iCloud Calendar** (published calendar URL)
- **UniTime** (course timetable .ics export)
- **University Events** (Purdue Localist API)
- **Manual Meetings** (coffee chats, study groups, phone calls)
- Smart cross-source deduplication

### AI Meeting Classification
Categories tuned for student life:
- **Interview** - Technical, behavioral, phone screens
- **Networking** - Coffee chats, informational interviews, mentorship
- **Class** - Lectures, recitations, labs, seminars
- **Office Hours** - Professor/TA meetings
- **Part-time / Work** - Shifts, work meetings
- **Club / Org** - Student orgs, e-board, general body
- **Career Fair** - Recruiting events, info sessions
- **1:1, Team, Client, Standup, All-Hands**

AI auto-classifies from title keywords + manual override in forms.

### AI-Powered Prep Briefs
- Category-specific prompts (interview prep is different from networking prep)
- Auto-injects reference docs and past meeting notes
- Talking points, suggested questions, context notes
- Priority scoring based on category, attendees, duration, and more

### Post-Meeting Reflection
- Log "What went well" and "What didn't go well" after each meeting
- **AI Coaching** -- get personalized tips based on your reflection
- Track improvement over time

### Follow-Up Email Drafts
- One-click AI-generated follow-up emails from meeting notes
- Summarizes decisions, action items, and next steps
- Professional tone, ready to send

### Person Lookup
- Add LinkedIn URL and context notes for key people in meetings
- AI personalizes prep based on who you're meeting with

### Action Items Dashboard
- Track pending tasks from all meetings in one place
- Mark items complete with one click
- See completed vs pending at a glance
- Category badges for context

### Beautiful Web App
- Colorful, student-friendly UI (purple/pink theme, Inter font)
- Weekly calendar view with color-coded sources
- Mobile-responsive design
- No terminal required -- everything through the browser

---

## Quick Start

### Prerequisites
- Python 3.9+
- Claude API key ([sign up for $5 free credit](https://console.anthropic.com))

### Installation

```bash
git clone https://github.com/Aishwarya-Koppula/meeting-prep-agent.git
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
```

3. Review `config.yaml` -- enable/disable calendar sources:
```yaml
google:
  enabled: true        # Google Calendar
outlook:
  enabled: false       # Outlook Graph API (requires admin consent for .edu)
ical:
  enabled: true        # iCal subscriptions (Outlook, iCloud, UniTime)
```

### Run

```bash
python3 -m src.app
# Open http://127.0.0.1:5000
```

---

## Calendar Setup

### Google Calendar (free)
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project -> Enable "Google Calendar API"
3. Credentials -> OAuth 2.0 Client ID -> Desktop App
4. Download JSON, save as `credentials.json` in project root
5. Add yourself as a test user in OAuth consent screen
6. First run opens browser for authorization

### Outlook Calendar (via iCal - recommended for .edu)
1. Open Outlook on the web (outlook.office365.com)
2. Settings -> Calendar -> Shared calendars -> Publish a calendar
3. Copy the ICS link
4. In the web app: Calendars -> Add iCal subscription with the URL

> **Why iCal instead of Graph API?** School Azure accounts (like Purdue) require admin consent for third-party apps. The iCal published link works without any admin approval and syncs every ~30 minutes.

### iCloud Calendar
1. Open Calendar app on Mac -> Right-click a calendar -> Share Calendar
2. Check "Public Calendar" and copy the URL (starts with `webcal://`)
3. In the web app: Calendars -> Add iCal subscription
   - Replace `webcal://` with `https://`

### UniTime (course timetable)
1. Log in to your university's UniTime
2. Personal Timetable -> Export -> Copy iCalendar URL
3. In the web app: Calendars -> Add iCal subscription

### Claude API Key
1. Go to [Anthropic Console](https://console.anthropic.com/settings/keys)
2. Sign up for $5 free credit (~500 AI actions)
3. Create an API key and add to `.env`

### Gmail App Password (optional, for email digest)
1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable 2-Step Verification
3. Search "App Passwords" -> Generate for "Mail"
4. Use the 16-character password as `EMAIL_APP_PASSWORD`

---

## How It Works

```
                        CONNECT
Google Calendar ──────┐
Outlook (iCal) ───────┤
iCloud Calendar ──────┤── Merge ── Filter ── Dedup
UniTime Schedule ─────┤
University Events ────┤
Manual Meetings ──────┘
                         │
                    CLASSIFY & PREP
                         │
              ┌──────────v──────────┐
              │  AI Classification  │
              │  (Interview, Class, │
              │   Networking, etc.) │
              └──────────┬──────────┘
                         │
              ┌──────────v──────────┐
              │  Claude AI Briefs   │
              │  + Reference Docs   │
              │  + Past Notes       │
              │  + Person Context   │
              └──────────┬──────────┘
                         │
                    REFLECT & ACT
                         │
              ┌──────────v──────────┐
              │  Post-Meeting       │
              │  - Reflection       │
              │  - AI Coaching      │
              │  - Follow-up Draft  │
              │  - Action Items     │
              └─────────────────────┘
```

---

## Workflow

| Step | What | Where |
|------|-------|-------|
| 1. Connect | Link all your calendars | Calendars page |
| 2. See | View unified weekly schedule | Weekly View |
| 3. Classify | AI auto-classifies + manual override | Auto + Meeting form |
| 4. Prep | Run AI pipeline for meeting briefs | Home -> Run Pipeline |
| 5. Reflect | Log what went well/poorly | Notes -> Add Note |
| 6. Act | Track action items + send follow-ups | Action Items + Notes |

---

## Tech Stack

- **Python 3.9+** with Pydantic models
- **Flask** web app with Jinja2 templates
- **Claude API** (Anthropic) for AI generation
- **Google Calendar API** (OAuth 2.0)
- **Microsoft Graph API** (optional, for Outlook)
- **iCal / .ics** subscriptions for Outlook, iCloud, UniTime
- **Localist API** for university events
- **APScheduler** for daily scheduling

---

## Project Structure

```
src/
  app.py              # Flask web app (browser UI)
  main.py             # CLI entry point + pipeline
  config.py           # Two-layer config (YAML + .env)
  models.py           # Pydantic data models (13 meeting categories)
  calendar_client.py  # Google Calendar OAuth
  outlook_client.py   # Outlook + Teams via Microsoft Graph
  ical_client.py      # iCal .ics subscriptions
  university_events.py # University events (Purdue Localist API)
  meeting_store.py    # Manual meeting storage (category, person lookup)
  event_processor.py  # Filter, dedup, classify, score
  ai_briefer.py       # Claude API with category-specific prompts
  meeting_notes.py    # Notes + reflection + follow-ups + action items
  reference_docs.py   # PDF/text/inline doc tagging
  email_sender.py     # Gmail SMTP + HTML email
  scheduler.py        # APScheduler daily cron
  templates/
    email_template.html  # HTML email template
    app/                 # 13 web app templates (colorful student theme)
tests/
  97 tests covering models, processing, storage, AI, and integrations
```

---

## CLI Commands

```bash
# Web app (recommended)
python3 -m src.app

# Pipeline
python3 -m src.main --dry-run     # Preview digest (no email)
python3 -m src.main --run         # Run pipeline + send email
python3 -m src.main --schedule    # Start daily scheduler (8 AM)

# Meetings
python3 -m src.main --add-meeting
python3 -m src.main --list-meetings
python3 -m src.main --remove-meeting <ID>

# University events
python3 -m src.main --events

# Reference docs
python3 -m src.main --tag-doc resume.pdf interview
python3 -m src.main --add-inline-doc
python3 -m src.main --list-docs

# Meeting notes
python3 -m src.main --add-note
python3 -m src.main --list-notes
python3 -m src.main --search-notes "budget"
python3 -m src.main --action-items
```

---

## Cost

```
Claude API:            $0 first 3-5 months ($5 free credit, ~$0.01/brief)
Google Calendar API:   $0 (free tier)
Microsoft Graph API:   $0 (free tier)
Localist API:          $0 (public API)
Gmail SMTP:            $0
────────────────────────────────────────────────
Total:                 $0 to start, ~$2-3/month after free credit
```

---

## Running Tests

```bash
source .venv/bin/activate
python3 -m pytest tests/ -v
# 97 tests, all passing
```

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built with Python + Claude AI for students who refuse to walk into meetings unprepared.
