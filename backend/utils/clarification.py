# Role: Deterministic "one question" builder. Converts missing_info keys (from Validator/DecisionLogic)
# into a single user-facing clarification question to keep the dialog step-by-step.

from __future__ import annotations

from typing import List

import backend.config as config


def build_clarification_question(missing_info: List[str]) -> str:
    # Step 1: log missing_info in debug mode (helps trace dialog state).
    if config.DEBUG:
        print("CLARIFICATION_BUILDER missing_info:", missing_info)

    if not missing_info:
        return "What details can you share about your trip (destination and dates)?"

    first = missing_info[0]

    # Step 2: map internal slot keys -> a single friendly question.
    if first == "destination":
        return "Where are you traveling to (city/country)?"

    if first in {"dates", "dates_or_duration"}:
        return "What are your travel dates (or how many days is the trip)?"

    if first == "budget":
        return "What’s your budget level (low / mid / high)?"

    if first == "travelers":
        return "Who’s traveling (solo / couple / friends / family, kids yes/no)?"

    if first == "interests":
        return "What are your interests (e.g., food, museums, nature, nightlife)?"

    if first == "pace":
        return "What pace do you prefer (relaxed / balanced / intense)?"

    if first == "goal":
        return "What would you like help with: itinerary, attractions, packing, weather, or currency conversion?"

    if first == "currency_pair":
        return (
            "Which currencies are you converting between? (e.g., USD to EUR)\n"
            "Then tell me the amount (e.g., 100)."
        )

    if first == "currency_amount":
        return "What amount do you want to convert? (e.g., 100)"

    if first == "currency_from":
        return "What is the FROM currency? (e.g., USD)"

    if first == "currency_to":
        return "What is the TO currency? (e.g., EUR)"

    return "What’s one more detail about your trip that matters most (destination, dates, budget, travelers)?"
