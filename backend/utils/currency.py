# Role: Deterministic parsing helpers for currency conversion. Extracts (amount, from, to) from natural language
# to avoid relying on the LLM for basic string parsing (improves reliability + testability).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

_AMOUNT = r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"

_ALIASES = {
    "dollar": "USD", "dollars": "USD", "$": "USD", "usd": "USD",
    "euro": "EUR", "euros": "EUR", "eur": "EUR", "€": "EUR",
    "shekel": "ILS", "shekels": "ILS", "nis": "ILS", "ils": "ILS", "₪": "ILS",
    "pound": "GBP", "pounds": "GBP", "gbp": "GBP",
    "yen": "JPY", "jpy": "JPY",
}

_TOKEN = r"[A-Za-z$₪€]+"


@dataclass(frozen=True)
class CurrencyQuery:
    amount: float
    from_ccy: str
    to_ccy: str


def _normalize_currency_token(token: str) -> Optional[str]:
    # Role: normalize inputs like "$" / "dollars" / "usd" -> "USD".
    if not token:
        return None

    t = token.strip().lower()
    t = re.sub(r"[^a-z$₪€]", "", t)
    if not t:
        return None

    if len(t) == 3 and t.isalpha():
        return t.upper()

    return _ALIASES.get(t)


def _parse_amount_str(raw: str) -> Optional[float]:
    # Role: parse "1,200" safely and reject non-positive values.
    if not raw:
        return None
    try:
        val = float(raw.replace(",", ""))
        return val if val > 0 else None
    except ValueError:
        return None


def parse_currency_amount(text: str) -> Optional[float]:
    # Role: extract an amount-only message (e.g., "100", "1,200").
    if not text:
        return None

    t = text.strip()
    low = t.lower()

    if re.search(r"\bday\s+\d+\b", low) and not re.search(r"[$€₪]|usd|eur|ils|gbp|jpy|dollar|euro|shekel|pound|yen", low):
        return None

    m = re.search(rf"\b{_AMOUNT}\b", t)
    if not m:
        return None
    return _parse_amount_str(m.group(1))


def parse_currency_pair(text: str) -> Optional[Tuple[str, str]]:
    """
    Parses pair-only patterns:
      - "usd to eur"
      - "EUR/GBP"
      - "usd-eur"
      - "$ to €"
      - "$/€" , "$-€"
    """
    if not text:
        return None
    t = text.strip()

    m = re.search(rf"({_TOKEN})\s*(?:to|in)\s*({_TOKEN})", t, flags=re.IGNORECASE)
    if m:
        a = _normalize_currency_token(m.group(1))
        b = _normalize_currency_token(m.group(2))
        if a and b and a != b:
            return a, b

    # Allow token pairs with separators, including symbols.
    m = re.search(rf"({_TOKEN})\s*[/\-]\s*({_TOKEN})", t, flags=re.IGNORECASE)
    if m:
        a = _normalize_currency_token(m.group(1))
        b = _normalize_currency_token(m.group(2))
        if a and b and a != b:
            return a, b

    return None


def parse_currency_query(text: str) -> Optional[CurrencyQuery]:
    """
    Parses full patterns like:
      - "convert 100 usd to eur"
      - "1,200 $ to €"
      - "USD to EUR 100"
    """
    if not text:
        return None

    t = text.strip()

    m = re.search(rf"\b{_AMOUNT}\b\s*({_TOKEN})\s*(?:to|in)\s*({_TOKEN})", t, flags=re.IGNORECASE)
    if m:
        amount = _parse_amount_str(m.group(1))
        from_ccy = _normalize_currency_token(m.group(2))
        to_ccy = _normalize_currency_token(m.group(3))
        if amount is not None and from_ccy and to_ccy and from_ccy != to_ccy:
            return CurrencyQuery(amount=amount, from_ccy=from_ccy, to_ccy=to_ccy)

    m = re.search(rf"({_TOKEN})\s*to\s*({_TOKEN})\s*\b{_AMOUNT}\b", t, flags=re.IGNORECASE)
    if m:
        from_ccy = _normalize_currency_token(m.group(1))
        to_ccy = _normalize_currency_token(m.group(2))
        amount = _parse_amount_str(m.group(3))
        if amount is not None and from_ccy and to_ccy and from_ccy != to_ccy:
            return CurrencyQuery(amount=amount, from_ccy=from_ccy, to_ccy=to_ccy)

    return None
