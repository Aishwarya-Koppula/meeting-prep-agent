# Product Requirements Document (PRD)  
# AI Meeting Prep Agent

**Version:** 1.0  
**Status:** Implemented  
**Last updated:** 2026-02

---

## 1. Product overview

### 1.1 Vision

**Never walk into a meeting unprepared again.**

The AI Meeting Prep Agent is an automated meeting-intelligence system that aggregates events from multiple calendar sources, generates AI-powered preparation briefs (via Claude), and delivers a single prioritized daily digest to the user’s inbox. Users can attach reference materials (PDFs, Google Docs) and reuse past meeting notes so prep is specific, ordered, and free of fluff.

### 1.2 One-line summary

Automated meeting prep: multi-calendar aggregation → filter/dedup/prioritize → Claude briefs → morning email digest; supports reference docs, meeting notes reuse, and multiple calendar options (Google, Outlook, manual, iCal/UniTime, university events).

### 1.3 Problem statement

- **Fragmented calendars:** Work (Google/Outlook/Teams), university (UniTime, campus events), and ad-hoc meetings live in different places; no single view of “today’s meetings” with prep.
- **Generic prep:** Generic tips don’t help; users need talking points and questions tailored to each meeting type (1:1, client, interview, etc.) and to their own reference materials.
- **Wasted context:** Past meeting notes and personal playbooks (interview tips, networking guides) are underused when preparing for similar or recurring meetings.
- **Time cost:** Manually prepping for multiple meetings each day is time-consuming and inconsistent.

### 1.4 Solution

A single pipeline that:

1. **Ingests** events from all configured sources (Google, Outlook, manual, iCal/UniTime, university events).
2. **Processes** them (filter noise, deduplicate, classify, score priority).
3. **Enriches** each event with AI-generated briefs (Claude), optionally using tagged reference docs and past meeting notes.
4. **Delivers** one daily digest (e.g. 8 AM) via email or preview (CLI/web), with join links and priority ordering.

Users can manage calendar options, reference docs (tag, order, remove redundancy), and meeting notes (add, search, export) via CLI or web app.

---

## 2. Goals and success criteria

### 2.1 Goals

| Goal | Description |
|------|-------------|
| **G1. Single daily view** | User receives one digest with all relevant meetings for the day, regardless of calendar source. |
| **G2. Actionable prep** | Every meeting has a brief with specific talking points, suggested questions, and context notes (no generic fluff). |
| **G3. Personal context** | Prep can use user’s reference materials (PDFs, pasted docs) and past meeting notes, in a controlled order. |
| **G4. Multi-audience** | Serves professionals (Google/Outlook), students (UniTime, campus events), and ad-hoc users (manual meetings). |
| **G5. Low-friction run** | Usable via CLI and web app; minimal config for “preview only”; free-tier APIs + small Claude cost. |

### 2.2 Success metrics

| Metric | Target |
|--------|--------|
| **Coverage** | All enabled calendar sources contribute to the digest; dedup avoids duplicate briefs for the same meeting. |
| **Prep quality** | Briefs are category-aware (1:1, team, client, interview, networking, standup, all-hands) and reference user docs when tagged. |
| **Reliability** | Pipeline runs on schedule or on-demand; graceful fallback when Claude is unavailable. |
| **Adoption** | One person can go from clone → first digest (dry-run) in &lt; 15 minutes with minimal setup. |

---

## 3. User personas

| Persona | Need | How the product helps |
|---------|------|------------------------|
| **Busy professional** | One place to see all meetings (work + personal) and get prep. | Multi-calendar merge, single morning email, priority order, join links. |
| **University student** | Prep for classes and campus events; use UniTime schedule. | iCal/UniTime subscription, university events (e.g. Purdue), manual meetings. |
| **Job seeker / networker** | Strong prep for interviews and coffee chats using own playbooks. | Reference docs (tagged to interview/networking), category-specific prompts, no fluff. |
| **Recurring-meeting lead** | Build on last time (notes, decisions, action items). | Meeting notes with reuse for similar title/attendees; action items view. |
| **Privacy-minded user** | Run locally, own data, no SaaS sign-up. | Self-hosted CLI + web app; data in local JSON files; config in YAML + .env. |

---

## 4. Functional requirements

### 4.1 Calendar aggregation (FR-CAL)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-CAL-1 | Ingest events from Google Calendar (OAuth 2.0, configurable calendar IDs). | Must |
| FR-CAL-2 | Ingest events from Microsoft Outlook and Teams (Microsoft Graph API). | Must |
| FR-CAL-3 | Support manually added meetings (stored locally; included in pipeline). | Must |
| FR-CAL-4 | Support iCal/ICS subscription URLs (e.g. UniTime “Copy iCalendar URL”). | Must |
| FR-CAL-5 | Support university events (at least one preconfigured source, e.g. Purdue Localist); user can add selected events to their calendar (manual store). | Should |
| FR-CAL-6 | Merge events from all enabled sources; deduplicate same meeting across sources. | Must |
| FR-CAL-7 | Allow enabling/disabling each source (Google, Outlook, iCal) via config; expose “calendar options” in web app (view status, manage iCal URLs). | Must |

### 4.2 Event processing (FR-PROC)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-PROC-1 | Filter out noise (e.g. all-day, cancelled, short events, OOO, focus blocks) per config. | Must |
| FR-PROC-2 | Classify each event (1:1, team, client, interview, networking, standup, all-hands, other). | Must |
| FR-PROC-3 | Assign priority (high/medium/low) from category, attendees, duration, external attendees, recurrence, agenda. | Must |
| FR-PROC-4 | Sort events by priority for digest order. | Must |

### 4.3 AI prep briefs (FR-AI)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-AI-1 | Generate a prep brief per event using Claude API: summary, talking points (with category), suggested questions, context notes, preparation time. | Must |
| FR-AI-2 | Use category-specific prompts (different guidance for 1:1, interview, client, etc.). | Must |
| FR-AI-3 | Inject tagged reference doc content into the prompt when category (or meeting) matches; respect doc order. | Must |
| FR-AI-4 | Inject relevant past meeting notes (matched by title/attendees) into the prompt. | Must |
| FR-AI-5 | Enforce “no fluff” in system and user prompts (concise, specific, actionable). | Must |
| FR-AI-6 | On Claude API failure, return a minimal fallback brief (no rich talking points). | Must |

### 4.4 Reference docs (FR-DOC)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-DOC-1 | Allow tagging a file (PDF, .txt, .md) to a meeting category. | Must |
| FR-DOC-2 | Allow adding “inline” content (e.g. pasted from Google Doc) tagged to a category. | Must |
| FR-DOC-3 | Support ordering docs per category (order used when injecting into prompt). | Must |
| FR-DOC-4 | Provide redundancy detection (similar content within a category) and allow removing a doc from all tags. | Should |
| FR-DOC-5 | Extract text from PDFs (e.g. PyPDF2); truncate per-doc content for prompt size. | Must |

### 4.5 Meeting notes (FR-NOTES)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-NOTES-1 | Allow adding a meeting note (title, content, attendees, action items, decisions, date). | Must |
| FR-NOTES-2 | Reuse notes automatically for future events with matching/similar title or attendees. | Must |
| FR-NOTES-3 | Support searching notes by keyword and listing open action items. | Must |
| FR-NOTES-4 | Support exporting all notes (e.g. JSON) for backup or external reuse. | Should |

### 4.6 Delivery (FR-DELIV)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-DELIV-1 | Send digest by email (HTML, responsive) with configurable subject and recipient. | Must |
| FR-DELIV-2 | Support “dry run” (preview only, no email). | Must |
| FR-DELIV-3 | Include per-meeting: title, time, join link, priority, summary, talking points, questions, context notes. | Must |
| FR-DELIV-4 | Support scheduled daily run (e.g. 8 AM weekdays) via in-process scheduler; time and timezone configurable. | Must |

### 4.7 Interfaces (FR-UI)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-UI-1 | CLI: run pipeline (--run, --dry-run), schedule (--schedule), add/list/remove meetings, tag/list/reorder/remove docs, add/list/search/export notes, browse university events, manage iCal (via file or future CLI). | Must |
| FR-UI-2 | Web app: dashboard (run/preview), meetings (list, add, remove), reference docs (list, tag file, paste inline, remove), notes (list, add, search, action items, export), calendars (view source status, add/remove iCal URLs). | Must |
| FR-UI-3 | Same data stores for CLI and web app (meetings.json, reference_docs.json, meeting_notes.json, ical_sources.json). | Must |

---

## 5. Non-functional requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | **Config:** Non-secret settings in config.yaml; secrets in .env; no secrets in repo. |
| NFR-2 | **Cost:** Designed to run on free-tier calendar APIs and ~$5 Claude credit for hundreds of briefs; no required paid SaaS. |
| NFR-3 | **Data:** All user data (meetings, notes, reference doc metadata, iCal URLs) stored locally in JSON; no telemetry or external analytics. |
| NFR-4 | **Resilience:** Missing or failing calendar source does not block pipeline; Claude failure yields fallback brief. |
| NFR-5 | **Run environment:** Python 3.9+; runnable locally or on a server (e.g. cron or long-lived process for scheduler). |

---

## 6. Out of scope / limitations

The following are explicitly **out of scope** for v1 (or limitations):

| Item | Description |
|------|-------------|
| **Create/edit calendar events** | Read-only; no writing back to Google/Outlook. Manual meetings are local only. |
| **Non-Gmail email** | Delivery is Gmail SMTP; other providers require config/code change. |
| **Run without Claude** | No full-quality briefs without Claude; only minimal fallback. |
| **Sync notes to calendars/tasks** | Notes stay in-app; no push to Google Tasks, Outlook, etc. |
| **Native Apple Calendar / CalDAV** | Not built-in; user can add an .ics feed as iCal subscription if available. |
| **Team/shared calendar auth** | Per-user OAuth only; no shared or bot-account calendar support. |
| **Recording/transcription** | No meeting recording or live transcription; notes are manual. |
| **Toggle Google/Outlook in UI** | Calendars page shows status and iCal URLs; Google/Outlook on/off via config.yaml. |
| **Real-time calendar updates** | Events fetched at run time (e.g. 8 AM); no live push. |
| **Every university API** | Only preconfigured Localist (e.g. Purdue); others via .ics or custom integration. |

---

## 7. Dependencies and constraints

### 7.1 External dependencies

- **Anthropic Claude API** — prep brief generation.
- **Google Calendar API** (optional) — OAuth + read events.
- **Microsoft Graph API** (optional) — Outlook/Teams events.
- **Gmail SMTP** — send digest email.
- **Localist API** (optional) — university events (e.g. Purdue).
- **UniTime / iCal feeds** (optional) — user-supplied URLs.

### 7.2 Technical stack

- Python 3.9+
- Pydantic (models, settings), PyYAML, python-dotenv
- Flask (web app), Jinja2 (templates + email)
- APScheduler, pytz (scheduling)
- icalendar (iCal parsing), PyPDF2 (PDF text), requests (HTTP)

### 7.3 Constraints

- Single-user use (one .env, one set of credentials per run).
- No built-in auth for the web app (assume local/trusted network or add reverse proxy auth separately).

---

## 8. Appendix

### 8.1 Glossary

| Term | Meaning |
|------|--------|
| **Digest** | Single email (or preview) containing all prep briefs for the day. |
| **Brief** | Per-meeting AI output: summary, talking points, questions, context notes. |
| **Category** | Meeting type: 1:1, team, client, interview, networking, standup, all-hands, other. |
| **Reference doc** | File or pasted content tagged to a category and optionally ordered. |
| **iCal subscription** | URL that returns an .ics feed (e.g. UniTime personal timetable). |

### 8.2 Document references

- **README.md** — Quick start, features, setup.
- **docs/USE_CASES_AND_OPERATIONS.md** — Use cases, failure modes, run locally, deploy, limitations.
- **docs/TEST_LOCALLY.md** — Step-by-step local testing.
- **config.yaml** — Calendar and pipeline configuration.

### 8.3 Revision history

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02 | Initial PRD reflecting implemented product (multi-calendar, reference docs, notes, UniTime, web app, calendar options). |
