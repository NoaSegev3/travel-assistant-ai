# Role: External tool adapter for currency conversion. Calls Frankfurter API and returns a structured,
# JSON-safe result dict that ResponseGenerator/TrustLayer can treat as the numeric "source of truth".

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

import backend.config as config


@dataclass(frozen=True)
class CurrencyToolResult:
    ok: bool
    data: Dict[str, Any]
    error: Optional[str] = None


class CurrencyClient:
    BASE_URL = "https://api.frankfurter.dev/v1"
    _TIMEOUT_SECONDS = 15

    def convert(self, *, amount: float, from_ccy: str, to_ccy: str) -> CurrencyToolResult:
        # 1) Validate inputs
        # 2) Call /latest with base + symbols
        # 3) Extract rate and compute conversion
        # 4) Return normalized data for downstream formatting

        if amount <= 0:
            return CurrencyToolResult(ok=False, data={}, error="Amount must be > 0")
        if not from_ccy or not to_ccy:
            return CurrencyToolResult(ok=False, data={}, error="Missing currency codes")

        from_ccy = from_ccy.upper().strip()
        to_ccy = to_ccy.upper().strip()

        try:
            params = {"base": from_ccy, "symbols": to_ccy}
            r = requests.get(f"{self.BASE_URL}/latest", params=params, timeout=self._TIMEOUT_SECONDS)
            r.raise_for_status()
            payload = r.json()

            rates = payload.get("rates") or {}
            rate = rates.get(to_ccy)
            if rate is None:
                return CurrencyToolResult(ok=False, data={}, error=f"No rate returned for {to_ccy}")

            converted = float(amount) * float(rate)

            data = {
                "source": "frankfurter",
                "date": payload.get("date"),
                "base": payload.get("base") or from_ccy,
                "to": to_ccy,
                "rate": float(rate),
                "amount": float(amount),
                "converted_amount": float(converted),
            }

            if config.DEBUG:
                print("\n--- CURRENCY TOOL ---")
                print("REQUEST:", params)
                print("RESPONSE date/base/to/rate:", data["date"], data["base"], data["to"], data["rate"])
                print("---------------------\n")

            return CurrencyToolResult(ok=True, data=data)

        except requests.RequestException as e:
            return CurrencyToolResult(ok=False, data={}, error=f"Frankfurter request failed: {e}")
        except (TypeError, ValueError) as e:
            return CurrencyToolResult(ok=False, data={}, error=f"Bad Frankfurter payload: {e}")
