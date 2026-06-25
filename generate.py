"""
Self-updating FIFA World Cup 2026 Google Calendar.

Data pipeline:
  football-data.org → match schedule, live scores, team names
  venues.json        → static venue per match (built once by setup_venues.py)
  rankings.json      → FIFA rankings as of tournament start
  bracket.json       → fallback labels for unresolved knockout slots
  ESPN API           → goal scorers for live/finished matches only

Events are upserted directly to Google Calendar via the API.
The GitHub Actions cron schedule self-adjusts and removes itself after the Final.
"""
import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict

import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from constants import ESPN_TO_FD

load_dotenv(".env.local")

FOOTBALL_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
CALENDAR_ID = os.environ["GOOGLE_CALENDAR_ID"]

TOURNAMENT_START = date(2026, 6, 11)
TOURNAMENT_END = date(2026, 7, 19)

MATCH_DURATION = timedelta(minutes=150)

STAGE_LABELS = {
    "GROUP_STAGE":    "Group Stage",
    "LAST_32":        "Round of 32",
    "LAST_16":        "Round of 16",
    "QUARTER_FINALS": "Quarterfinal",
    "SEMI_FINALS":    "Semifinal",
    "THIRD_PLACE":    "Third Place",
    "FINAL":          "Final",
}


class Goal(TypedDict):
    player: str
    team: str
    minute: str
    type: str


# ── Credentials ──────────────────────────────────────────────────────────────

def load_credentials() -> service_account.Credentials:
    """
    Supports two credential sources:
    - GOOGLE_CREDENTIALS_FILE: path to a service account JSON file (local dev)
    - GOOGLE_CREDENTIALS_JSON: raw JSON string (GitHub Actions secret)
    """
    creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE")
    if creds_file:
        info = json.loads(Path(creds_file).read_text())
    else:
        info = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])

    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/calendar"]
    )


def gcal_service():
    return build("calendar", "v3", credentials=load_credentials(), cache_discovery=False)


# ── Static data ───────────────────────────────────────────────────────────────

def load_json(filename: str) -> dict[str, Any]:
    with open(Path(__file__).parent / filename) as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ── Football data ─────────────────────────────────────────────────────────────

def fetch_matches() -> list[dict]:
    r = requests.get(
        "https://api.football-data.org/v4/competitions/WC/matches",
        headers={"X-Auth-Token": FOOTBALL_API_KEY},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["matches"]


# ── ESPN scorer enrichment ────────────────────────────────────────────────────

def normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


def fetch_espn_scorers(matches: list[dict]) -> dict[int, list[Goal]]:
    """
    Fetches goal scorer data from ESPN for live or recently finished matches.
    Returns: match_id → list of {player, team, minute, type}
    """
    relevant = [
        m for m in matches
        if m["status"] in ("IN_PLAY", "PAUSED", "FINISHED")
        and m["homeTeam"]["name"] and m["awayTeam"]["name"]
    ]
    if not relevant:
        return {}

    # ESPN uses local kickoff dates; late-evening North American kickoffs (e.g.
    # 01:00 UTC) appear on the previous calendar day locally. Fetching UTC-1 as
    # well ensures we never miss a match due to the timezone boundary.
    dates_needed: set[str] = set()
    for m in relevant:
        utc_dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        dates_needed.add(utc_dt.strftime("%Y%m%d"))
        dates_needed.add((utc_dt - timedelta(days=1)).strftime("%Y%m%d"))

    espn_by_teams: dict[tuple[str, str], list[Goal]] = {}

    for date_str in dates_needed:
        try:
            r = requests.get(
                "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard",
                params={"dates": date_str},
                timeout=15,
            )
            r.raise_for_status()
        except Exception:
            continue

        for event in r.json().get("events", []):
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            home_name = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), "")
            away_name = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), "")

            if not home_name or not away_name:
                continue

            nh = ESPN_TO_FD.get(normalize(home_name), normalize(home_name))
            na = ESPN_TO_FD.get(normalize(away_name), normalize(away_name))

            goals: list[Goal] = []
            for detail in comp.get("details", []):
                if "Goal" not in detail.get("type", {}).get("text", ""):
                    continue
                athletes = detail.get("athletesInvolved", [])
                player = athletes[0].get("displayName", "") if athletes else ""
                team = detail.get("team", {}).get("displayName", "")
                team = ESPN_TO_FD.get(normalize(team), normalize(team))
                minute = detail.get("clock", {}).get("displayValue", "")
                goal_type = detail.get("type", {}).get("text", "Goal")
                goals.append(Goal(player=player, team=team, minute=minute, type=goal_type))

            espn_by_teams[(nh, na)] = goals

    result: dict[int, list[Goal]] = {}
    for match in relevant:
        nh = ESPN_TO_FD.get(normalize(match["homeTeam"]["name"]), normalize(match["homeTeam"]["name"]))
        na = ESPN_TO_FD.get(normalize(match["awayTeam"]["name"]), normalize(match["awayTeam"]["name"]))
        goals = espn_by_teams.get((nh, na))
        if goals is not None:
            result[match["id"]] = goals

    return result


# ── Event builders ────────────────────────────────────────────────────────────

def event_summary(match: dict, bracket: dict) -> str:
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    group = match.get("group", "")
    group_suffix = f" ({group.replace('GROUP_', 'Group ')})" if group else ""
    if home and away:
        if match["status"] == "FINISHED":
            ft = match["score"]["fullTime"]
            if ft["home"] is not None:
                h, a = ft["home"], ft["away"]
                suffix = ""
                if match["score"]["duration"] == "EXTRA_TIME":
                    suffix = " (AET)"
                elif match["score"]["duration"] == "PENALTY_SHOOTOUT":
                    suffix = " (Pens)"
                return f"{home} {h}–{a} {away}{suffix}{group_suffix}"
        return f"{home} vs {away}{group_suffix}"
    fallback = bracket.get(str(match["id"]))
    if fallback:
        return f"{fallback['home']} vs {fallback['away']}"
    return f"{STAGE_LABELS.get(match['stage'], match['stage'])} — TBD vs TBD"


def event_description(match: dict, rankings: dict, scorers: list[Goal] | None) -> str:
    lines = []

    # FIFA rankings — shown even for TBD matches if both sides are resolvable
    home_name = match["homeTeam"]["name"]
    away_name = match["awayTeam"]["name"]
    if home_name and away_name:
        hr = rankings.get(home_name, "–")
        ar = rankings.get(away_name, "–")
        lines.append(f"FIFA Rankings: {home_name} #{hr} · {away_name} #{ar}")

    # Stage + group
    stage = STAGE_LABELS.get(match["stage"], match["stage"])
    group = match.get("group", "")
    if group:
        lines.append(f"{stage} · {group.replace('GROUP_', 'Group ')}")
    else:
        lines.append(stage)

    # Score
    score = match["score"]
    status = match["status"]
    if status in ("IN_PLAY", "PAUSED") and score["halfTime"]["home"] is not None:
        h, a = score["halfTime"]["home"], score["halfTime"]["away"]
        lines.append(f"HT: {h}–{a}")
    if status == "FINISHED" and score["fullTime"]["home"] is not None:
        h, a = score["fullTime"]["home"], score["fullTime"]["away"]
        result = f"FT: {home_name} {h}–{a} {away_name}"
        if score["duration"] == "EXTRA_TIME":
            result += " (AET)"
        elif score["duration"] == "PENALTY_SHOOTOUT":
            result += " (Pens)"
        lines.append(result)

    # Goal scorers
    if scorers:
        goal_lines = [f"{g['minute']} {g['player']} ({g['team']})" for g in scorers]
        lines.append("Goals: " + " · ".join(goal_lines))

    return "\n".join(lines)


# ── Self-modifying cron ───────────────────────────────────────────────────────

def compute_cron(matches: list[dict]) -> str | None:
    today = datetime.now(timezone.utc).date()

    if today > TOURNAMENT_END:
        return None  # Tournament over — remove schedule trigger

    match_dates = {
        datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).date()
        for m in matches
    }
    tomorrow = today + timedelta(days=1)

    if today in match_dates or tomorrow in match_dates:
        return "*/30 * * * *"

    return "0 */3 * * *"


def update_workflow_cron(cron: str | None) -> None:
    # Rewrites .github/workflows/update.yml in-place. When cron is None
    # (tournament over), the entire schedule: block is removed so the workflow
    # stops triggering automatically. The workflow can still be run manually.
    path = Path(".github/workflows/update.yml")
    original = path.read_text()

    if cron is None:
        updated = re.sub(r"\s+schedule:\n(\s+- cron: '[^']*'\n)+", "\n", original)
    else:
        updated = re.sub(r"cron: '[^']*'", f"cron: '{cron}'", original)

    if updated != original:
        path.write_text(updated)
        print(f"Workflow cron updated → {cron or 'removed (tournament over)'}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    matches = fetch_matches()
    bracket = load_json("bracket.json")
    rankings = load_json("rankings.json")
    venues = load_json("venues.json")

    scorers_by_id = fetch_espn_scorers(matches)

    service = gcal_service()
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    for match in matches:
        start = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
        end = start + MATCH_DURATION
        venue = venues.get(str(match["id"]))
        scorers = scorers_by_id.get(match["id"])

        ev: dict = {
            # Google Calendar event IDs must match [a-v0-9]{5,1024} (base32hex).
            # 'w' is out of range, so we prefix with 'fc' (FIFA Calendar).
            "id": f"fc2026{match['id']}",
            "summary": event_summary(match, bracket),
            "description": event_description(match, rankings, scorers),
            "start": {"dateTime": start.strftime(fmt), "timeZone": "UTC"},
            "end":   {"dateTime": end.strftime(fmt),   "timeZone": "UTC"},
        }
        if venue:
            ev["location"] = venue  # Google Calendar auto-links to Maps

        try:
            service.events().patch(calendarId=CALENDAR_ID, eventId=ev["id"], body=ev).execute()
        except HttpError as e:
            if e.resp.status == 404:
                service.events().insert(calendarId=CALENDAR_ID, body=ev).execute()
            else:
                raise

    print(f"Upserted {len(matches)} events")
    update_workflow_cron(compute_cron(matches))


if __name__ == "__main__":
    main()
