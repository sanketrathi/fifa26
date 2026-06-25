# ⚽ FIFA World Cup 2026 — Self-Updating Calendar Feed

Subscribe once. As the bracket resolves, placeholder slots (`Runner-up Group A`, `Best 3rd (C/D/F/G/H)`) are replaced with real team names automatically — no re-subscribing needed.

**Live feed:** https://sanketrathi.github.io/fifa26/calendar.ics

## Subscribe

| Client | Link |
|--------|------|
| Google Calendar | [Add to Google Calendar](https://www.google.com/calendar/render?cid=webcal://sanketrathi.github.io/fifa26/calendar.ics) |
| Apple Calendar | [Add to Apple Calendar](webcal://sanketrathi.github.io/fifa26/calendar.ics) |
| Other | Paste the feed URL above into any calendar app that supports ICS subscriptions |

## How it works

```
GitHub Actions (every 30 min)
    │
    ▼
football-data.org API          bracket.json (static fallback)
    │                               │
    └──────────────┬────────────────┘
                   ▼
            generate.py
                   │
                   ▼
            calendar.ics  ──▶  GitHub Pages  ──▶  Your calendar
```

- **Group stage** matches always have known teams from day one.
- **Knockout matches** start as bracket placeholders (`bracket.json`) and flip to real names as soon as `football-data.org` returns them — typically within hours of the group stage ending.
- Events use stable UIDs (`wc2026-{matchId}@sanketrathi.github.io`) so calendar clients update in-place rather than duplicating.
- `SEQUENCE` increments as a match progresses (`TBD → teams known → finished`), signalling clients to refresh the event.

## Known limitation: Google Calendar refresh delay

Google Calendar polls externally subscribed ICS feeds roughly every **12–24 hours**. There is no server-side mechanism to force a faster refresh — Google's Calendar API push notifications only work for natively-owned calendars, not subscribed feeds. The feed includes a `REFRESH-INTERVAL:PT1H` hint, which Google partially respects but does not guarantee.

**Bottom line:** updates will appear in Google Calendar within a day. Apple Calendar typically refreshes faster (~1 hour). For the knockout bracket specifically, teams are confirmed days before their match kicks off, so the lag is rarely meaningful in practice.

## Local development

```bash
cp .env.local.example .env.local
# fill in FOOTBALL_DATA_API_KEY

uv sync
uv run generate.py   # writes calendar.ics
```

## Architecture decisions

- **Single `.ics` file** — one URL to subscribe to, no per-team filtering (out of scope).
- **`bracket.json`** — static file mapping `football-data.org` match IDs to human-readable bracket labels. Cross-referenced against the official FIFA schedule. Note: FIFA match numbers are not chronological (e.g., matches 73, 76, 74, 75 play in that date order) — the mapping was verified by converting each match's local kickoff time to UTC and matching against the API.
- **GitHub Pages** — free, stable URL, correct `Content-Type` for ICS subscriptions. No server needed.
- **`[skip ci]`** on bot commits — prevents the workflow from re-triggering itself when it commits an updated `calendar.ics`.

## Built by

[Claude Sonnet 4.6](https://anthropic.com) & [Sanket Rathi](https://github.com/sanketrathi)
