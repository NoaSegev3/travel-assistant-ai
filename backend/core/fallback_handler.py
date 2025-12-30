# Role: Recovery path when something breaks. Prefer deterministic clarifications first;
# only use the LLM if we have enough info but still failed to produce an answer.

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from backend.core.validator import Validator
from backend.llm.gemini_client import GeminiClient
from backend.models.intent import Intent
from backend.models.state import State
from backend.prompts.fallback_prompt import build_fallback_prompt
from backend.prompts.system_prompt import build_system_prompt
from backend.utils.clarification import build_clarification_question

_GOAL_INTENTS = {
    Intent.ITINERARY_PLANNING,
    Intent.ATTRACTIONS_RECOMMENDATIONS,
    Intent.PACKING_LIST,
    Intent.WEATHER_QUERY,
    Intent.CURRENCY_CONVERSION,
}


@dataclass(frozen=True)
class FallbackResult:
    message: str
    used_llm: bool
    pending_missing_info: List[str]
    resolved_intent: Optional[Intent] = None


class FallbackHandler:
    def __init__(self, client: Optional[GeminiClient] = None, validator: Optional[Validator] = None) -> None:
        # Key line: lazy-init avoids crashing if GEMINI_API_KEY is missing (deterministic fallbacks still work).
        self._client = client
        self.validator = validator or Validator()

    def _get_client(self) -> GeminiClient:
        if self._client is None:
            self._client = GeminiClient()
        return self._client

    def recover(
        self,
        *,
        state: State,
        user_message: str,
        intent_for_flow: Optional[Intent] = None,
        recent_messages: Optional[List[Dict[str, str]]] = None,
        error: Optional[str] = None,
    ) -> FallbackResult:
        # 1) If mid-clarification -> ask that question again (deterministic).
        # 2) If no active goal -> ask user to choose a goal (deterministic).
        # 3) Validate the chosen goal -> ask the next missing required field (deterministic).
        # 4) Otherwise -> build fallback prompt and use LLM as last resort.

        if state.pending_missing_info:
            pending = state.pending_missing_info[:1]
            q = build_clarification_question(pending)
            return FallbackResult(message=q, used_llm=False, pending_missing_info=pending)

        active_goal = state.last_intent if state.last_intent in _GOAL_INTENTS else None
        if active_goal is None and (intent_for_flow not in _GOAL_INTENTS):
            return FallbackResult(
                message="What would you like help with: itinerary, attractions, packing, weather, or currency conversion?",
                used_llm=False,
                pending_missing_info=["goal"],
                resolved_intent=None,
            )

        goal = intent_for_flow if intent_for_flow in _GOAL_INTENTS else active_goal

        if goal is not None:
            validation = self.validator.validate(goal, state)
            if not validation.ok:
                pending = (validation.missing_info or [])[:1]
                q = build_clarification_question(pending)
                return FallbackResult(
                    message=q,
                    used_llm=False,
                    pending_missing_info=pending,
                    resolved_intent=goal,
                )

        system_prompt = build_system_prompt()
        fallback_prompt = build_fallback_prompt(
            intent=goal,
            state=state,
            user_message=user_message,
            recent_messages=recent_messages,
            error=error,
        )
        full_prompt = f"{system_prompt}\n\n{fallback_prompt}"
        text = (self._get_client().generate_text(full_prompt) or "").strip()

        if not text:
            return FallbackResult(
                message="I can help with itineraries, attractions, packing, weather, or currency conversion. What would you like to do next?",
                used_llm=False,
                pending_missing_info=["goal"],
                resolved_intent=goal,
            )

        return FallbackResult(
            message=text,
            used_llm=True,
            pending_missing_info=[],
            resolved_intent=goal,
        )
