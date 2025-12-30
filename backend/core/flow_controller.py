# backend/core/flow_controller.py
# Role: Orchestrator for one conversation turn. It glues together:
# state management, intent classification, validation, decision routing, tool calls, trust checks, and persistence.

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as dt_date
from typing import Optional

import backend.config as config
from backend.core.decision_logic import DecisionLogic
from backend.core.fallback_handler import FallbackHandler
from backend.core.state_manager import StateManager
from backend.core.trust_layer import TrustLayer
from backend.core.validator import Validator
from backend.llm.intent_classifier import IntentClassifier
from backend.llm.response_generator import ResponseGenerator
from backend.models.decision import Action, Decision
from backend.models.intent import Intent
from backend.models.state import State
from backend.tools.currency_client import CurrencyClient
from backend.tools.weather_client import WeatherClient
from backend.utils.clarification import build_clarification_question
from backend.utils.weather_rules import mentions_month

_GOAL_INTENTS = {
    Intent.ITINERARY_PLANNING,
    Intent.ATTRACTIONS_RECOMMENDATIONS,
    Intent.PACKING_LIST,
    Intent.WEATHER_QUERY,
    Intent.CURRENCY_CONVERSION,
}


@dataclass(frozen=True)
class TurnResponse:
    session_id: str
    assistant_message: str


class FlowController:
    def __init__(
        self,
        state_manager: Optional[StateManager] = None,
        intent_classifier: Optional[IntentClassifier] = None,
        validator: Optional[Validator] = None,
        decision_logic: Optional[DecisionLogic] = None,
        response_generator: Optional[ResponseGenerator] = None,
        weather_client: Optional[WeatherClient] = None,
        currency_client: Optional[CurrencyClient] = None,
        fallback_handler: Optional[FallbackHandler] = None,
        trust_layer: Optional[TrustLayer] = None,
    ) -> None:
        # Key line: dependencies are injectable for testing/mocking.
        self.state_manager = state_manager or StateManager()
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.validator = validator or Validator()
        self.decision_logic = decision_logic or DecisionLogic()
        self.response_generator = response_generator or ResponseGenerator()
        self.weather_client = weather_client or WeatherClient()
        self.currency_client = currency_client or CurrencyClient()
        self.fallback_handler = fallback_handler or FallbackHandler()
        self.trust_layer = trust_layer or TrustLayer()

    def _recent_messages(self, state: State, limit: int = 6) -> list[dict]:
        # Role: compact history format for prompts/classifier.
        msgs = state.conversation_history[-limit:]
        return [{"role": m.role, "content": m.content} for m in msgs]

    def _infer_pending_from_assistant(self, assistant_text: str, intent: Intent, state: State) -> list[str]:
        # Role: heuristic backup for setting pending_missing_info when LLM asks a question.
        if not assistant_text or not assistant_text.rstrip().endswith("?"):
            return []

        if intent in _GOAL_INTENTS and intent != Intent.CURRENCY_CONVERSION:
            validation_result = self.validator.validate(intent, state)
            if validation_result.missing_info:
                return (validation_result.missing_info or [])[:1]

        if intent == Intent.CURRENCY_CONVERSION:
            low = assistant_text.lower()
            if "between" in low or "which currencies" in low:
                return ["currency_pair"]
            if "amount" in low or "how much" in low:
                return ["currency_amount"]
            if "from" in low and "currency" in low:
                return ["currency_from"]
            if "to" in low and "currency" in low:
                return ["currency_to"]

        low = assistant_text.lower()
        if "interest" in low:
            return ["interests"]
        if "budget" in low:
            return ["budget"]
        if "who" in low or "traveling" in low:
            return ["travelers"]
        if "pace" in low:
            return ["pace"]
        if "month" in low:
            return ["dates_or_duration"]
        if "date" in low or "when" in low:
            return ["dates_or_duration"]
        if "where" in low or "city" in low or "country" in low:
            return ["destination"]

        return []

    def _looks_like_full_month_range(self, start_date: dt_date, end_date: dt_date) -> bool:
        # Role: detect "January (no year)" interpreted as full-month range.
        return (
            start_date is not None
            and end_date is not None
            and start_date.year == end_date.year
            and start_date.month == end_date.month
            and start_date.day == 1
            and end_date.day in {28, 29, 30, 31}
        )

    def _guardrail_roll_month_without_year_forward(self, user_message: str, state: State) -> None:
        # Role: if the classifier produced "full month" dates in the past (month without year),
        # roll them forward by +1 year to keep behavior aligned with "next occurrence" rule.
        msg = user_message or ""
        has_year = bool(re.search(r"\b(19|20)\d{2}\b", msg))
        if not (mentions_month(msg) and not has_year):
            return

        start_date = state.trip_profile.start_date
        end_date = state.trip_profile.end_date
        if not (start_date and end_date):
            return

        today = dt_date.today()

        if self._looks_like_full_month_range(start_date, end_date) and end_date < today:
            try:
                state.trip_profile.start_date = start_date.replace(year=start_date.year + 1)
                state.trip_profile.end_date = end_date.replace(year=end_date.year + 1)
                if config.DEBUG:
                    print("GUARDRAIL: Rolled month-only dates forward by +1 year (full-month range)")
            except ValueError:
                # Key line: if invalid date after roll (rare), clear dates to force clarification.
                state.trip_profile.start_date = None
                state.trip_profile.end_date = None
                if config.DEBUG:
                    print("GUARDRAIL: Invalid rolled date; cleared dates to force clarification")

    def handle_turn(self, session_id: str, user_message: str) -> TurnResponse:
        # 1) Load state and classify intent (using recent history + pending slot)
        # 2) Persist user message; apply extracted trip updates
        # 3) Normalize intent for flow (constraints_update -> active goal)
        # 4) Validate -> decide action
        # 5) Execute (tool or LLM), fallback on errors
        # 6) TrustLayer guardrails for non-tool outputs (and for tool outputs inside tool branch)
        # 7) Persist assistant message and return

        state = self.state_manager.get_or_create(session_id)
        prev_intent = state.last_intent
        prev_pending = state.pending_missing_info[:]  # NEW: snapshot pending slots for this turn

        recent_for_intent = self._recent_messages(state, limit=6)
        intent_result = self.intent_classifier.classify(
            user_message=user_message,
            recent_messages=recent_for_intent,
            pending_missing_info=state.pending_missing_info,
        )

        self.state_manager.add_message(session_id, role="user", content=user_message)

        state.trip_profile.apply_updates(intent_result.extracted_updates or {})
        self._guardrail_roll_month_without_year_forward(user_message, state)

        intent_for_flow = intent_result.intent
        active_goal = prev_intent if prev_intent in _GOAL_INTENTS else None

        if intent_for_flow == Intent.CONSTRAINTS_UPDATE:
            # Key line: follow-ups become part of the current goal, not a separate "constraints" mode.
            intent_for_flow = active_goal or Intent.CLARIFICATION_NEEDED

        # Intent bookkeeping
        if intent_for_flow in _GOAL_INTENTS:
            state.last_intent = intent_for_flow
            # NEW: primary_intent tracks "main" flow; currency is an interrupt
            if intent_for_flow != Intent.CURRENCY_CONVERSION:
                state.primary_intent = intent_for_flow

        self.state_manager.increment_turn(state)

        validation = self.validator.validate(intent_for_flow, state)
        decision = self.decision_logic.decide(intent_for_flow, validation, user_message, state)

        # Defensive: if decision is missing, use recovery handler.
        if decision is None:
            fallback = self.fallback_handler.recover(
                state=state,
                user_message=user_message,
                intent_for_flow=intent_for_flow,
                recent_messages=self._recent_messages(state, limit=8),
                error="DecisionLogic returned None",
            )
            assistant_text = fallback.message

            state.pending_missing_info = (
                fallback.pending_missing_info[:1]
                if fallback.pending_missing_info
                else self._infer_pending_from_assistant(assistant_text, intent_for_flow, state)
            )

            if fallback.resolved_intent in _GOAL_INTENTS:
                state.last_intent = fallback.resolved_intent

            trust = self.trust_layer.apply(
                intent=intent_for_flow,
                assistant_text=assistant_text,
                tool_data=None,
                user_message=user_message,
            )

            if config.DEBUG:
                if trust.flagged:
                    print("[TRUST_LAYER] flagged:", trust.reasons)
                print("FINAL (after trust):", trust.text)

            assistant_text = trust.text
            self.state_manager.add_message(session_id, role="assistant", content=assistant_text)
            return TurnResponse(session_id=session_id, assistant_message=assistant_text)

        # Update pending clarification slot (single-field loop).
        if decision.action == Action.ASK_CLARIFICATION:
            state.pending_missing_info = (decision.missing_info or [])[:1]
        else:
            # NEW: keep currency_amount pending if we intentionally answered a non-currency turn
            if prev_pending == ["currency_amount"] and intent_for_flow != Intent.CURRENCY_CONVERSION:
                state.pending_missing_info = prev_pending
            else:
                state.pending_missing_info = []

        if config.DEBUG:
            print("\n--- FLOW DEBUG ---")
            print("SESSION:", session_id)
            print("USER MESSAGE:", user_message)
            print("INTENT (raw):", intent_result.intent)
            print("PREV last_intent:", prev_intent)
            print("INTENT (for flow):", intent_for_flow)
            print("TURN COUNT:", state.turn_count)
            print("STATE last_intent:", state.last_intent)
            # primary_intent may be None if State model doesn't have it yet or never set
            if hasattr(state, "primary_intent"):
                print("STATE primary_intent:", getattr(state, "primary_intent"))
            print("TRIP PROFILE:", state.trip_profile.model_dump())
            print("VALIDATION OK:", validation.ok)
            print("VALIDATION missing_info:", validation.missing_info)
            print("VALIDATION problems:", validation.problems)
            print("DECISION action:", decision.action)
            print("DECISION missing_info:", decision.missing_info)
            print("DECISION tool_name:", decision.tool_name)
            print("DECISION notes:", decision.notes)
            print("PENDING missing_info:", state.pending_missing_info)
            print("------------------\n")

        try:
            assistant_text = self._execute_decision(decision, state, intent_for_flow, user_message)
            if not assistant_text or not assistant_text.strip():
                raise RuntimeError("Empty assistant_text")
        except Exception as e:
            if config.DEBUG:
                print("\n!!! EXECUTION ERROR !!!")
                print(repr(e))
                print("!!! END ERROR !!!\n")

            fallback = self.fallback_handler.recover(
                state=state,
                user_message=user_message,
                intent_for_flow=intent_for_flow,
                recent_messages=self._recent_messages(state, limit=8),
                error=repr(e),
            )
            assistant_text = fallback.message

            state.pending_missing_info = (
                fallback.pending_missing_info[:1]
                if fallback.pending_missing_info
                else self._infer_pending_from_assistant(assistant_text, intent_for_flow, state)
            )

            if fallback.resolved_intent in _GOAL_INTENTS:
                state.last_intent = fallback.resolved_intent

        # Key line: apply TrustLayer to all non-tool responses (tools already pass tool_data into TrustLayer).
        if decision.action != Action.CALL_TOOL:
            trust = self.trust_layer.apply(
                intent=intent_for_flow,
                assistant_text=assistant_text,
                tool_data=None,
                user_message=user_message,
            )
            if config.DEBUG:
                if trust.flagged:
                    print("[TRUST_LAYER] flagged:", trust.reasons)
                print("FINAL (after trust):", trust.text)
            assistant_text = trust.text

        # If LLM asks a question, infer which slot it asked for.
        if decision.action == Action.GENERATE_RESPONSE and not state.pending_missing_info:
            state.pending_missing_info = self._infer_pending_from_assistant(
                assistant_text, intent_for_flow, state
            )

        self.state_manager.add_message(session_id, role="assistant", content=assistant_text)
        return TurnResponse(session_id=session_id, assistant_message=assistant_text)

    def _execute_decision(self, decision: Decision, state: State, intent: Intent, user_message: str) -> str:
        # 1) Deterministic responses for out-of-scope / clarifications
        # 2) Tool branch (weather/currency) -> tool call -> response generation -> TrustLayer with tool_data
        # 3) Default: LLM response generation

        if decision.action == Action.OUT_OF_SCOPE_RESPONSE:
            return (
                "I can help with travel planning only (itineraries, attractions, packing, weather, currency conversion). "
                "What would you like to do?"
            )

        if decision.action == Action.ASK_CLARIFICATION:
            return build_clarification_question(decision.missing_info)

        if decision.action == Action.CALL_TOOL:
            recent_for_response = self._recent_messages(state, limit=8)

            if decision.tool_name == "weather":
                tool_result = self.weather_client.get_weather(state.trip_profile)

                if tool_result.ok:
                    text = self.response_generator.generate(
                        intent=intent,
                        state=state,
                        recent_messages=recent_for_response,
                        tool_data=tool_result.data,
                    )
                    trust = self.trust_layer.apply(
                        intent=intent,
                        assistant_text=text,
                        tool_data=tool_result.data,
                        user_message=user_message,
                    )
                    if config.DEBUG:
                        if trust.flagged:
                            print("[TRUST_LAYER] flagged:", trust.reasons)
                        print("FINAL (after trust):", trust.text)
                    return trust.text

                return (
                    "I couldn’t fetch weather info right now. "
                    "If you tell me your dates (or month), I can still give general seasonal packing tips."
                )

            if decision.tool_name == "currency":
                payload = decision.tool_payload or {}
                amount = payload.get("amount")
                from_ccy = payload.get("from_ccy")
                to_ccy = payload.get("to_ccy")

                if amount is None or from_ccy is None or to_ccy is None:
                    # Defensive fallback: DecisionLogic should always provide these for currency CALL_TOOL
                    return "To convert currency, tell me something like: “100 USD to EUR”."

                tool_result = self.currency_client.convert(
                    amount=float(amount),
                    from_ccy=str(from_ccy),
                    to_ccy=str(to_ccy),
                )

                if tool_result.ok:
                    text = self.response_generator.generate(
                        intent=intent,
                        state=state,
                        recent_messages=recent_for_response,
                        tool_data=tool_result.data,
                    )
                    trust = self.trust_layer.apply(
                        intent=intent,
                        assistant_text=text,
                        tool_data=tool_result.data,
                        user_message=user_message,
                    )

                    # NEW: currency is an interrupt; return control to primary goal (e.g., itinerary).
                    if state.primary_intent is not None:
                        state.last_intent = state.primary_intent

                    if config.DEBUG:
                        if trust.flagged:
                            print("[TRUST_LAYER] flagged:", trust.reasons)
                        print("FINAL (after trust):", trust.text)
                    return trust.text

                return (
                    "I couldn’t fetch the exchange rate right now. "
                    "Try again in a moment, or share the currencies in the format “100 USD to EUR”."
                )

            return "I can’t run that tool right now. What would you like to do next?"

        recent_for_response = self._recent_messages(state, limit=8)
        return self.response_generator.generate(
            intent=intent,
            state=state,
            recent_messages=recent_for_response,
        )
