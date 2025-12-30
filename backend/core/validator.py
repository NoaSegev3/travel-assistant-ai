# Role: Input gatekeeper per intent. Checks if the current State has enough trip info to proceed,
# and returns a single-field missing_info list used by the clarification loop.

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from backend.models.intent import Intent
from backend.models.state import State


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    missing_info: List[str]
    problems: List[str]


class Validator:
    def validate(self, intent: Intent, state: State) -> ValidationResult:
        # 1) Collect missing required fields for this intent
        # 2) Collect any invalid-state problems (e.g., negative duration)
        # 3) ok=True only if both lists are empty

        trip = state.trip_profile
        missing: List[str] = []
        problems: List[str] = []

        if trip.duration_days is not None and trip.duration_days <= 0:
            problems.append("duration_days must be > 0")

        if intent == Intent.ITINERARY_PLANNING:
            if not trip.destination:
                missing.append("destination")
            if not self._has_dates_or_duration(state):
                missing.append("dates_or_duration")

        elif intent == Intent.WEATHER_QUERY:
            if not trip.destination:
                missing.append("destination")

        elif intent in {Intent.ATTRACTIONS_RECOMMENDATIONS, Intent.PACKING_LIST}:
            if not trip.destination:
                missing.append("destination")

        ok = (len(missing) == 0) and (len(problems) == 0)
        return ValidationResult(ok=ok, missing_info=missing, problems=problems)

    def _has_dates_or_duration(self, state: State) -> bool:
        # Key line: itinerary can be satisfied by either duration OR (start_date+end_date).
        trip = state.trip_profile
        return trip.duration_days is not None or (trip.start_date is not None and trip.end_date is not None)
