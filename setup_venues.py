"""
One-time setup: builds venues.json by fetching the ESPN scoreboard for every
day of the tournament and building a global (home, away) → venue lookup,
then cross-referencing against the football-data.org match list.

ESPN uses local kickoff dates; football-data.org uses UTC. Ignoring dates
entirely and matching only on team names avoids timezone boundary mismatches.

Run once (or re-run as the tournament progresses to fill in knockout venues):
    uv run setup_venues.py

Commit venues.json afterwards — it's static data that never changes at runtime.
"""

import json
import os
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(".env.local")

FOOTBALL_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
VENUES_FILE = Path("venues.json")

TOURNAMENT_START = date(2026, 6, 11)
TOURNAMENT_END = date(2026, 7, 19)

# Known name discrepancies between ESPN and football-data.org
ESPN_TO_FD: dict[str, str] = {
    "cape verde":              "cape verde islands",
    "cote d'ivoire":           "ivory coast",
    "côte d'ivoire":           "ivory coast",
    "dr congo":                "congo dr",
    "bosnia and herzegovina":  "bosnia-herzegovina",
    "czech republic":          "czechia",
    "usa":                     "united states",
    "türkiye":                 "turkey",
    "turkiye":                 "turkey",
}


def normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


def fetch_fdorg_matches() -> list[dict]:
    r = requests.get(
        "https://api.football-data.org/v4/competitions/WC/matches",
        headers={"X-Auth-Token": FOOTBALL_API_KEY},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["matches"]


def fetch_espn_scoreboard(date_str: str) -> list[dict]:
    """Returns list of ESPN competition dicts for the given YYYYMMDD date."""
    try:
        r = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard",
            params={"dates": date_str},
            timeout=15,
        )
        r.raise_for_status()
        competitions = []
        for event in r.json().get("events", []):
            comps = event.get("competitions", [])
            if comps:
                competitions.append(comps[0])
        return competitions
    except Exception as e:
        print(f"  ESPN fetch failed for {date_str}: {e}")
        return []


def build_espn_global_lookup() -> dict[tuple[str, str], str]:
    """
    Fetches ESPN scoreboard for every day of the tournament.
    Returns a global (normalized_home, normalized_away) → venue_name mapping.
    Date-agnostic to avoid UTC vs local timezone boundary issues.
    """
    lookup: dict[tuple[str, str], str] = {}
    day = TOURNAMENT_START
    while day <= TOURNAMENT_END:
        date_str = day.strftime("%Y%m%d")
        comps = fetch_espn_scoreboard(date_str)
        for comp in comps:
            competitors = comp.get("competitors", [])
            home = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), "")
            away = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), "")
            venue = comp.get("venue", {}).get("fullName")
            address = comp.get("venue", {}).get("address", {})
            city = address.get("city", "")
            location = f"{venue}, {city}" if city else venue
            if home and away and venue:
                nh = ESPN_TO_FD.get(normalize(home), normalize(home))
                na = ESPN_TO_FD.get(normalize(away), normalize(away))
                lookup[(nh, na)] = location
        day += timedelta(days=1)

    print(f"ESPN global lookup built: {len(lookup)} matches with venues")
    return lookup


def build_venues() -> None:
    existing: dict[str, str] = {}
    if VENUES_FILE.exists():
        raw = json.loads(VENUES_FILE.read_text())
        existing = {k: v for k, v in raw.items() if not k.startswith("_")}

    matches = fetch_fdorg_matches()
    print(f"Fetched {len(matches)} matches from football-data.org")

    missing = [m for m in matches if str(m["id"]) not in existing]
    if not missing:
        print("No missing venues — venues.json is complete.")
        return

    print(f"{len(missing)} matches without venue, fetching ESPN for all tournament dates...")
    espn_lookup = build_espn_global_lookup()

    venues: dict[str, str] = dict(existing)
    found = 0
    still_missing = []

    for match in missing:
        home = normalize(match["homeTeam"]["name"] or "")
        away = normalize(match["awayTeam"]["name"] or "")
        if not home or not away:
            still_missing.append(match)
            continue

        home = ESPN_TO_FD.get(home, home)
        away = ESPN_TO_FD.get(away, away)

        venue = espn_lookup.get((home, away))
        if venue:
            venues[str(match["id"])] = venue
            found += 1
        else:
            still_missing.append(match)

    output: dict = {"_note": "Static venue lookup keyed by football-data.org match ID. Built by setup_venues.py — re-run to fill in knockout venues as bracket resolves."}
    output.update(dict(sorted(venues.items(), key=lambda x: int(x[0]))))
    VENUES_FILE.write_text(json.dumps(output, indent=2))

    print(f"venues.json updated — {found} new venues added, {len(venues)} total")
    if still_missing:
        unresolved = [m for m in still_missing if m["homeTeam"]["name"] is None]
        name_miss = [m for m in still_missing if m["homeTeam"]["name"] is not None]
        if unresolved:
            print(f"  {len(unresolved)} knockout matches not yet resolved (expected)")
        if name_miss:
            print(f"  {len(name_miss)} matches with known teams but no ESPN venue match (name mismatch?):")
            for m in name_miss:
                print(f"    {m['homeTeam']['name']} vs {m['awayTeam']['name']}")


if __name__ == "__main__":
    build_venues()
