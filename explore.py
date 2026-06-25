import json
import os

import requests
from dotenv import load_dotenv

load_dotenv(".env.local")

API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
BASE_URL = "https://api.football-data.org/v4"

headers = {"X-Auth-Token": API_KEY}


def get(path, **params):
    r = requests.get(f"{BASE_URL}{path}", headers=headers, params=params)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    data = get("/competitions/WC/matches")
    print(json.dumps(data, indent=2))
