# Role: Safety filter that enforces "no hallucinated numbers / no fake real-time claims".
# It rewrites risky outputs when tool_data is missing, especially for weather + currency.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend.models.intent import Intent


@dataclass(frozen=True)
class TrustResult:
    text: str
    flagged: bool
    reasons: list[str]


class TrustLayer:
    _REALTIME_CLAIMS = (
        "real-time",
        "live data",
        "right now",
        "currently",
        "as of now",
        "i just checked",
        "i checked online",
        "i looked it up",
        "from the internet",
        "according to google",
    )

    def apply(
        self,
        *,
        intent: Intent,
        assistant_text: str,
        tool_data: Optional[Dict[str, Any]] = None,
        user_message: Optional[str] = None,
    ) -> TrustResult:
        # 1) Remove any leaked tool-code patterns
        # 2) Remove/soften "real-time" claims unless explicitly requested in live-weather scenarios
        # 3) Weather: block exact daily/live claims without tool_data
        # 4) Currency: block rates/conversions without tool_data

        text = (assistant_text or "").strip()
        if not text:
            return TrustResult(text=text, flagged=False, reasons=[])

        reasons: list[str] = []

        if self._looks_like_tool_code(text):
            reasons.append("tool_code_leak")
            text = self._strip_tool_code_fences(text)

        low = text.lower()
        realtime_hit = any(p in low for p in self._REALTIME_CLAIMS)

        if realtime_hit and not (intent == Intent.WEATHER_QUERY and self._user_requested_live(user_message or "")):
            reasons.append("realtime_claim")
            text = self._rewrite_no_realtime_claim(text)

        if intent == Intent.WEATHER_QUERY:
            u = user_message or ""

            if tool_data is None and self._user_requested_exact_daily(u):
                reasons.append("exact_daily_weather_without_tool")
                text = self._safe_weather_without_tool(u)

            elif self._user_requested_live(u):
                reasons.append("live_weather_request")
                text = self._safe_live_weather_response(tool_data)

            elif tool_data is None:
                if self._contains_specific_forecast_numbers(text, u):
                    reasons.append("weather_numbers_without_tool")
                    text = self._safe_weather_without_tool(u)

        if intent == Intent.CURRENCY_CONVERSION and tool_data is None:
            if self._contains_currency_rate_or_conversion(text):
                reasons.append("currency_numbers_without_tool")
                text = self._safe_currency_without_tool()

        return TrustResult(text=text, flagged=bool(reasons), reasons=reasons)

    def _looks_like_tool_code(self, text: str) -> bool:
        # Role: detect LLM leaking internal "tool_code" or pseudo-calls.
        low = text.lower()
        return (
            "```tool_code" in low
            or "currency_conversion(" in low
            or "weather(" in low
            or "invoke-restmethod" in low
        )

    def _strip_tool_code_fences(self, text: str) -> str:
        return text.replace("```tool_code", "").replace("```", "").strip()

    def _rewrite_no_realtime_claim(self, text: str) -> str:
        # Key line: replaces "I checked online" style claims with a neutral phrase.
        cleaned = text
        for p in self._REALTIME_CLAIMS:
            cleaned = re.sub(re.escape(p), "based on available info", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _contains_specific_forecast_numbers(self, text: str, user_message: str = "") -> bool:
        # Role: detect "forecast-like" numeric claims (°C, mm, wind) that look too specific for seasonal guidance.
        low = text.lower()
        user_low = (user_message or "").lower()

        seasonal_markers = (
            "typical",
            "usually",
            "generally",
            "on average",
            "average",
            "around",
            "roughly",
            "expect average",
            "seasonal",
            "in general",
            "often",
            "range of",
            "ranges from",
            "between",
        )

        if any(m in low for m in seasonal_markers) and not self._user_requested_exact_daily(user_message):
            return False

        specific_request_markers = (
            "exact",
            "daily",
            "each day",
            "day-by-day",
            "right now",
            "live",
            "currently",
            "today",
            "tomorrow",
            "on ",
        )
        strict = any(m in user_low for m in specific_request_markers)

        patterns = [
            r"\b-?\d{1,2}\s*°\s*c\b",
            r"\b-?\d{1,3}\s*°\s*f\b",
            r"\b\d{1,3}\s*mm\b",
            r"\b\d{1,3}\s*km\/h\b",
            r"\b\d{1,3}\s*kmh\b",
            r"\bhighs?\s+of\s+\d{1,2}\b",
            r"\blows?\s+of\s+\d{1,2}\b",
        ]

        has_numbers = any(re.search(p, low) for p in patterns)

        forecast_claim_markers = (
            "on ",
            "tomorrow",
            "today",
            "this weekend",
            "next week",
            "expect a high of",
            "expect a low of",
        )
        sounds_like_forecast = any(m in low for m in forecast_claim_markers)

        return bool(has_numbers and (strict or sounds_like_forecast))

    def _contains_currency_rate_or_conversion(self, text: str) -> bool:
        # Role: detect conversions/rates (e.g., "rate of 0.84", "100 USD converts to ...") without tool grounding.
        if not text:
            return False

        low = text.lower()

        patterns = [
            r"\brate\s+of\s+\d+(\.\d+)?\b",
            r"\b\d+(\.\d+)?\s*(usd|eur|ils|gbp|jpy)\b",
            r"\b(usd|eur|ils|gbp|jpy)\s*\d+(\.\d+)?\b",
            r"[$€₪]\s*\d+(\.\d+)?",
            r"\bconverts\s+to\s+\d+(\.\d+)?\b",
            r"\bexchange\s+rate\b.*\d",
        ]

        return any(re.search(p, low, flags=re.IGNORECASE) for p in patterns)

    def _safe_weather_without_tool(self, user_message: str) -> str:
        # Role: standard safe response when we cannot use weather tool data.
        u = (user_message or "").lower()

        if any(k in u for k in ("right now", "live", "currently", "today")):
            return (
                "I can’t guarantee a *live* weather reading without calling the weather API.\n\n"
                "If you confirm the city (e.g., Paris) I can fetch today’s forecast from the tool, "
                "or I can give seasonal guidance if you’re planning ahead."
            )

        if any(
            k in u
            for k in (
                "in january",
                "in february",
                "in march",
                "in april",
                "in may",
                "in june",
                "in july",
                "in august",
                "in september",
                "in october",
                "in november",
                "in december",
                "this winter",
                "this summer",
                "season",
            )
        ):
            return (
                "I can’t provide exact day-by-day numbers that far in advance. Forecasts are typically reliable only up to ~16 days ahead.\n\n"
                "If you want, tell me your rough dates or how sensitive you are to rain/cold, and I’ll give seasonal expectations + a packing list."
            )

        return (
            "I can’t fetch an exact forecast for that date right now (forecasts are typically only available/reliable up to ~16 days ahead).\n\n"
            "If you share your dates (or even just the month), I can give seasonal expectations and packing advice."
        )

    def _safe_currency_without_tool(self) -> str:
        return (
            "I can help convert currency, but I couldn’t fetch a live exchange rate right now.\n"
            "Please send it like: **“100 USD to EUR”** (amount + from + to)."
        )

    def _user_requested_exact_daily(self, user_message: str) -> bool:
        u = (user_message or "").lower()
        triggers = (
            "exact daily",
            "day-by-day",
            "day by day",
            "each day",
            "every day",
            "for each day",
            "daily highs",
            "daily lows",
            "precipitation in mm for each day",
            "exact highs",
            "exact lows",
            "exact precipitation",
        )
        return any(t in u for t in triggers)

    def _user_requested_live(self, user_message: str) -> bool:
        u = (user_message or "").lower()
        triggers = ("right now", "live", "currently", "as of now", "exact temperature", "0.1")
        return any(t in u for t in triggers)

    def _safe_live_weather_response(self, tool_data: Optional[Dict[str, Any]]) -> str:
        # Role: respond to "live" requests while being honest that tool provides forecast, not observed readings.
        if tool_data and isinstance(tool_data, dict):
            loc = tool_data.get("location", "that city")
            timeframe = tool_data.get("timeframe", "today")
            today = (tool_data.get("today") or {})
            tmin = today.get("temp_min_c")
            tmax = today.get("temp_max_c")
            precip = today.get("precip_mm")

            parts = ["I can’t guarantee a *live right-now* temperature reading to 0.1°C."]
            parts.append(f"What I *can* fetch is today’s forecast summary for {loc} ({timeframe}).")

            if tmin is not None and tmax is not None:
                parts.append(f"Today’s forecast range: low {tmin}°C, high {tmax}°C.")
            if precip is not None:
                parts.append(f"Forecast precipitation: {precip} mm.")

            parts.append("If you still need *current observed temperature*, use a live weather app/station feed.")
            return "\n\n".join(parts)

        return (
            "I can’t guarantee a *live right-now* weather reading without calling the weather API.\n\n"
            "If you confirm the city (e.g., Paris) I can fetch today’s forecast from the tool."
        )
