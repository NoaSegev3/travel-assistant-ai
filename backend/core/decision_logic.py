# Role: Routing brain. Given (intent + validation + state), decide the next action:
# ask a clarification, call a tool, or generate a response (and when to avoid tools).

from __future__ import annotations

import backend.config

from backend.core.validator import ValidationResult
from backend.models.decision import Action, Decision
from backend.models.intent import Intent
from backend.models.state import State
from backend.utils.currency import (
    parse_currency_amount,
    parse_currency_pair,
    parse_currency_query,
)
from backend.utils.history_extractors import combine_currency_query_from_history
from backend.utils.weather_rules import (
    is_within_open_meteo_forecast_window,
    mentions_month,
    is_seasonal_weather_question,
)

class DecisionLogic:
    @staticmethod
    def _is_numeric_amount(msg: str) -> bool:
        return parse_currency_amount(msg) is not None

    def decide(self, intent: Intent, validation: ValidationResult, user_message: str, state: State) -> Decision:
        # 1) Handle out-of-scope and generic-help onboarding
        # 2) If validation fails -> ask for missing info
        # 3) Intent-specific routing:
        #    - weather: tool only within forecast window and not month-level
        #    - currency: tool only when we have (amount + pair), otherwise clarify (sticky slots)
        # 4) Default: generate response

        if intent == Intent.OUT_OF_SCOPE:
            return Decision(
                action=Action.OUT_OF_SCOPE_RESPONSE,
                notes="User request is outside supported travel domain",
            )

        if intent == Intent.CLARIFICATION_NEEDED:
            return Decision(
                action=Action.ASK_CLARIFICATION,
                missing_info=["goal"],
                notes="User message unclear -> ask for goal",
            )

        if not validation.ok:
            return Decision(
                action=Action.ASK_CLARIFICATION,
                missing_info=validation.missing_info,
                notes="Missing or invalid information",
            )

        if intent == Intent.WEATHER_QUERY:
            # Key line: month mentions OR seasonal phrasing are treated as seasonal guidance (no daily tool numbers).
            if mentions_month(user_message) or is_seasonal_weather_question(user_message):
                return Decision(
                    action=Action.GENERATE_RESPONSE,
                    notes="Seasonal weather wording -> general seasonal answer (no tool)",
                )

            # Key line: avoid tool usage outside Open-Meteo horizon (handled safely in response prompt/trust).
            if not is_within_open_meteo_forecast_window(state.trip_profile):
                return Decision(
                    action=Action.GENERATE_RESPONSE,
                    notes="Weather query outside Open-Meteo window -> seasonal/general answer (no tool)",
                )

            return Decision(
                action=Action.CALL_TOOL,
                tool_name="weather",
                notes="Weather query within horizon -> call tool",
            )

        if intent == Intent.CURRENCY_CONVERSION:
            # Step 1: try parse from current message (one-shot).
            currency_query = parse_currency_query(user_message)

            # Step 2: if partial, try combining from history (amount in one message, pair in another).
            if currency_query is None and state.pending_missing_info in (["currency_amount"], ["currency_pair"]):
                currency_query = combine_currency_query_from_history(
                    user_message=user_message,
                    conversation_history=state.conversation_history[:-1],
                    allow_amount_from_history=(state.pending_missing_info == ["currency_amount"]),
                )

            if backend.config.DEBUG:
                print("DEBUG currency cq:", currency_query)

            # Step 3: sticky slot behavior (if we asked for amount, don't accept unrelated text).
            if state.pending_missing_info == ["currency_amount"] and currency_query is None:
                if not self._is_numeric_amount(user_message):
                    return Decision(
                        action=Action.ASK_CLARIFICATION,
                        missing_info=["currency_amount"],
                        notes="Still missing currency_amount (sticky slot)",
                    )

            # Step 4: still missing -> decide which single clarification to ask next.
            if currency_query is None:
                pair = parse_currency_pair(user_message)
                if pair is not None:
                    return Decision(
                        action=Action.ASK_CLARIFICATION,
                        missing_info=["currency_amount"],
                        notes="Currency conversion missing amount (pair detected)",
                    )

                return Decision(
                    action=Action.ASK_CLARIFICATION,
                    missing_info=["currency_pair"],
                    notes="Currency conversion missing currency pair",
                )

            return Decision(
                action=Action.CALL_TOOL,
                tool_name="currency",
                tool_payload={
                    "amount": float(currency_query.amount),
                    "from_ccy": currency_query.from_ccy,
                    "to_ccy": currency_query.to_ccy,
                },
                notes="Currency conversion -> call tool (use resolved currency_query; no re-parse in FlowController)",
            )

        if intent in {
            Intent.ITINERARY_PLANNING,
            Intent.ATTRACTIONS_RECOMMENDATIONS,
            Intent.PACKING_LIST,
        }:
            return Decision(
                action=Action.GENERATE_RESPONSE,
                notes=f"{intent.value} -> generate response",
            )

        return Decision(
            action=Action.GENERATE_RESPONSE,
            notes=f"Default fallback routing for intent={intent.value}",
        )
