# Role: Deterministic helper rules for weather routing. Used by DecisionLogic to decide whether it's safe/valid
# to call Open-Meteo (forecast horizon checks) and to detect month-level queries (seasonal guidance).

from __future__ import annotations

import re
from datetime import date as dt_date

from backend.models.trip_profile import TripProfile

_MONTH_PATTERN = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)


def mentions_month(text: str) -> bool:
    # Role: fast check for month names (signals "seasonal" vs exact forecast).
    return bool(_MONTH_PATTERN.search(text or ""))


def is_within_open_meteo_forecast_window(trip: TripProfile, horizon_days: int = 16) -> bool:
    # 1) Normalize missing start/end
    # 2) Reject invalid/past ranges
    # 3) Ensure both start/end are within horizon and range length is <= horizon

    today = dt_date.today()

    start = trip.start_date
    end = trip.end_date

    if start is None and end is None:
        return True

    if start is None:
        start = end
    if end is None:
        end = start

    if start is None or end is None:
        return True

    if end < start:
        return False

    if end < today:
        return False

    if (start - today).days > horizon_days:
        return False

    if (end - today).days > horizon_days:
        return False

    if (end - start).days + 1 > horizon_days:
        return False

    return True

def is_seasonal_weather_question(text: str) -> bool:
    t = (text or "").lower()
    triggers = ("usually", "typical", "around this time of year", "on average", "generally")
    return any(x in t for x in triggers)

