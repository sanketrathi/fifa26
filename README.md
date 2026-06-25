# ⚽ FIFA World Cup 2026 — Live Google Calendar

Subscribe once. As the knockout bracket resolves, placeholder slots (`Runner-up Group A`, `Best 3rd (C/D/F/G/H)`) flip to real team names automatically. Updates hit Google Calendar within minutes.

**→ [Add to Google Calendar](https://calendar.google.com/calendar/render?cid=GOOGLE_CALENDAR_ID_PLACEHOLDER)**

---

## What each event contains

- **Title**: `Brazil vs Germany` (or bracket placeholder until resolved)
- **Location**: `Estadio Azteca, Mexico City` — links to Google Maps
- **Description**:
  - FIFA rankings of both teams
  - Stage and group
  - Half-time score (while live)
  - Full-time result with AET/Pens notation
  - Goal scorers with minute and player name

## How it works

```
GitHub Actions (adaptive cron)
        │
        ├── football-data.org   → match data, team names, scores
        ├── venues.json         → static venue per match (built once)
        ├── rankings.json       → FIFA rankings as of June 11, 2026
        ├── bracket.json        → bracket labels for unresolved knockouts
        └── ESPN API            → goal scorers (live + finished matches only)
                │
                ▼
        Google Calendar API  →  events updated directly
                │
                ▼
        Subscribers see changes within minutes
```

The cron schedule self-adjusts:
- **Match day or day before** → every 30 minutes
- **Tournament, no match today/tomorrow** → every 3 hours
- **After July 19** → schedule trigger removed; workflow goes dormant

## Setup

### 1. Secrets required

| Secret | Where | Description |
|--------|-------|-------------|
| `FOOTBALL_DATA_API_KEY` | GitHub + `.env.local` | football-data.org free tier key |
| `GOOGLE_CREDENTIALS_JSON` | GitHub secret only | Service account JSON (raw content) |
| `GOOGLE_CREDENTIALS_FILE` | `.env.local` only | Path to service account JSON file |
| `GOOGLE_CALENDAR_ID` | GitHub + `.env.local` | Target calendar ID |

### 2. Google Cloud setup (one-time)

1. Create a project at [console.cloud.google.com](https://console.cloud.google.com)
2. Enable the **Google Calendar API**
3. IAM & Admin → Service Accounts → Create → generate a JSON key → download it
4. Save it locally as `service-account.json` (gitignored)
5. Add to `.env.local`:
   ```
   GOOGLE_CREDENTIALS_FILE=./service-account.json
   FOOTBALL_DATA_API_KEY=your_key
   ```
6. Run `uv run setup_calendar.py` → prints the `GOOGLE_CALENDAR_ID`
7. Add `GOOGLE_CALENDAR_ID` to `.env.local`

### 3. GitHub secrets

```bash
gh secret set FOOTBALL_DATA_API_KEY --body "$(grep FOOTBALL_DATA_API_KEY .env.local | cut -d= -f2)"
gh secret set GOOGLE_CALENDAR_ID    --body "$(grep GOOGLE_CALENDAR_ID .env.local | cut -d= -f2)"
gh secret set GOOGLE_CREDENTIALS_JSON < service-account.json
```

### 4. One-time data setup

```bash
uv run setup_calendar.py   # creates + makes public the Google Calendar
uv run setup_venues.py     # builds venues.json from ESPN (re-run after each knockout round)
```

### 5. Test locally

```bash
uv run generate.py
```

## Updating venues for knockout matches

`venues.json` covers all group stage matches. As the knockout bracket resolves, re-run `setup_venues.py` to fill in the remaining venues — it skips matches already present and only adds new ones.

## Data sources

- Match data & results: [football-data.org](https://www.football-data.org) (free tier)
- Venues & goal scorers: ESPN unofficial API
- FIFA rankings: official rankings as of June 11, 2026
- Bracket structure: derived from official FIFA 2026 bracket
