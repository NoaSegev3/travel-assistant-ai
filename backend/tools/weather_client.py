# Role: External tool adapter for weather. Calls Open-Meteo geocoding + forecast endpoints and returns a
# compact "daily summary" dict plus raw_daily for debugging/future richer responses.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

import requests

from backend.models.trip_profile import TripProfile


@dataclass(frozen=True)
class WeatherToolResult:
    ok: bool
    data: Dict[str, Any]
    error: Optional[str] = None


class WeatherClient:
    GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    FORECAST_HORIZON_DAYS = 16

    def get_weather(self, trip: TripProfile) -> WeatherToolResult:
        # 1) Validate destination + date window
        # 2) Geocode destination -> (lat, lon)
        # 3) Fetch forecast for requested date range
        # 4) Normalize a small summary + include raw daily for inspection

        if not trip.destination:
            return WeatherToolResult(ok=False, data={}, error="Missing destination")

        dest = trip.destination.strip()

        # Treat "no dates" as "today" for tool calls
        start = trip.start_date or date.today()
        end = trip.end_date or start

        days = (end - start).days + 1
        if days <= 0:
            return WeatherToolResult(ok=False, data={}, error="Invalid date range")

        # Key line: safety net on forecast horizon.
        if days > self.FORECAST_HORIZON_DAYS:
            return WeatherToolResult(
                ok=False,
                data={},
                error=f"Forecast range too long (Open-Meteo forecasts up to ~{self.FORECAST_HORIZON_DAYS} days).",
            )

        try:
            geo = self._geocode(dest)
            if not geo:
                return WeatherToolResult(ok=False, data={}, error=f"Could not geocode '{dest}'")

            lat = geo["latitude"]
            lon = geo["longitude"]
            name = geo["name"]
            country = geo.get("country")

            params = {
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
                "timezone": "auto",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }

            r = requests.get(self.FORECAST_URL, params=params, timeout=15)
            r.raise_for_status()
            payload = r.json()

            daily = payload.get("daily", {})
            times = daily.get("time", [])
            tmax = daily.get("temperature_2m_max", [])
            tmin = daily.get("temperature_2m_min", [])
            precip = daily.get("precipitation_sum", [])
            wind = daily.get("wind_speed_10m_max", [])

            if not times:
                return WeatherToolResult(ok=False, data={}, error="No daily forecast returned")

            # Key line: "today" is the first day of the requested range, not necessarily actual today.
            data = {
                "source": "open-meteo",
                "location": f"{name}, {country}" if country else name,
                "timeframe": f"{times[0]} (local timezone: {payload.get('timezone')})",
                "today": {
                    "temp_min_c": tmin[0] if tmin else None,
                    "temp_max_c": tmax[0] if tmax else None,
                    "precip_mm": precip[0] if precip else None,
                    "wind_max_kmh": wind[0] if wind else None,
                },
                "raw_daily": daily,
            }
            return WeatherToolResult(ok=True, data=data)

        except requests.RequestException as e:
            return WeatherToolResult(ok=False, data={}, error=f"Open-Meteo request failed: {e}")

    def _geocode(self, name: str) -> Optional[Dict[str, Any]]:
        # Role: resolve city name -> coordinates (single best result).
        params = {"name": name, "count": 1, "language": "en", "format": "json"}
        r = requests.get(self.GEO_URL, params=params, timeout=15)
        r.raise_for_status()
        payload = r.json()
        results = payload.get("results") or []
        return results[0] if results else None
