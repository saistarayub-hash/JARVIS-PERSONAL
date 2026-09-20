"""Web tools: search + weather. No API keys required."""
from __future__ import annotations

import requests

from . import tool

_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST = "https://api.open-meteo.com/v1/forecast"

_WMO = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


def _ddg(query: str, max_results: int = 4) -> list:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            raise RuntimeError("Web search needs the 'ddgs' package — pip install ddgs")
    try:
        raw = DDGS().text(query, max_results=max_results) or []
    except Exception:
        raise RuntimeError("Web search is unreachable right now — looks like a "
                           "connection issue. Give it another moment and try again.")
    out = []
    for r in raw[:max_results]:
        out.append({
            "title": r.get("title") or r.get("headline") or "",
            "url": r.get("href") or r.get("url") or r.get("link") or "",
            "snippet": (r.get("body") or r.get("snippet") or "")[:200],
        })
    return out


@tool("web_search", "Search the web.",
      {"query": "string: the search text",
       "max_results": "integer (optional): default 4"})
def web_search(query: str, max_results: int = 4) -> dict:
    results = _ddg(query, max_results)
    if not results:
        raise RuntimeError(f"No results for '{query}'.")
    return {"query": query, "results": results}


@tool("weather", "Get current weather for a city.",
      {"city": "string (optional): city name — leave empty for the user's default city",
       "default_city": "string (optional, internal): injected from config"})
def weather(city: str | None = None, default_city: str | None = None) -> dict:
    city = (city or default_city or "").strip()
    if not city:
        raise RuntimeError("Tell me which city you want the weather for.")
    try:
        geo = requests.get(_GEOCODE, params={"name": city, "count": 1},
                           timeout=10).json().get("results") or []
    except (requests.RequestException, ValueError):
        raise RuntimeError("I can't reach the weather service from here right now "
                           "(connection issue). It'll work when you're online.")
    if not geo:
        raise RuntimeError(f"I couldn't find a place called '{city}'.")
    loc = geo[0]
    data = requests.get(_FORECAST, params={
        "latitude": loc["latitude"], "longitude": loc["longitude"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
    }, timeout=10).json()
    cur = data.get("current", {})
    return {
        "city": loc.get("name", city),
        "country": loc.get("country", ""),
        "temp_c": cur.get("temperature_2m"),
        "feels_c": cur.get("apparent_temperature"),
        "conditions": _WMO.get(cur.get("weather_code"), "unknown conditions"),
        "wind_kmh": cur.get("wind_speed_10m"),
    }
