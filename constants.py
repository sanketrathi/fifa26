# Known name discrepancies between ESPN display names and football-data.org team names.
# Keyed by normalized ESPN name (lowercase ASCII); value is the normalized FD name.
ESPN_TO_FD: dict[str, str] = {
    "cape verde":             "cape verde islands",
    "cote d'ivoire":          "ivory coast",
    "côte d'ivoire":          "ivory coast",
    "dr congo":               "congo dr",
    "bosnia and herzegovina": "bosnia-herzegovina",
    "czech republic":         "czechia",
    "usa":                    "united states",
    "türkiye":                "turkey",
    "turkiye":                "turkey",
}
