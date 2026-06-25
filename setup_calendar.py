"""
One-time setup: creates the public FIFA World Cup 2026 Google Calendar
using the service account credentials.

Run once locally:
    uv run setup_calendar.py

Then copy the printed GOOGLE_CALENDAR_ID into .env.local and add it
as a GitHub Actions secret.
"""

import json
import os

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv(".env.local")

CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]


def main() -> None:
    info = json.loads(CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    cal = service.calendars().insert(body={
        "summary": "⚽ FIFA World Cup 2026",
        "description": (
            "Self-updating match calendar for the 2026 FIFA World Cup. "
            "Knockout bracket placeholders resolve to real team names as results come in. "
            "Updated every 30 minutes during the tournament via GitHub Actions."
        ),
        "timeZone": "UTC",
    }).execute()

    cal_id = cal["id"]

    # Make the calendar publicly readable (no Google account required to subscribe)
    service.acl().insert(calendarId=cal_id, body={
        "role": "reader",
        "scope": {"type": "default"},
    }).execute()

    print(f"\nCalendar created and made public.")
    print(f"\nAdd this to .env.local and GitHub Secrets:")
    print(f"\n  GOOGLE_CALENDAR_ID={cal_id}")
    print(f"\nSubscribe URL:")
    print(f"\n  https://calendar.google.com/calendar/render?cid={cal_id}")


if __name__ == "__main__":
    main()
