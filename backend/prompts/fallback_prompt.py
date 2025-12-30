# Role: Builds the LLM prompt used only in fallback mode. It includes trip context + last assistant message
# so the model can recover without repeating the same question, and it enforces strict "one question max" rules.

from __future__ import annotations

import json
from typing import Dict, List, Optional

from backend.models.intent import Intent
from backend.models.state import State


def build_fallback_prompt(
    *,
    intent: Optional[Intent],
    state: State,
    user_message: str,
    recent_messages: Optional[List[Dict[str, str]]] = None,
    error: Optional[str] = None,
) -> str:
    trip = state.trip_profile

    # Step 1: build compact context (JSON-safe dates).
    context = {
        "destination": trip.destination,
        "start_date": str(trip.start_date) if trip.start_date is not None else None,
        "end_date": str(trip.end_date) if trip.end_date is not None else None,
        "duration_days": trip.duration_days,
        "budget": trip.budget,
        "travelers": trip.travelers,
        "interests": trip.interests,
        "pace": trip.pace,
        "constraints": trip.constraints,
        "pending_missing_info": state.pending_missing_info,
        "last_intent": state.last_intent.value if state.last_intent else None,
        "turn_count": state.turn_count,
    }

    history_block = ""
    last_assistant = ""
    if recent_messages:
        formatted = "\n".join([f'{m["role"]}: {m["content"]}' for m in recent_messages])
        history_block = f"\n\nRecent conversation:\n{formatted}"
        for m in reversed(recent_messages):
            if m.get("role") == "assistant" and m.get("content"):
                last_assistant = m["content"]
                break

    # Key line: helps avoid repeating identical clarification.
    last_assistant_block = ""
    if last_assistant:
        last_assistant_block = (
            "\n\nLAST_ASSISTANT_MESSAGE (do not repeat it verbatim):\n"
            f"{last_assistant}"
        )

    err_block = ""
    if error:
        err_block = f"\n\nERROR (for context only, do not mention to user):\n{error}"

    intent_str = intent.value if intent else "unknown"

    return f"""
You are a Travel Assistant.
You are in FALLBACK / RECOVERY mode because something went wrong.

Current user message: {user_message}
Current intent (best guess): {intent_str}

Trip context (source of truth):
{json.dumps(context, ensure_ascii=False)}
{err_block}
{last_assistant_block}

FALLBACK RULES (MUST FOLLOW):
- Output ONLY a user-facing message (no reasoning, no system talk, no JSON).
- Be calm and helpful.
- Ask at most ONE short clarification question.
- Prefer the most important next piece of info:
  1) If "pending_missing_info" exists: ask for that.
  2) Else if last_intent is null: ask the user to choose goal: itinerary / attractions / packing / weather / currency conversion.
  3) Else ask the next required info for that goal:
     - itinerary needs destination + dates_or_duration
     - attractions needs destination
     - packing needs destination (and optionally month)
     - weather needs destination (dates optional)
     - currency conversion needs amount + currency pair (e.g., "100 USD to EUR")

- If you already have enough info for the user’s goal, provide a short helpful answer (bullets), and optionally ask ONE follow-up question.
- Do NOT repeat the exact same clarification question that was asked in the last assistant message.

Keep it concise.
{history_block}
""".strip()
