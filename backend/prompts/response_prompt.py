# Role: Builds the user-specific LLM prompt for response generation. It injects trip context + recent messages,
# plus strict policies per intent (weather/packing/attractions/currency) to reduce hallucinations.

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.models.intent import Intent
from backend.models.state import State


def build_response_prompt(
    intent: Intent,
    state: State,
    recent_messages: Optional[List[Dict[str, str]]] = None,
    tool_data: Optional[Dict[str, Any]] = None,
    force_seasonal: bool = False,
) -> str:

    trip = state.trip_profile

    # Step 1: create JSON-safe context (dates -> strings).
    context: Dict[str, Any] = {
        "destination": trip.destination,
        "start_date": str(trip.start_date) if trip.start_date is not None else None,
        "end_date": str(trip.end_date) if trip.end_date is not None else None,
        "duration_days": trip.duration_days,
        "budget": trip.budget,
        "travelers": trip.travelers,
        "interests": trip.interests,
        "pace": trip.pace,
        "constraints": trip.constraints,
    }

    history_block = ""
    if recent_messages:
        formatted = "\n".join([f'{m["role"]}: {m["content"]}' for m in recent_messages])
        history_block = f"\n\nRecent conversation:\n{formatted}"

    # Step 2: include tool data as "source of truth" when present.
    tool_block = ""
    if tool_data is not None:
        label = "TOOL_DATA"
        if intent == Intent.WEATHER_QUERY:
            label = "WEATHER_TOOL_DATA (SOURCE OF TRUTH)"
        elif intent == Intent.CURRENCY_CONVERSION:
            label = "CURRENCY_TOOL_DATA (SOURCE OF TRUTH)"

        tool_block = f"\n\n{label}:\n" + json.dumps(tool_data, ensure_ascii=False)

    # Key idea: when weather tool is missing but dates exist, hint the model about horizon limits.
    weather_hint = ""
    if intent == Intent.WEATHER_QUERY and tool_data is None:
        # Case 1: user asked about a specific date/range but tool missing (out of horizon / failed)
        if context["start_date"] or context["end_date"]:
            weather_hint = (
                "\n\nHINT (WEATHER): The user asked about a specific date/range, but WEATHER_TOOL_DATA is missing. "
                "This usually means the requested date is beyond the forecast horizon (~16 days) OR the tool failed. "
                "In your answer: briefly mention the ~16-day forecast limit, then provide seasonal expectations "
                "(typical ranges) and practical packing advice. Do NOT invent daily forecast numbers."
            )

        # Case 2: seasonal phrasing like "usually / typical / around this time of year"
        elif force_seasonal:
            weather_hint = (
                "\n\nHINT (WEATHER): This is a SEASONAL question (e.g., 'usually', 'typical', 'around this time of year'). "
                "Do NOT ask for dates. Treat it as 'this time of year' and answer with general seasonal expectations "
                "(typical ranges + rain/wind pattern) and practical packing advice. Do NOT give exact daily highs/lows."
            )

    # Key idea: enforce a stable seasonal answer format when force_seasonal=True and tool_data is missing.
    seasonal_weather_template = ""
    if intent == Intent.WEATHER_QUERY and tool_data is None and force_seasonal:
        seasonal_weather_template = """
SEASONAL WEATHER OUTPUT TEMPLATE (MUST FOLLOW):
- Do NOT ask for dates.
- Do NOT ask "Would you like that?" — just answer.
- Do NOT give exact daily forecast numbers.
- Give a concrete, helpful seasonal summary using this structure:

1) One-line summary: "Around this time of year in {destination}, expect: ____."
2) Typical temperature feel (no day-by-day): mention "cool/mild" + "mornings/evenings cooler".
   - You MAY include a broad range like "single digits to low teens °C" but avoid exact decimal precision.
3) Rain/wind: "showers possible" + "breezy evenings" style phrasing.
4) What to pack (bullets): light jacket, layers, closed shoes, compact umbrella/rain shell.
5) One practical tip (e.g., plan indoor museum time if it rains).
""".strip()

    weather_policy = """
WEATHER RESPONSE POLICY (MUST FOLLOW):
- If WEATHER_TOOL_DATA is provided:
  - Use ONLY that tool data for ALL numeric values (temp, precip, wind).
  - Only talk about the date(s) present in WEATHER_TOOL_DATA.
  - Do NOT claim you have data for other dates.
  - If the user asked about a different date/range than the tool returned,
    explain briefly the limitation and then give general seasonal guidance.
  - If the user asks for "right now" / "current" temperature:
    - Do NOT claim a live observed temperature.
    - Provide today's forecast range for the location/date in WEATHER_TOOL_DATA.
    - Label it clearly as a forecast (not a live sensor reading).

- If WEATHER_TOOL_DATA is NOT provided:
  - Do NOT invent forecasts or numeric values for a specific day.
  - Provide general/seasonal expectations only (typical ranges + packing advice).
  - Be transparent that you can't fetch a specific forecast for that date/range.
  - If the user asked about a specific date/range beyond the next ~16 days,
    explicitly say forecasts are typically available only up to ~16 days ahead.
  - If the user phrased it as "usually/typical/around this time of year", do NOT ask for dates — answer seasonally.
""".strip()

    attractions_policy = """
ATTRACTIONS RESPONSE POLICY (MUST FOLLOW):
- If destination is present:
  - ALWAYS provide a starter set of attractions FIRST (at least 8–12 items).
  - Group them by theme (e.g., "Top sights", "Neighborhoods", "Museums", "Food/markets", "Views & parks").
  - Only AFTER the list, you MAY ask ONE optional follow-up question to personalize.
  - Do NOT ask for interests as a prerequisite when destination is already known.
- If destination is missing:
  - Ask ONE clarification question: "Which city/country are you visiting?"
""".strip()

    packing_policy = """
PACKING RESPONSE POLICY (MUST FOLLOW):
- If destination is present:
  - ALWAYS provide a starter packing list FIRST (do not block on missing dates/season).
  - If dates/season are missing, assume a moderate baseline (layers + a light rain option) and keep it generic.
  - AFTER the list, you MAY ask ONE optional follow-up question to refine.
- If destination is missing:
  - Ask ONE clarification question: "Which city/country are you visiting?"
""".strip()

    currency_policy = """
CURRENCY RESPONSE POLICY (MUST FOLLOW):
- If CURRENCY_TOOL_DATA is provided:
  - Use ONLY that tool data for numeric values (rate, converted_amount).
  - Mention the rate date if present.
- If CURRENCY_TOOL_DATA is NOT provided:
  - Do NOT invent an exchange rate.
  - Ask ONE clarification OR explain that rates could not be fetched.
""".strip()

    internal_scaffold = """
INTERNAL STEPS (DO NOT OUTPUT):
1) Identify the user’s goal from intent and the latest message.
2) Check trip context + any tool data; list what’s missing mentally.
3) Decide: use tool data only for numbers; if no tool data, avoid exact forecasts/rates.
4) Generate the best helpful travel answer for this intent.
5) Self-check: comply with policies + output rules; output ONLY the final answer.
""".strip()

    return f"""
User intent: {intent.value}

Trip context (source of truth):
{json.dumps(context, ensure_ascii=False)}
{weather_hint if intent == Intent.WEATHER_QUERY else ""}
{seasonal_weather_template if intent == Intent.WEATHER_QUERY else ""}

{weather_policy if intent == Intent.WEATHER_QUERY else ""}
{attractions_policy if intent == Intent.ATTRACTIONS_RECOMMENDATIONS else ""}
{packing_policy if intent == Intent.PACKING_LIST else ""}
{currency_policy if intent == Intent.CURRENCY_CONVERSION else ""}

{tool_block}

{internal_scaffold}

STRICT OUTPUT RULES:
- Output ONLY the final answer to the user.
- Do NOT include preambles like “Okay…”, “I will…”, “The user wants…”.
- Do NOT describe your reasoning.
- No analysis, no internal notes.
- Do NOT output JSON.
- Do NOT output tool code blocks.

Task:
Generate a helpful travel response for the user based on the intent and trip context.
If key info is missing, ask at most ONE short clarification question.

{history_block}
""".strip()
