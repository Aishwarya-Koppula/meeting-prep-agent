"""
Web app for the AI Meeting Prep Agent.

Run with: python -m src.app
Then open http://127.0.0.1:5000

Uses the same pipeline and stores as the CLI; no logic duplication.
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for, jsonify

from src.config import load_config
from src.main import run_pipeline, _digest_preview_lines
from src.meeting_store import MeetingStore
from src.reference_docs import ReferenceDocsStore
from src.meeting_notes import MeetingNotesStore
from src.ical_client import load_ical_sources, save_ical_sources
from src.university_events import UNIVERSITY_ENDPOINTS
from src.calendar_client import GoogleCalendarClient
from src.outlook_client import OutlookCalendarClient
from src.ical_client import fetch_all_ical_events

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates" / "app"))
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB for uploads

# Global state for Outlook device code auth (web-based flow)
_outlook_auth_state = {"device_code_data": None, "status": "idle", "error": None}
_outlook_auth_lock = threading.Lock()


def _config():
    try:
        return load_config()
    except Exception:
        return None


def _check_outlook_token():
    """Check if a valid Outlook token exists."""
    config = _config()
    if not config or not config.outlook.enabled:
        return False
    token_path = Path(config.outlook.token_path)
    if not token_path.exists():
        return False
    try:
        data = json.loads(token_path.read_text())
        return "access_token" in data or "refresh_token" in data
    except Exception:
        return False


def _check_google_token():
    """Check if a valid Google token exists."""
    config = _config()
    if not config or not config.google.enabled:
        return False
    token_path = Path(config.google.token_path)
    return token_path.exists()


@app.route("/")
def index():
    config = _config()
    google_connected = _check_google_token()
    outlook_connected = _check_outlook_token()
    store = MeetingStore()
    meetings_count = len(store.get_all_meetings())
    return render_template("index.html", config=config,
                           google_connected=google_connected,
                           outlook_connected=outlook_connected,
                           meetings_count=meetings_count)


@app.route("/run", methods=["POST"])
def run():
    dry_run = request.form.get("dry_run") == "1"
    config = _config()
    if not config:
        return render_template("result.html", error="Could not load config (config.yaml + .env)")
    logs = []
    result = run_pipeline(config, dry_run=dry_run, log_collector=logs)
    if result is None:
        digest_dict = None
        preview_lines = []
        email_sent = False
    else:
        digest, email_sent = result
        digest_dict = digest.model_dump(mode="json") if digest else None
        preview_lines = _digest_preview_lines(digest) if digest else []
        if digest_dict and "date" in digest_dict:
            digest_dict["date"] = str(digest_dict["date"])
    return render_template(
        "result.html",
        logs=logs,
        digest=digest_dict,
        preview_lines=preview_lines,
        email_sent=email_sent,
        dry_run=dry_run,
    )


# ── Outlook auth (web-based device code flow) ─────────────────────

@app.route("/auth/outlook/start", methods=["POST"])
def outlook_auth_start():
    """Start the Outlook device code flow and return the code to the browser."""
    config = _config()
    if not config or not config.outlook.enabled:
        return jsonify({"error": "Outlook not enabled in config.yaml"}), 400
    if not config.outlook.client_id:
        return jsonify({"error": "OUTLOOK_CLIENT_ID not set in .env"}), 400

    import requests as req
    tenant = getattr(config.outlook, "tenant_id", "common") or "common"
    auth_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"

    try:
        resp = req.post(
            f"{auth_url}/devicecode",
            data={
                "client_id": config.outlook.client_id,
                "scope": " ".join(config.outlook.scopes),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return jsonify({"error": f"Failed to start auth: {e}"}), 500

    with _outlook_auth_lock:
        _outlook_auth_state["device_code_data"] = data
        _outlook_auth_state["status"] = "pending"
        _outlook_auth_state["error"] = None

    # Start polling in background thread
    thread = threading.Thread(target=_poll_outlook_token, args=(config, data, auth_url), daemon=True)
    thread.start()

    return jsonify({
        "user_code": data.get("user_code"),
        "verification_uri": data.get("verification_uri"),
        "message": data.get("message"),
    })


@app.route("/auth/outlook/status")
def outlook_auth_status():
    """Check if Outlook auth has completed."""
    with _outlook_auth_lock:
        status = _outlook_auth_state["status"]
        error = _outlook_auth_state["error"]
    return jsonify({"status": status, "error": error})


def _poll_outlook_token(config, device_code_data, auth_url):
    """Background thread: poll Microsoft for the token after user authorizes."""
    import time
    import requests as req

    interval = device_code_data.get("interval", 5)
    expires_in = device_code_data.get("expires_in", 900)
    device_code = device_code_data["device_code"]
    start = time.time()

    while time.time() - start < expires_in:
        time.sleep(interval)
        try:
            resp = req.post(
                f"{auth_url}/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": config.outlook.client_id,
                    "device_code": device_code,
                },
                timeout=10,
            )
            data = resp.json()
            if "access_token" in data:
                # Save token
                token_path = Path(config.outlook.token_path)
                token_path.write_text(json.dumps(data, indent=2))
                with _outlook_auth_lock:
                    _outlook_auth_state["status"] = "success"
                return
            elif data.get("error") == "authorization_pending":
                continue
            elif data.get("error") == "slow_down":
                interval += 5
            else:
                with _outlook_auth_lock:
                    _outlook_auth_state["status"] = "error"
                    _outlook_auth_state["error"] = data.get("error_description", data.get("error", "Unknown error"))
                return
        except Exception:
            continue

    with _outlook_auth_lock:
        _outlook_auth_state["status"] = "error"
        _outlook_auth_state["error"] = "Authentication timed out"


# ── Calendars (sources overview + iCal / UniTime) ──────────────────

@app.route("/calendars")
def calendars_list():
    """Show all calendar source options and manage iCal subscriptions."""
    config = _config()
    sources_path = getattr(config.ical, "sources_path", "./ical_sources.json") if config and hasattr(config, "ical") else "./ical_sources.json"
    ical_subs = load_ical_sources(sources_path)
    google_connected = _check_google_token()
    outlook_connected = _check_outlook_token()
    return render_template(
        "calendars.html",
        config=config,
        ical_subscriptions=ical_subs,
        university_endpoints=UNIVERSITY_ENDPOINTS,
        google_connected=google_connected,
        outlook_connected=outlook_connected,
    )


@app.route("/calendars/ical/add", methods=["POST"])
def calendars_ical_add():
    url = request.form.get("url", "").strip()
    name = request.form.get("name", "").strip() or None
    config = _config()
    sources_path = getattr(config.ical, "sources_path", "./ical_sources.json") if config and hasattr(config, "ical") else "./ical_sources.json"
    if not url:
        return redirect(url_for("calendars_list"))
    subs = load_ical_sources(sources_path)
    subs.append({"url": url, "name": name or url[:50]})
    save_ical_sources(subs, sources_path)
    return redirect(url_for("calendars_list"))


@app.route("/calendars/ical/remove", methods=["POST"])
def calendars_ical_remove():
    index_str = request.form.get("index", "")
    config = _config()
    sources_path = getattr(config.ical, "sources_path", "./ical_sources.json") if config and hasattr(config, "ical") else "./ical_sources.json"
    try:
        index = int(index_str)
    except ValueError:
        return redirect(url_for("calendars_list"))
    subs = load_ical_sources(sources_path)
    if 0 <= index < len(subs):
        subs.pop(index)
        save_ical_sources(subs, sources_path)
    return redirect(url_for("calendars_list"))


# ── Meetings ────────────────────────────────────────────────────

@app.route("/meetings")
def meetings_list():
    store = MeetingStore()
    meetings = sorted(store.get_all_meetings(), key=lambda m: m.get("start_time", ""))
    return render_template("meetings.html", meetings=meetings)


@app.route("/meetings/add", methods=["GET", "POST"])
def meetings_add():
    if request.method == "GET":
        return render_template("meeting_form.html", meeting=None, now=datetime.now().strftime("%Y-%m-%d"))
    title = request.form.get("title", "").strip()
    if not title:
        return render_template("meeting_form.html", meeting=None, now=datetime.now().strftime("%Y-%m-%d"), error="Title is required.")
    date_str = request.form.get("date") or datetime.now().strftime("%Y-%m-%d")
    time_str = request.form.get("time", "09:00")
    try:
        start = datetime.fromisoformat(f"{date_str}T{time_str}:00")
    except ValueError:
        return render_template("meeting_form.html", meeting=None, now=datetime.now().strftime("%Y-%m-%d"), error="Invalid date/time.")
    duration = int(request.form.get("duration", 30))
    end = start + timedelta(minutes=duration)
    attendees_str = request.form.get("attendees", "")
    attendees = [a.strip() for a in attendees_str.split(",") if a.strip()]
    store = MeetingStore()
    meeting = store.add_meeting(
        title=title,
        start_time=start,
        end_time=end,
        attendees=attendees,
        description=request.form.get("description") or None,
        location=request.form.get("location") or None,
        meeting_link=request.form.get("meeting_link") or None,
        is_recurring=request.form.get("is_recurring") == "on",
    )
    return redirect(url_for("meetings_list"))


@app.route("/meetings/remove/<mid>", methods=["POST"])
def meetings_remove(mid):
    MeetingStore().remove_meeting(mid)
    return redirect(url_for("meetings_list"))


# ── Reference docs ──────────────────────────────────────────────

@app.route("/docs")
def docs_list():
    store = ReferenceDocsStore()
    data = store.list_all()
    by_category = {k: sorted(v, key=lambda d: d.get("order", 0)) for k, v in (data.get("by_category") or {}).items() if v}
    return render_template("docs.html", by_category=by_category)


@app.route("/docs/tag", methods=["GET", "POST"])
def docs_tag():
    if request.method == "GET":
        return render_template("doc_tag_form.html")
    path = request.form.get("path", "").strip()
    category = request.form.get("category", "").strip().lower()
    label = request.form.get("label", "").strip() or None
    if not path or not category:
        return render_template("doc_tag_form.html", error="Path and category required."), 400
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    store = ReferenceDocsStore()
    if store.tag_to_category(str(p), category, label=label):
        return redirect(url_for("docs_list"))
    return render_template("doc_tag_form.html", error=f"File not found or already tagged: {path}"), 400


@app.route("/docs/inline", methods=["GET", "POST"])
def docs_inline():
    if request.method == "GET":
        return render_template("doc_inline_form.html")
    category = request.form.get("category", "").strip().lower()
    content = request.form.get("content", "").strip()
    label = request.form.get("label", "").strip() or None
    if not category or not content:
        return render_template("doc_inline_form.html", error="Category and content required."), 400
    store = ReferenceDocsStore()
    store.add_inline_doc(category, content, label=label)
    return redirect(url_for("docs_list"))


@app.route("/docs/remove", methods=["POST"])
def docs_remove():
    path_or_id = request.form.get("path_or_id", "").strip()
    if path_or_id:
        ReferenceDocsStore().remove_doc(path_or_id)
    return redirect(url_for("docs_list"))


# ── Meeting notes ───────────────────────────────────────────────

@app.route("/notes")
def notes_list():
    store = MeetingNotesStore()
    notes = sorted(store.get_all_notes(), key=lambda n: n.get("date", ""), reverse=True)
    return render_template("notes.html", notes=notes)


@app.route("/notes/add", methods=["GET", "POST"])
def notes_add():
    if request.method == "GET":
        return render_template("note_form.html", now=datetime.now().strftime("%Y-%m-%d"))
    title = request.form.get("meeting_title", "").strip()
    content = request.form.get("content", "").strip()
    if not title or not content:
        return render_template("note_form.html", now=datetime.now().strftime("%Y-%m-%d"), error="Title and content required."), 400
    attendees_str = request.form.get("attendees", "")
    attendees = [a.strip() for a in attendees_str.split(",") if a.strip()]
    action_items = [x.strip() for x in request.form.get("action_items", "").strip().split("\n") if x.strip()]
    decisions = [x.strip() for x in request.form.get("decisions", "").strip().split("\n") if x.strip()]
    store = MeetingNotesStore()
    store.add_note(
        meeting_title=title,
        content=content,
        attendees=attendees,
        action_items=action_items,
        decisions=decisions,
        date=request.form.get("date") or datetime.now().strftime("%Y-%m-%d"),
    )
    return redirect(url_for("notes_list"))


@app.route("/notes/search")
def notes_search():
    q = request.args.get("q", "").strip()
    if not q:
        return redirect(url_for("notes_list"))
    notes = MeetingNotesStore().search_notes(q)
    return render_template("notes.html", notes=notes, search_query=q)


@app.route("/notes/action-items")
def notes_action_items():
    items = MeetingNotesStore().get_open_action_items()
    return render_template("action_items.html", items=items)


# ── Weekly view ─────────────────────────────────────────────────

@app.route("/week")
def week_view():
    """Show a weekly calendar view (7 days) with events from enabled sources."""
    config = _config()
    if not config:
        return render_template("week.html", days=[], errors=["Could not load config"])

    errors = []
    all_events = []

    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)

    # Google
    if config.google.enabled:
        try:
            g = GoogleCalendarClient(config.google)
            g.authenticate()
            all_events.extend(g.fetch_events(start, end))
        except Exception as e:
            errors.append(f"Google: {e}")

    # Outlook / Teams — only if token exists (no interactive auth in web view)
    if config.outlook.enabled and _check_outlook_token():
        try:
            o = OutlookCalendarClient(config.outlook)
            o.authenticate()
            all_events.extend(o.fetch_events(start, end))
        except Exception as e:
            errors.append(f"Outlook: {e}")
    elif config.outlook.enabled:
        errors.append("Outlook: Not connected yet. Go to Calendars to connect.")

    # iCal subscriptions
    if config.ical.enabled:
        try:
            ical_events = fetch_all_ical_events(lookahead_hours=168, sources_path=config.ical.sources_path)
            all_events.extend(ical_events)
        except Exception as e:
            errors.append(f"iCal: {e}")

    # Manual meetings
    try:
        store = MeetingStore()
        manual = store.to_calendar_events()
        all_events.extend(manual)
    except Exception as e:
        errors.append(f"Manual store: {e}")

    # Normalize and group by day
    def to_simple(ev):
        try:
            start_dt = ev.start_time
            end_dt = ev.end_time
            return {
                "title": ev.title,
                "start": start_dt.strftime("%Y-%m-%dT%H:%M"),
                "end": end_dt.strftime("%Y-%m-%dT%H:%M"),
                "date": start_dt.date().isoformat(),
                "source": getattr(ev, "source", "unknown"),
                "calendar_id": getattr(ev, "calendar_id", ""),
                "location": ev.location or "",
            }
        except Exception:
            return {"title": getattr(ev, "title", "(No title)"), "date": now.date().isoformat(), "start": "", "end": "", "source": "", "calendar_id": "", "location": ""}

    simples = [to_simple(e) for e in all_events]

    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        day_str = d.date().isoformat()
        items = [s for s in simples if s.get("date") == day_str]
        items.sort(key=lambda x: x.get("start") or "")
        days.append({"date": day_str, "dow": dow_names[d.weekday()], "items": items})

    return render_template("week.html", days=days, errors=errors)


def main():
    app.run(host="127.0.0.1", port=5000, debug=True)


if __name__ == "__main__":
    main()
