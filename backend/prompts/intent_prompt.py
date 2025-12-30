# Role: Strict prompt template for intent classification + extraction. It teaches the LLM a rigid JSON schema,
# includes date rules (today/tomorrow/in N days), and supports "pending clarification" behavior.

from __future__ import annotations

import json
from datetime import date
from typing import List, Optional

from backend.models.intent import Intent


def build_intent_prompt(
    user_message: str,
    recent_messages: Optional[List[dict]] = None,
    pending_missing_info: Optional[List[str]] = None,
) -> str:
    # Step 1: gather allowed intents and "today" for date normalization rules.
    intents = [i.value for i in Intent]
    today = date.today().isoformat()

    history_block = ""
    if recent_messages:
        formatted = "\n".join([f'{m["role"]}: {m["content"]}' for m in recent_messages])
        history_block = f"\n\nRecent conversation:\n{formatted}"

    # Step 2: if we are mid-clarification, add a "SYSTEM STATE" hint to keep the model on track.
    pending_block = ""
    if pending_missing_info:
        missing = pending_missing_info[0]

        if missing == "goal":
            pending_block = (
                "\n\nPENDING_CLARIFICATION (SYSTEM STATE):\n"
                "- The system previously asked the user to choose a goal: itinerary / attractions / packing / weather / currency conversion.\n"
                "- If the user's message is one of these (or a clear synonym), classify accordingly:\n"
                "  - itinerary/plan/route/schedule -> intent='itinerary_planning'\n"
                "  - attractions/things to do/activities -> intent='attractions_recommendations'\n"
                "  - pack/packing/what to bring -> intent='packing_list'\n"
                "  - weather/temperature/rain -> intent='weather_query'\n"
                "  - currency/exchange rate/convert -> intent='currency_conversion'\n"
                "- Treat it as a NEW goal selection (not a destination update).\n"
                "- If the message is clearly a NEW travel question instead, classify normally.\n"
            )
        else:
            currency_fields = {"currency_pair", "currency_amount", "currency_from", "currency_to"}

            if missing in currency_fields:
                pending_block = (
                    "\n\nPENDING_CLARIFICATION (SYSTEM STATE):\n"
                    f"- The system previously asked the user for: {missing}\n"
                    "- This is part of a CURRENCY CONVERSION flow.\n"
                    "- You MUST classify intent='currency_conversion'.\n"
                    "- Treat the user's message as the answer to the missing field:\n"
                    "  - currency_amount: a number like '200' or '200.50'\n"
                    "  - currency_from: a 3-letter code or common name (USD, EUR, dollars, shekels)\n"
                    "  - currency_to: a 3-letter code or common name (ILS, EUR, pounds)\n"
                    "  - currency_pair: formats like 'USD to ILS', 'EUR/GBP', 'USD-EUR'\n"
                    "- WRONG-TYPE FOLLOW-UP HANDLING (IMPORTANT):\n"
                    "  - If missing field is currency_pair AND the user's message is only a number (e.g., '100'):\n"
                    "    - intent MUST still be 'currency_conversion'\n"
                    "    - notes should say the user provided an amount but we still need the currency pair (e.g., 'USD to EUR')\n"
                    "    - set missing_info=['currency_pair']\n"
                    "  - If missing field is currency_amount AND the user's message looks like only a currency pair (e.g., 'USD to EUR'):\n"
                    "    - intent MUST still be 'currency_conversion'\n"
                    "    - notes should say the user provided the pair but we still need the amount\n"
                    "    - set missing_info=['currency_amount']\n"
                    "- Do NOT classify these short answers as constraints_update.\n"
                    "- Do NOT output intent='clarification_needed' for these answers.\n"
                    "- If the user's message is clearly a NEW travel question, classify normally.\n"
                )
            else:
                pending_block = (
                    "\n\nPENDING_CLARIFICATION (SYSTEM STATE):\n"
                    f"- The system previously asked the user for: {missing}\n"
                    "- Treat the user's message as an answer to this missing field if possible.\n"
                    "- If the user's message is clearly a NEW travel question (not an answer), classify normally.\n"
                )

    # Key lines: examples anchor the JSON format and teach follow-up answers as constraints_update.
    good_example = {
        "intent": "weather_query",
        "confidence": 0.9,
        "extracted_updates": {
            "destination": "Rome",
            "start_date": today,
            "end_date": None,
            "duration_days": None,
            "budget": None,
            "travelers": None,
            "interests": [],
            "pace": None,
            "constraints": [],
        },
        "missing_info": [],
        "notes": "User asked about weather today.",
    }

    bad_example_description = (
        "BAD (INVALID) OUTPUT EXAMPLE (do NOT copy): "
        "a JSON object wrapped in markdown/code fences (a 'json' fenced block)."
    )

    followup_city_example = {
        "intent": "constraints_update",
        "confidence": 0.85,
        "extracted_updates": {
            "destination": "Paris",
            "start_date": None,
            "end_date": None,
            "duration_days": None,
            "budget": None,
            "travelers": None,
            "interests": [],
            "pace": None,
            "constraints": [],
        },
        "missing_info": [],
        "notes": "Follow-up answer: destination provided.",
    }

    followup_duration_example = {
        "intent": "constraints_update",
        "confidence": 0.85,
        "extracted_updates": {
            "destination": None,
            "start_date": None,
            "end_date": None,
            "duration_days": 5,
            "budget": None,
            "travelers": None,
            "interests": [],
            "pace": None,
            "constraints": [],
        },
        "missing_info": [],
        "notes": "Follow-up answer: duration provided.",
    }

    return f"""
ROLE:
You are a STRICT intent-classification component for a Travel Assistant system.
Your job is ONLY:
(1) classify intent
(2) extract structured updates
You must NOT answer the user.

HARD OUTPUT CONTRACT (NON-NEGOTIABLE):
- Output MUST be EXACTLY ONE raw JSON object.
- Output MUST start with '{{' and end with '}}'.
- Output MUST contain NO markdown and NO code fences.
- Do NOT wrap the JSON in any kind of fenced block. Do NOT add headings or extra text.

{bad_example_description}

VALID OUTPUT EXAMPLE (copy this style):
{json.dumps(good_example, ensure_ascii=False)}

Allowed intents (choose exactly ONE):
{json.dumps(intents, ensure_ascii=False)}

Rules:
1) Weather/best time/temps/rain/wind -> intent="weather_query"
2) Day-by-day plan -> intent="itinerary_planning"
3) Attractions/things to do -> intent="attractions_recommendations"
4) What to pack -> intent="packing_list"
5) Currency conversion / exchange rate / convert money / "USD to ILS" -> intent="currency_conversion"
6) Any preferences/constraints update (kids, budget, pace, vegetarian, wheelchair, etc.) -> intent="constraints_update"
7) If the user says generic help / unsure (e.g., "help", "help me", "I need help", "not sure what to ask")
   -> intent="clarification_needed" (this is in-scope onboarding; NOT out_of_scope)

IMPORTANT DATE RULES:
- Today (server date) is: {today}
- If user says "today" -> start_date={today}, end_date=null
- If user says "tomorrow" -> start_date=(today+1 day) as ISO YYYY-MM-DD, end_date=null
- If user says "in N days" -> start_date=(today+N days) as ISO YYYY-MM-DD, end_date=null
- If user says "on YYYY-MM-DD" -> start_date=that date
- If user says "from YYYY-MM-DD to YYYY-MM-DD" -> start_date and end_date
- Always output ISO YYYY-MM-DD only.
- If weather question gives NO date -> leave start_date/end_date as null.

MONTH WITHOUT YEAR RULE (CRITICAL):
- If the user mentions a month name (e.g., "January") WITHOUT a year,
  interpret it as the NEXT upcoming occurrence of that month relative to Today.
- For month-only trips, set:
  start_date = YYYY-MM-01
  end_date   = YYYY-MM-(last day of month)
- Never output dates in the past unless the user explicitly gave a year in the past.

FOLLOW-UP ANSWERS (CRITICAL):
If the message looks like a short follow-up answering ONE missing trip detail
(city name like "Rome", duration like "5 days", dates, budget),
THEN:
- intent="constraints_update"
- put the parsed value into extracted_updates
- missing_info=[]

clarification_needed is ONLY for travel-related messages that cannot be interpreted
as ANY structured update AND do not match any intent.

If NOT travel-related AND NOT a generic help/unsure message -> intent="out_of_scope"
{pending_block}

Output JSON schema (fill all keys; use null/[] where unknown):
{{
  "intent": "<allowed intent>",
  "confidence": <0.0..1.0>,
  "extracted_updates": {{
     "destination": <string or null>,
     "start_date": <YYYY-MM-DD or null>,
     "end_date": <YYYY-MM-DD or null>,
     "duration_days": <integer or null>,
     "budget": <"low"|"mid"|"high" or null>,
     "travelers": <string or null>,
     "interests": <list of strings>,
     "pace": <"relaxed"|"balanced"|"intense" or null>,
     "constraints": <list of strings>
  }},
  "missing_info": <list of strings>,
  "notes": <string>
}}

Follow-up examples:
User message: Paris
{json.dumps(followup_city_example, ensure_ascii=False)}

User message: 5 days
{json.dumps(followup_duration_example, ensure_ascii=False)}

Now classify:
{history_block}

User message: {user_message}
""".strip()
