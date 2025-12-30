# Role: Lightweight "memory" for currency parsing. Combines partial info across messages (amount + pair)
# to support multi-turn currency conversion without extra LLM calls.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from backend.models.message import Message
from backend.utils.currency import (
    CurrencyQuery,
    parse_currency_amount,
    parse_currency_pair,
    parse_currency_query,
)


@dataclass(frozen=True)
class _CurrencyParts:
    amount: Optional[float] = None
    pair: Optional[tuple[str, str]] = None


def _extract_currency_parts(text: str) -> _CurrencyParts:
    # Step: prefer full parse; otherwise return partials.
    full = parse_currency_query(text)
    if full is not None:
        return _CurrencyParts(amount=float(full.amount), pair=(full.from_ccy, full.to_ccy))

    return _CurrencyParts(
        amount=parse_currency_amount(text),
        pair=parse_currency_pair(text),
    )


def combine_currency_query_from_history(
    *,
    user_message: str,
    conversation_history: Sequence[Message],
    max_lookback_user_messages: int = 10,
    allow_amount_from_history: bool = False,
) -> Optional[CurrencyQuery]:
    # 1) If current message is full query -> done
    # 2) Otherwise extract partials from current message
    # 3) Walk backwards over prior user messages to fill missing parts
    # 4) Return CurrencyQuery only if we have both amount + pair

    full_now = parse_currency_query(user_message)
    if full_now is not None:
        return full_now

    now_parts = _extract_currency_parts(user_message)
    amount_now = now_parts.amount
    pair_now = now_parts.pair

    if amount_now is None and pair_now is None:
        return None

    found_amount: Optional[float] = None
    found_pair: Optional[tuple[str, str]] = None

    lookback_count = 0

    for m in reversed(conversation_history):
        if getattr(m, "role", None) != "user":
            continue

        text = (getattr(m, "content", "") or "").strip()
        if not text:
            continue

        lookback_count += 1
        if lookback_count > max_lookback_user_messages:
            break

        prev_parts = _extract_currency_parts(text)

        if found_pair is None and prev_parts.pair is not None:
            found_pair = prev_parts.pair
        
        if allow_amount_from_history:
            if found_amount is None and prev_parts.amount is not None:
                found_amount = prev_parts.amount

        need_amount = amount_now is None
        need_pair = pair_now is None
        if (not need_amount or found_amount is not None) and (not need_pair or found_pair is not None):
            break

    amount = amount_now if amount_now is not None else found_amount
    pair = pair_now if pair_now is not None else found_pair

    if amount is None or pair is None:
        return None

    from_ccy, to_ccy = pair
    return CurrencyQuery(amount=float(amount), from_ccy=from_ccy, to_ccy=to_ccy)
