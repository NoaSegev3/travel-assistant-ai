# Role: Produces the final assistant text. Uses deterministic formatting when tool_data exists (currency),
# otherwise calls the LLM with system+user prompts, then cleans up common "assistant preamble" artifacts.

from __future__ import annotations

from typing import Any, Dict, List, Optional

import backend.config as config
from backend.llm.gemini_client import GeminiClient
from backend.models.intent import Intent
from backend.models.state import State
from backend.prompts.response_prompt import build_response_prompt
from backend.prompts.system_prompt import build_system_prompt
from backend.utils.weather_rules import mentions_month, is_seasonal_weather_question


class ResponseGenerator:
    def __init__(self, client: Optional[GeminiClient] = None) -> None:
        self.client = client or GeminiClient()

    def _clean_llm_output(self, text: str) -> str:
        # Role: remove common filler/preambles without changing actual content.
        if not text:
            return text

        lines = [ln.rstrip() for ln in text.strip().splitlines()]

        always_drop_prefixes = (
            "the user",
            "my plan",
            "i will",
            "i'll",
            "i am going to",
            "here's my plan",
            "i have weather data",
        )

        soft_drop_prefixes = ("okay", "ok", "sure", "alright", "got it")

        weather_prefixes = (
            "here's the weather",
            "here is the weather",
            "here are the weather",
            "here's the forecast",
            "here is the forecast",
        )

        cleaned: list[str] = []
        skipping = True

        for ln in lines:
            low = ln.strip().lower()
            low_norm = low.rstrip(":,.-! ")

            if skipping:
                if not low_norm:
                    continue

                if any(low_norm.startswith(p) for p in always_drop_prefixes):
                    continue

                if any(low_norm.startswith(p) for p in soft_drop_prefixes) and len(low_norm) <= 40:
                    continue

                if any(low_norm.startswith(p) for p in weather_prefixes) and len(low_norm) <= 80:
                    continue

            skipping = False
            cleaned.append(ln)

        out = "\n".join(cleaned).strip()
        return out if out else text.strip()

    def _looks_like_tool_code(self, text: str) -> bool:
        # Role: detect tool-code leak (extra defense; TrustLayer also checks).
        if not text:
            return False
        low = text.lower()
        return "```tool_code" in low or "currency_conversion(" in low or "weather(" in low

    def _strip_tool_code_fences(self, text: str) -> str:
        if not text:
            return text
        return text.replace("```tool_code", "").replace("```", "").strip()

    def _format_currency_from_tool(self, tool_data: Dict[str, Any]) -> str:
        # Role: deterministic user-facing format for currency conversions (tool_data is source of truth).
        rate_date = tool_data.get("date")
        base = tool_data.get("base")
        to = tool_data.get("to")
        rate = tool_data.get("rate")
        amount = tool_data.get("amount")
        converted = tool_data.get("converted_amount")

        try:
            amount_f = float(amount)
        except Exception:
            amount_f = amount

        try:
            converted_f = float(converted)
        except Exception:
            converted_f = converted

        if rate_date and base and to and rate is not None and amount is not None and converted is not None:
            return (
                f"Based on data from {rate_date}, {amount_f:g} {base} converts to {converted_f:.2f} {to} "
                f"at a rate of {rate}."
            )

        return (
            "I fetched the exchange rate, but couldn’t format the conversion cleanly. "
            "Try again with something like “100 USD to EUR”."
        )

    def generate(
        self,
        intent: Intent,
        state: State,
        recent_messages: Optional[List[Dict]] = None,
        tool_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        # 1) If currency + tool_data -> deterministic formatter (no LLM)
        # 2) Else -> build prompts -> call LLM
        # 3) Clean output (preambles, tool-code leaks)
        if intent == Intent.CURRENCY_CONVERSION and tool_data is not None:
            out = self._format_currency_from_tool(tool_data)

            if config.DEBUG:
                print("\n--- RESPONSE GENERATOR (DETERMINISTIC) ---")
                print("INTENT:", intent)
                print("TOOL DATA:", tool_data)
                print("OUTPUT:", out)
                print("----------------------------------------\n")

            return out

        system_prompt = build_system_prompt()

        last_user_msg = ""
        for m in reversed(recent_messages or []):
            if m.get("role") == "user":
                last_user_msg = (m.get("content") or "").strip()
                break

        force_seasonal = (
            intent == Intent.WEATHER_QUERY
            and tool_data is None
            and (mentions_month(last_user_msg) or is_seasonal_weather_question(last_user_msg))
        )

        user_prompt = build_response_prompt(
            intent=intent,
            state=state,
            recent_messages=recent_messages,
            tool_data=tool_data,
            force_seasonal=force_seasonal,
        )

        if config.DEBUG:
            print("\n--- RESPONSE GENERATOR ---")
            print("INTENT:", intent)
            print("TRIP CONTEXT:", state.trip_profile.model_dump())
            if tool_data is not None:
                print("TOOL DATA:", tool_data)
            if recent_messages:
                print("RECENT:", recent_messages)
            print("-------------------------")

        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self.client.generate_text(full_prompt)

        if config.DEBUG:
            raw_preview = (response or "").strip()
            print(
                "RAW RESPONSE (preview):\n",
                raw_preview[:600] + ("..." if len(raw_preview) > 600 else ""),
            )
            print("-------------------------")

        response = self._clean_llm_output(response or "")

        if self._looks_like_tool_code(response):
            response = self._strip_tool_code_fences(response)

        if config.DEBUG:
            print("CLEANED RESPONSE:\n", response)
            print("-------------------------\n")

        return response
