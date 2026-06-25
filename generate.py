import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from icalendar import Calendar, Event

load_dotenv(".env.local")

API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
BASE_URL = "https://api.football-data.org/v4"

STAGE_LABELS = {
    "GROUP_STAGE": "Group Stage",
    "LAST_32": "Round of 32",
    "LAST_16": "Round of 16",
    "QUARTER_FINALS": "Quarterfinal",
    "SEMI_FINALS": "Semifinal",
    "THIRD_PLACE": "Third Place",
    "FINAL": "Final",
}

# Matches can go 120 min + injury time. 150 min gives comfortable buffer without
# bleeding into the next match slot on tight schedules.
MATCH_DURATION = timedelta(minutes=150)


def fetch_matches() -> list[dict]:
    r = requests.get(
        f"{BASE_URL}/competitions/WC/matches",
        headers={"X-Auth-Token": API_KEY},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["matches"]


def load_bracket() -> dict:
    with open(Path(__file__).parent / "bracket.json") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def summary(match: dict, bracket: dict) -> str:
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    if home and away:
        return f"{home} vs {away}"

    fallback = bracket.get(str(match["id"]))
    if fallback:
        return f"{fallback['home']} vs {fallback['away']}"

    return f"{STAGE_LABELS.get(match['stage'], match['stage'])} — TBD vs TBD"


def description(match: dict) -> str:
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


def sequence(match: dict) -> int:
    # Monotonically increases as a match progresses through its lifecycle,
    # so calendar clients update in-place rather than creating duplicates.
    if match["status"] == "FINISHED":
        return 3
    if match["status"] in ("IN_PLAY", "PAUSED"):
        return 2
    if match["homeTeam"]["name"] is not None:
        return 1
    return 0


def build_calendar(matches: list[dict], bracket: dict) -> Calendar:
    cal = Calendar()
    cal.add("VERSION", "2.0")
    cal.add("PRODID", "-//sanketrathi//FIFA World Cup 2026//EN")
    cal.add("X-WR-CALNAME", "⚽ FIFA World Cup 2026")
    cal.add("X-WR-TIMEZONE", "UTC")
    # Hint to calendar clients how often to re-fetch. Not all clients respect this,
    # but Google Calendar does honour it to some degree.
    cal.add("REFRESH-INTERVAL;VALUE=DURATION", "PT1H")
    cal.add("X-PUBLISHED-TTL", "PT1H")

    now = datetime.now(timezone.utc)

    for match in matches:
        ev = Event()
        ev.add("UID", f"wc2026-{match['id']}@sanketrathi.github.io")
        ev.add("SUMMARY", summary(match, bracket))
        ev.add("DESCRIPTION", description(match))

        start = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
        ev.add("DTSTART", start)
        ev.add("DTEND", start + MATCH_DURATION)

        last_mod = datetime.fromisoformat(match["lastUpdated"].replace("Z", "+00:00"))
        ev.add("LAST-MODIFIED", last_mod)
        ev.add("DTSTAMP", now)
        ev.add("SEQUENCE", sequence(match))

        cal.add_component(ev)

    return cal


def main() -> None:
    matches = fetch_matches()
    bracket = load_bracket()
    cal = build_calendar(matches, bracket)

    Path("calendar.ics").write_bytes(cal.to_ical())
    print(f"Generated calendar.ics — {len(matches)} events")


if __name__ == "__main__":
    main()
