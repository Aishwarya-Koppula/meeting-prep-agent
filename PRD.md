# Product Requirements Document (PRD)
## AI Meeting Prep Agent for Students

**Version:** 2.0
**Last Updated:** February 2026
**Author:** Aishwarya Koppula

---

## 1. Product Vision

An intelligent meeting preparation platform designed for college students. It aggregates all calendar sources, uses AI to classify meetings by type, generates personalized prep briefs, provides post-meeting coaching, and tracks action items -- all through a beautiful, student-friendly web interface.

**Tagline:** Your centralized calendar + AI-powered meeting coach.

---

## 2. Target User

- **Primary:** College students (especially CS/engineering students at Purdue)
- **Use cases:** Juggling interviews, networking events, classes, office hours, club meetings, part-time work, and career fairs
- **Pain point:** 5+ calendar sources, each needing different preparation, with no single unified view

---

## 3. User Workflow

```
Connect -> See -> Classify -> Prep -> Reflect -> Act
```

| Step | Action | Interface |
|------|--------|-----------|
| Connect | Link Google, Outlook, iCloud, UniTime calendars | Calendars page |
| See | View all events in unified weekly grid | Weekly View |
| Classify | AI auto-classifies + manual category override | Automatic + Forms |
| Prep | Generate AI briefs with category-specific prompts | Home -> Run Pipeline |
| Reflect | Log what went well/poorly, get AI coaching tips | Notes -> Add Note |
| Act | Track action items, generate follow-up emails | Action Items + Notes |

---

## 4. Features & Implementation Status

### 4.1 Calendar Aggregation (DONE)

| Source | Method | Status |
|--------|--------|--------|
| Google Calendar | OAuth 2.0 | Done |
| Outlook Calendar | iCal subscription (workaround for .edu admin consent) | Done |
| Microsoft Teams | Auto-detected from Outlook via Calendars.Read | Done |
| iCloud Calendar | Published calendar URL | Done |
| UniTime | .ics export URL | Done |
| University Events (Purdue) | Localist API | Done |
| Manual Meetings | JSON store + web form | Done |

**Key decisions:**
- Outlook uses iCal instead of Graph API because Purdue IT requires admin consent for third-party apps
- iCloud uses published calendar URL (webcal:// converted to https://)
- Smart deduplication: same title + start time within 5 min = single event

### 4.2 Meeting Classification (DONE)

**13 categories** tuned for student life:

| Category | Keywords | Priority Weight |
|----------|----------|----------------|
| Interview | interview, screening, hiring, behavioral, technical round | 1.0 |
| Career Fair | career fair, job fair, recruiting event, info session | 0.95 |
| Client | client, customer, external, vendor | 0.9 |
| Networking | networking, coffee chat, meet & greet, informational | 0.7 |
| 1:1 | 1:1, 1-1, one on one | 0.7 |
| Office Hours | office hours, professor, instructor, TA | 0.65 |
| Team | 3+ attendees | 0.5 |
| Club | club, org meeting, e-board, general body | 0.45 |
| Class | lecture, class, recitation, lab, seminar | 0.4 |
| Other | default | 0.4 |
| Part-time | shift, part-time, work schedule | 0.35 |
| All-Hands | all-hands, town hall | 0.3 |
| Standup | standup, daily sync | 0.2 |

**Classification approach:** Keyword matching on event title + manual override in web forms.

### 4.3 AI Prep Briefs (DONE)

- Claude API (Anthropic) with category-specific system prompts
- Each category has tailored guidance (e.g., Interview: STAR examples, Networking: conversation starters)
- Auto-injects relevant reference docs and past meeting notes
- Output: summary, talking points, suggested questions, context notes, prep time estimate
- Graceful fallback when API unavailable

### 4.4 Post-Meeting Reflection (DONE)

- "What went well?" and "What didn't go well?" fields in note form
- Stored with meeting notes for future reference
- Visual display: green card for positive, red card for improvements

### 4.5 AI Coaching (DONE)

- POST endpoint: `/notes/<id>/ai-coaching`
- Analyzes went_well and went_poorly fields
- Returns 2-3 personalized, actionable coaching tips
- Student-friendly tone

### 4.6 Follow-Up Email Drafts (DONE)

- POST endpoint: `/notes/<id>/generate-followup`
- Generates professional follow-up email from meeting notes
- Includes: thank you, decisions summary, action items, next steps
- Saved to note record for future reference

### 4.7 Person Lookup (DONE)

- LinkedIn URL field in meeting form
- Person notes field (role, company, context)
- Displayed in meetings list with LinkedIn link
- Available for AI to personalize prep briefs

### 4.8 Action Items Dashboard (DONE)

- Flat list across all meeting notes
- Mark items complete with one click
- Separate pending vs completed sections
- Category badges for context
- Completion state persisted via `completed_actions` array in notes

### 4.9 Web App UI (DONE)

- Colorful student theme (purple/pink gradients, Inter font)
- 13 template pages
- Sidebar navigation with emoji icons
- Category-specific color badges
- Mobile-responsive grid layouts
- AJAX-based AI features (coaching, follow-ups load without page refresh)

---

## 5. Priority Scoring Algorithm

Score is 0.0-1.0 based on weighted factors:

| Factor | Weight | Details |
|--------|--------|---------|
| Category | 0.30 | Interview=1.0, Career Fair=0.95, Client=0.9, ... |
| Attendee count | 0.20 | Scaled 0-10 attendees |
| Duration | 0.15 | Scaled 0-60 minutes |
| External attendees | 0.15 | Different email domain than organizer |
| Non-recurring | 0.10 | One-off meetings need more prep |
| Has agenda | 0.10 | Description > 20 chars |

**Priority levels:**
- HIGH: score >= 0.6
- MEDIUM: score >= 0.35
- LOW: score < 0.35

---

## 6. Technical Architecture

### Data Pipeline
```
CalendarEvent -> ProcessedEvent -> PrepBrief -> DailyDigest
```

### Key Components
- **Flask** web server (port 5000)
- **Pydantic** models for type safety
- **JSON** file storage (meetings.json, meeting_notes.json, ical_sources.json)
- **Claude API** for AI generation (briefs, coaching, follow-ups)
- **APScheduler** for daily automation (8 AM)

### API Endpoints (Web App)

| Method | Path | Purpose |
|--------|------|---------|
| GET | / | Home dashboard |
| POST | /run | Run AI prep pipeline |
| GET | /week | Weekly calendar view |
| GET | /calendars | Calendar sources management |
| POST | /calendars/ical/add | Add iCal subscription |
| GET | /meetings | Manual meetings list |
| POST | /meetings/add | Add manual meeting |
| GET | /notes | Meeting notes list |
| POST | /notes/add | Add meeting note |
| POST | /notes/{id}/generate-followup | AI follow-up draft |
| POST | /notes/{id}/ai-coaching | AI coaching tips |
| GET | /notes/action-items | Action items dashboard |
| POST | /notes/action-items/complete | Mark action complete |
| GET | /docs | Reference docs list |
| POST | /auth/outlook/start | Start Outlook auth |
| GET | /auth/outlook/status | Check Outlook auth |

---

## 7. Future Roadmap

### Phase 1 (Current) - DONE
- Multi-calendar aggregation
- AI classification (13 categories)
- AI prep briefs with category-specific prompts
- Post-meeting reflection + AI coaching
- Follow-up email drafts
- Person lookup
- Action items with completion tracking
- Colorful student web app

### Phase 2 (Next)
- Browser push notifications for upcoming meetings
- Calendar event creation from web app
- Recurring reflection tracking (improvement over time)
- AI-generated agenda from meeting description
- Integration with university career services (Handshake)

### Phase 3 (Future)
- Mobile app (React Native or Flutter)
- Slack/Discord delivery channel
- LinkedIn API integration for automatic person lookup
- Group study session coordination
- Resume/cover letter tailoring per interview

---

## 8. Cost Analysis

All services used are free or have generous free tiers:

| Service | Cost | Capacity |
|---------|------|----------|
| Claude API | $5 free credit | ~500 AI actions |
| Google Calendar API | Free | 1M requests/day |
| Microsoft Graph API | Free | 10K requests/10 min |
| Localist API | Free | Public, no auth |
| Gmail SMTP | Free | 500 emails/day |
| **Total** | **$0 to start** | **~$2-3/month after credits** |

---

## 9. Testing

- **97 tests** across 7 test files
- Coverage: models, event processing, meeting storage, AI briefer, Outlook parsing, university events, config loading
- Pure Python event_processor.py has the most tests (17) -- no external dependencies
- Run: `python3 -m pytest tests/ -v`
