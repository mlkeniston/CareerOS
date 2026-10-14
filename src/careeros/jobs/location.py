"""Conservative, offline classification of job locations for U.S.-only work."""
from __future__ import annotations

import re


US = "us"
OUTSIDE_US = "outside_us"
UNKNOWN = "unknown"

_US_COUNTRY_MARKERS = (
    "united states", "united states of america", "usa", "u s a", "us", "u s",
)
_OUTSIDE_COUNTRY_MARKERS = (
    "canada", "mexico", "united kingdom", "great britain", "uk", "u k", "england", "scotland", "wales",
    "ireland", "india", "germany", "france", "spain", "italy", "australia", "new zealand", "singapore",
    "japan", "china", "brazil", "argentina", "chile", "israel", "netherlands", "belgium", "sweden",
    "norway", "denmark", "finland", "switzerland", "poland", "portugal", "south korea", "south africa",
    "czechia", "czech republic", "austria", "romania", "ukraine", "philippines", "indonesia", "thailand",
    "taiwan", "turkey", "united arab emirates", "uae", "colombia", "peru", "pakistan", "bangladesh",
)
_US_STATES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas", "ca": "california",
    "co": "colorado", "ct": "connecticut", "de": "delaware", "fl": "florida", "ga": "georgia",
    "hi": "hawaii", "id": "idaho", "il": "illinois", "in": "indiana", "ia": "iowa", "ks": "kansas",
    "ky": "kentucky", "la": "louisiana", "me": "maine", "md": "maryland", "ma": "massachusetts",
    "mi": "michigan", "mn": "minnesota", "ms": "mississippi", "mo": "missouri", "mt": "montana",
    "ne": "nebraska", "nv": "nevada", "nh": "new hampshire", "nj": "new jersey", "nm": "new mexico",
    "ny": "new york", "nc": "north carolina", "nd": "north dakota", "oh": "ohio", "ok": "oklahoma",
    "or": "oregon", "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina", "sd": "south dakota",
    "tn": "tennessee", "tx": "texas", "ut": "utah", "vt": "vermont", "va": "virginia", "wa": "washington",
    "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming", "dc": "district of columbia",
    "pr": "puerto rico", "gu": "guam", "vi": "u s virgin islands", "as": "american samoa", "mp": "northern mariana islands",
}
_KNOWN_NON_US_CITIES = (
    "london", "toronto", "vancouver", "montreal", "ottawa", "calgary", "edmonton", "waterloo",
    "dublin", "bengaluru", "bangalore", "hyderabad", "mumbai", "new delhi", "singapore", "tokyo",
    "osaka", "berlin", "munich", "paris", "amsterdam", "stockholm", "copenhagen", "sydney",
    "melbourne", "auckland", "zurich", "tel aviv", "sao paulo", "são paulo", "mexico city",
)
_KNOWN_US_CITIES = {
    "new york", "new york city", "nyc", "san francisco", "los angeles", "boston", "seattle", "austin",
    "chicago", "san diego", "denver", "atlanta", "philadelphia", "houston", "dallas", "san jose",
    "pittsburgh", "raleigh", "durham", "ann arbor", "detroit", "minneapolis", "portland", "miami",
    "orlando", "tampa", "phoenix", "salt lake city", "provo", "madison", "columbus", "boulder",
    "charlotte", "washington dc", "washington d c", "dc", "cambridge", "baltimore", "irvine",
}


def classify_location(value: str | None) -> str:
    """Return ``us``, ``outside_us``, or ``unknown`` using location text only.

    Unknown locations are deliberately not treated as U.S. locations. This is
    a conservative filter, not a geocoder; city-only and unscoped remote labels
    need human review.
    """
    raw = (value or "").strip().casefold()
    if not raw:
        return UNKNOWN
    normalized = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    padded = f" {normalized} "
    has_us = any(f" {marker} " in padded for marker in _US_COUNTRY_MARKERS)
    has_other = any(f" {marker} " in padded for marker in _OUTSIDE_COUNTRY_MARKERS)
    if has_us and has_other:
        return UNKNOWN
    if has_other:
        return OUTSIDE_US
    if has_us:
        return US

    # A state name is sufficient when it appears as the final location part.
    for state_name in _US_STATES.values():
        if normalized == state_name or normalized.endswith(f" {state_name}"):
            return US

    # Two-letter state/territory abbreviations count only after a delimiter;
    # bare codes are too ambiguous to use as country evidence.
    suffix = re.search(r"(?:,|[-/])\s*([a-z]{2})\s*(?:\d{5}(?:-\d{4})?)?$", raw)
    if suffix and suffix.group(1) in _US_STATES:
        return US

    if any(f" {city} " in padded or normalized == city for city in _KNOWN_NON_US_CITIES):
        return OUTSIDE_US
    if normalized in _KNOWN_US_CITIES:
        return US
    return UNKNOWN


def is_us_location(value: str | None) -> bool:
    return classify_location(value) == US
