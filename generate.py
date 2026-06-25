import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv(".env.local")

FOOTBALL_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
CALENDAR_ID = os.environ["GOOGLE_CALENDAR_ID"]
CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]

TOURNAMENT_START = date(2026, 6, 11)
TOURNAMENT_END = date(2026, 7, 19)

MATCH_DURATION = timedelta(minutes=150)

STAGE_LABELS = {
    "GROUP_STAGE":   "Group Stage",
    "LAST_32":       "Round of 32",
    "LAST_16":       "Round of 16",
    "QUARTER_FINALS":"Quarterfinal",
    "SEMI_FINALS":   "Semifinal",
    "THIRD_PLACE":   "Third Place",
    "FINAL":         "Final",
}


# ── Google Calendar ──────────────────────────────────────────────────────────

def gcal_service():
    info = json.loads(CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def upsert_event(service, event: dict) -> None:
    eid = event["id"]
    try:
        service.events().patch(calendarId=CALENDAR_ID, eventId=eid, body=event).execute()
    except HttpError as e:
        if e.resp.status == 404:
            service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        else:
            raise


# ── Football data ────────────────────────────────────────────────────────────

def fetch_matches() -> list[dict]:
    r = requests.get(
        "https://api.football-data.org/v4/competitions/WC/matches",
        headers={"X-Auth-Token": FOOTBALL_API_KEY},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["matches"]


def load_bracket() -> dict:
    with open(Path(__file__).parent / "bracket.json") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ── Event builders ───────────────────────────────────────────────────────────

def event_summary(match: dict, bracket: dict) -> str:
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    if home and away:
        return f"{home} vs {away}"
    fallback = bracket.get(str(match["id"]))
    if fallback:
        return f"{fallback['home']} vs {fallback['away']}"
    return f"{STAGE_LABELS.get(match['stage'], match['stage'])} — TBD vs TBD"


def event_description(match: dict) -> str:
    parts = [STAGE_LABELS.get(match["stage"], match["stage"])]

    if match.get("group"):
        parts.append(match["group"].replace("GROUP_", "Group "))

    score = match["score"]
    status = match["status"]

    if status in ("IN_PLAY", "PAUSED") and score["halfTime"]["home"] is not None:
        h, a = score["halfTime"]["home"], score["halfTime"]["away"]
        parts.append(f"HT: {h}–{a}")

    if status == "FINISHED" and score["fullTime"]["home"] is not None:
        home = match["homeTeam"]["name"] or "Home"
        away = match["awayTeam"]["name"] or "Away"
        h, a = score["fullTime"]["home"], score["fullTime"]["away"]
        result = f"FT: {home} {h}–{a} {away}"
        if score["duration"] == "EXTRA_TIME":
            result += " (AET)"
        elif score["duration"] == "PENALTY_SHOOTOUT":
            result += " (Pens)"
        parts.append(result)

    return " · ".join(parts)


def build_gcal_event(match: dict, bracket: dict) -> dict:
    start = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
    end = start + MATCH_DURATION
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return {
        # Google Calendar event IDs must match [a-v0-9]{5,1024}
        "id": f"wc2026{match['id']}",
        "summary": event_summary(match, bracket),
        "description": event_description(match),
        "start": {"dateTime": start.strftime(fmt), "timeZone": "UTC"},
        "end":   {"dateTime": end.strftime(fmt),   "timeZone": "UTC"},
    }


# ── Self-modifying cron ──────────────────────────────────────────────────────

def compute_cron(matches: list[dict]) -> str | None:
    today = datetime.now(timezone.utc).date()

    if today > TOURNAMENT_END:
        # Tournament is over — remove the schedule trigger entirely.
        return None

    match_dates = {
        datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).date()
        for m in matches
    }
    tomorrow = today + timedelta(days=1)

    if today in match_dates or tomorrow in match_dates:
        return "*/30 * * * *"   # Active match period: every 30 min

    return "0 */3 * * *"        # Tournament but quiet day: every 3 hours


def update_workflow_cron(cron: str | None) -> bool:
    """
    Rewrites the schedule trigger in update.yml.
    If cron is None (tournament over), removes the schedule block so the
    workflow only fires on workflow_dispatch and goes dormant.
    Returns True if the file was changed.
    """
    path = Path(".github/workflows/update.yml")
    original = path.read_text()

    if cron is None:
        # Remove the schedule block (the two lines: "  schedule:" and "    - cron: '...'")
        updated = re.sub(
            r"\s+schedule:\n\s+- cron: '[^']*'\n",
            "\n",
            original,
        )
    else:
        updated = re.sub(r"cron: '[^']*'", f"cron: '{cron}'", original)

    if updated == original:
        return False

    path.write_text(updated)
    label = cron if cron else "removed (tournament over)"
    print(f"Updated workflow cron → {label}")
    return True


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    matches = fetch_matches()
    bracket = load_bracket()

    service = gcal_service()
    for match in matches:
        upsert_event(service, build_gcal_event(match, bracket))
    print(f"Upserted {len(matches)} events to Google Calendar")

    cron = compute_cron(matches)
    update_workflow_cron(cron)


if __name__ == "__main__":
    main()
