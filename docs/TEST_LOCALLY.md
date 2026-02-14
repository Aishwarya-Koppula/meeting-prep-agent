# How to test on your local machine

## 1. One-time setup

From the project root:

```bash
cd meeting-prep-agent
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at least:

- **ANTHROPIC_API_KEY** – required for AI briefs ([get one](https://console.anthropic.com/settings/keys), $5 free credit).
- **EMAIL_SENDER**, **EMAIL_APP_PASSWORD**, **EMAIL_RECIPIENT** – required only if you want to test sending the real email (e.g. with `--run`). For **dry-run** you can leave them as placeholders.

Optional for calendar:

- **Google Calendar:** Download `credentials.json` from Google Cloud Console, put it in the project root. First run will open a browser to sign in.
- **Outlook:** Set `OUTLOOK_CLIENT_ID` in `.env` and `outlook.enabled: true` in `config.yaml`.

---

## 2. Run the web app (optional)

Use the browser instead of the CLI:

```bash
source .venv/bin/activate
python -m src.app
```

Open **http://127.0.0.1:5000**. You can:

- **Home:** Run the pipeline (preview or send email)
- **Meetings:** Add / remove manual meetings
- **Reference docs:** Tag files or paste content (e.g. Google Doc) by category
- **Notes:** Add notes, search, view action items

Same data as the CLI (same `meetings.json`, `reference_docs.json`, `meeting_notes.json`).

---

## 3. Test without calendar (recommended first)

Add one manual meeting, then run the pipeline in **dry-run** (no email sent):

```bash
# Activate venv if you haven’t
source .venv/bin/activate

# Add a fake meeting (answer the prompts)
python -m src.main --add-meeting
# e.g. Title: Test 1:1, Date: today, Time: 10:00, Duration: 30, rest optional

# Run the full pipeline but only preview (no email)
python -m src.main --dry-run
```

You should see:

1. Fetching events (manual meeting listed)
2. Processing (filter, dedup, priority)
3. AI briefs generated via Claude
4. A text preview of the digest and a file `digest_preview.json`

If that works, the app and Claude are wired correctly.

---

## 4. Test with your calendar

If you have `credentials.json` and `google.enabled: true` in `config.yaml`:

```bash
python -m src.main --dry-run
```

You’ll see events from Google Calendar in step 1. No email is sent.

---

## 5. Test sending the real email

Only after dry-run looks good:

```bash
python -m src.main --run
```

Requires valid `EMAIL_SENDER`, `EMAIL_APP_PASSWORD`, and `EMAIL_RECIPIENT` in `.env`. You should get the digest at `EMAIL_RECIPIENT`.

---

## 6. Test reference docs and notes (no email)

```bash
# List tagged docs (empty at first)
python -m src.main --list-docs

# Add pasted content (e.g. from a Google Doc)
python -m src.main --add-inline-doc

# List notes, search, export
python -m src.main --list-notes
python -m src.main --search-notes "test"
python -m src.main --export-notes
```

Then run `--dry-run` again; if you tagged a doc to the same category as your test meeting, the brief should reflect that content.

---

## 7. Run the unit tests

```bash
source .venv/bin/activate
pip install -r requirements.txt   # includes pytest
python -m pytest tests/ -v
```

All tests should pass. This does not call Claude or send email.

---

## Quick reference

| Goal                    | Command                          |
|-------------------------|-----------------------------------|
| Preview only (no email) | `python -m src.main --dry-run`   |
| Add a test meeting      | `python -m src.main --add-meeting` |
| Run and send email      | `python -m src.main --run`       |
| Run web app             | `python -m src.app` → http://127.0.0.1:5000 |
| Run unit tests          | `python -m pytest tests/ -v`     |

Start with **dry-run** after **add-meeting**; that’s enough to confirm everything works locally.
