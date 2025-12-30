# Role: Canonical trip context (destination, dates, preferences). This is the "source of truth" the rest of the
# system reads from. apply_updates() safely merges incremental updates extracted from the LLM.

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TripProfile(BaseModel):
    destination: Optional[str] = None

    start_date: Optional[date] = None
    end_date: Optional[date] = None
    duration_days: Optional[int] = None

    budget: Optional[str] = None
    travelers: Optional[str] = None

    interests: List[str] = Field(default_factory=list)
    pace: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)

    def apply_updates(self, updates: Dict[str, Any]) -> None:
        # 1) Ignore empty updates
        # 2) Normalize/validate types (strip strings, parse ISO dates)
        # 3) Merge list fields without duplicates
        if not updates:
            return

        destination = updates.get("destination")
        if isinstance(destination, str) and destination.strip():
            self.destination = destination.strip()

        start_date = updates.get("start_date")
        if start_date is not None:
            if isinstance(start_date, date):
                self.start_date = start_date
            elif isinstance(start_date, str) and start_date.strip():
                self.start_date = date.fromisoformat(start_date.strip())

        end_date = updates.get("end_date")
        if end_date is not None:
            if isinstance(end_date, date):
                self.end_date = end_date
            elif isinstance(end_date, str) and end_date.strip():
                self.end_date = date.fromisoformat(end_date.strip())

        duration_days = updates.get("duration_days")
        if isinstance(duration_days, int):
            self.duration_days = duration_days

        for field in ("budget", "travelers", "pace"):
            value = updates.get(field)
            if isinstance(value, str) and value.strip():
                setattr(self, field, value.strip())

        interests = updates.get("interests")
        if isinstance(interests, list):
            for interest in interests:
                if isinstance(interest, str):
                    cleaned = interest.strip()
                    if cleaned and cleaned not in self.interests:
                        self.interests.append(cleaned)

        constraints = updates.get("constraints")
        if isinstance(constraints, list):
            for constraint in constraints:
                if isinstance(constraint, str):
                    cleaned = constraint.strip()
                    if cleaned and cleaned not in self.constraints:
                        self.constraints.append(cleaned)
