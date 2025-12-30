# Role: LLM-backed intent classification + structured extraction into TripProfile updates.
# It enforces a strict "single JSON object" contract, repairs common violations, and applies overrides
# based on pending clarification slots (especially for currency flows).

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import backend.config as config
from backend.llm.gemini_client import GeminiClient
from backend.models.intent import Intent
from backend.prompts.intent_prompt import build_intent_prompt


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    confidence: float
    extracted_updates: Dict[str, Any]
    missing_info: List[str]
    raw_text: str


class IntentClassifier:
    """
    LLM-backed intent classification + structured extraction.

    Contract:
    - We ask the model to return a single JSON object only.
    - In practice, models sometimes wrap JSON in code fences or add extra text.
    - We parse defensively and (optionally) log when the contract was violated.
    """

    def __init__(self, client: Optional[GeminiClient] = None) -> None:
        self.client = client or GeminiClient()

    def classify(
        self,
        user_message: str,
        recent_messages: Optional[List[dict]] = None,
        pending_missing_info: Optional[List[str]] = None,
    ) -> IntentResult:
        # 1) Build strict prompt with allowed intents + extraction schema
        # 2) Call LLM
        # 3) Parse JSON (with repairs)
        # 4) Apply "pending slot" overrides (prevents drift in clarification loops)
        # 5) Return structured IntentResult

        prompt = build_intent_prompt(
            user_message,
            recent_messages=recent_messages,
            pending_missing_info=pending_missing_info,
        )

        raw = self.client.generate_text(prompt)

        if config.DEBUG:
            print("\n--- INTENT CLASSIFIER ---")
            print("USER MESSAGE:", user_message)
            if recent_messages:
                print("RECENT MESSAGES:", recent_messages)
            if pending_missing_info:
                print("PENDING MISSING INFO:", pending_missing_info)
            print("RAW LLM OUTPUT:\n", raw)

        parsed, parse_meta = self._try_parse_json(raw)

        if not parsed:
            return self._fallback(raw)

        if parse_meta.get("repaired") and config.DEBUG:
            print(
                "WARNING: IntentClassifier received non-strict JSON output "
                f"(repaired={parse_meta})."
            )

        intent = self._parse_intent(parsed.get("intent"))
        confidence = self._parse_confidence(parsed.get("confidence"))
        extracted_updates = self._parse_dict(parsed.get("extracted_updates"))
        missing_info = self._parse_list_of_strings(parsed.get("missing_info"))

        if intent is None:
            return self._fallback(raw)

        # Key idea: when we're in a clarification loop, keep the intent stable (especially currency).
        if pending_missing_info:
            pending = pending_missing_info[0]
            currency_fields = {"currency_pair", "currency_amount", "currency_from", "currency_to"}

            if pending in currency_fields:
                # Key line: keep currency intent stable during pending slots,
                # but allow itinerary continuation to proceed when currency_amount is pending.
                if pending == "currency_amount":
                    is_amount = (
                        self._looks_like_amount_only(user_message)
                        or ("$" in user_message)
                        or ("usd" in user_message.lower())
                        or ("eur" in user_message.lower())
                    )
                    is_pair = self._looks_like_currency_pair(user_message)

                    if self._looks_like_itinerary_continue(user_message) and not is_amount and not is_pair:
                        # Key line: do NOT force currency intent here; user is resuming primary goal.
                        pass
                    else:
                        if intent != Intent.CURRENCY_CONVERSION:
                            if config.DEBUG:
                                print(
                                    f"OVERRIDE: intent {intent} -> CURRENCY_CONVERSION (pending={pending})"
                                )
                            intent = Intent.CURRENCY_CONVERSION
                            confidence = max(confidence, 0.6)
                else:
                    if intent != Intent.CURRENCY_CONVERSION:
                        if config.DEBUG:
                            print(f"OVERRIDE: intent {intent} -> CURRENCY_CONVERSION (pending={pending})")
                        intent = Intent.CURRENCY_CONVERSION
                        confidence = max(confidence, 0.6)

                # Wrong-type follow-ups: user provides amount when we need pair (and vice-versa).
                if pending == "currency_pair" and self._looks_like_amount_only(user_message):
                    if config.DEBUG:
                        print("OVERRIDE: still missing currency_pair (user provided amount-only)")
                    missing_info = ["currency_pair"]

                if pending == "currency_amount" and self._looks_like_currency_pair(user_message):
                    if config.DEBUG:
                        print("OVERRIDE: still missing currency_amount (user provided pair-only)")
                    missing_info = ["currency_amount"]

        # Guardrail: generic help stays in-scope and goes to goal selection.
        if intent == Intent.OUT_OF_SCOPE and self._looks_like_generic_help(user_message):
            if config.DEBUG:
                print("OVERRIDE: OUT_OF_SCOPE -> CLARIFICATION_NEEDED (generic help message)")
            intent = Intent.CLARIFICATION_NEEDED
            confidence = max(confidence, 0.6)
            missing_info = []
            extracted_updates = extracted_updates or {}

        if config.DEBUG:
            print("PARSED INTENT:", intent)
            print("EXTRACTED UPDATES:", extracted_updates)
            print("------------------------\n")

        return IntentResult(
            intent=intent,
            confidence=confidence,
            extracted_updates=extracted_updates,
            missing_info=missing_info,
            raw_text=raw,
        )

    def _strip_code_fences(self, text: str) -> str:
        # Role: remove markdown fences if model incorrectly wrapped JSON.
        if not text:
            return ""
        t = text.strip()

        if t.startswith("```"):
            t = re.sub(r"^\s*```(?:json)?\s*", "", t, flags=re.IGNORECASE)
            t = re.sub(r"\s*```\s*$", "", t)
        return t.strip()

    def _try_parse_json(self, text: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        # 1) strict json.loads
        # 2) strip code fences
        # 3) extract {...} substring as last attempt
        raw = (text or "").strip()

        try:
            return json.loads(raw), {"repaired": False, "method": "strict"}
        except json.JSONDecodeError:
            pass

        cleaned = self._strip_code_fences(raw)
        if cleaned != raw:
            try:
                return json.loads(cleaned), {"repaired": True, "method": "stripped_fences"}
            except json.JSONDecodeError:
                pass

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = cleaned[start : end + 1]
            try:
                return json.loads(candidate), {"repaired": True, "method": "extracted_braces"}
            except json.JSONDecodeError:
                return None, {"repaired": True, "method": "failed"}

        return None, {"repaired": False, "method": "failed"}

    def _parse_intent(self, value: Any) -> Optional[Intent]:
        if not isinstance(value, str):
            return None
        try:
            return Intent(value)
        except ValueError:
            return None

    def _parse_confidence(self, value: Any) -> float:
        try:
            c = float(value)
        except (TypeError, ValueError):
            return 0.0
        return min(max(c, 0.0), 1.0)

    def _parse_dict(self, value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _parse_list_of_strings(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    def _fallback(self, raw_text: str) -> IntentResult:
        # Role: safe default when parsing fails -> ask user to pick a goal (FlowController handles it).
        if config.DEBUG:
            print("\n--- INTENT FALLBACK TRIGGERED ---")
            print("RAW TEXT:", raw_text)
            print("--------------------------------\n")

        return IntentResult(
            intent=Intent.CLARIFICATION_NEEDED,
            confidence=0.0,
            extracted_updates={},
            missing_info=["destination", "dates_or_duration"],
            raw_text=raw_text or "",
        )

    def _looks_like_generic_help(self, text: str) -> bool:
        t = (text or "").strip().lower()
        return t in {
            "help",
            "help me",
            "i need help",
            "need help",
            "not sure",
            "not sure what to ask",
            "what can you do",
            "what do you do",
            "how can you help",
            "can you help",
            "please help",
            "pls help",
        }

    def _looks_like_amount_only(self, text: str) -> bool:
        t = (text or "").strip()
        return bool(re.fullmatch(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", t))

    def _looks_like_currency_pair(self, text: str) -> bool:
        t = (text or "").strip().upper()
        return bool(re.search(r"\b[A-Z]{3}\s*(?:TO|->|-|/)\s*[A-Z]{3}\b", t))

    def _looks_like_itinerary_continue(self, text: str) -> bool:
        t = (text or "").lower().strip()
        markers = (
            "continue",
            "keep going",
            "go on",
            "resume",
            "itinerary",
            "plan",
            "schedule",
            "day ",
            "make day",
        )
        return any(m in t for m in markers)