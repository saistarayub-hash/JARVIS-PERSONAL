"""Web tools: search + weather + page reading + news + world clock.
No API keys required."""
from __future__ import annotations

import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from . import tool

_DEMO = False
_NEWS_CACHE = {"ts": 0.0, "items": None}

DEFAULT_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
]

_DEMO_HEADLINES = [
    "(offline demo feed) Markets steady as central banks signal patience on rates",
    "(offline demo feed) Rand firms after inflation print lands inside the band",
    "(offline demo feed) Chipmakers rally; AI capex cycle enters its third year",
    "(offline demo feed) Overnight cables: quiet sessions across Asia-Pacific",
]


def set_demo(on: bool) -> None:
    global _DEMO
    _DEMO = bool(on)

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


# ---------------------------------------------------------------- read a page
@tool("read_url", "Fetch a web page and return its readable text (title + body).",
      {"url": "string: http(s) URL to read"})
def read_url(url: str) -> dict:
    if not re.match(r"^https?://", url or ""):
        url = "https://" + (url or "")
    try:
        r = requests.get(url, timeout=9, headers={
            "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) JARVIS/1.0 "
                           "personal-assistant")})
        r.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"I couldn't reach {url} from here ({exc.__class__.__name__}). "
                           "If you're offline I'll retry later.")
    ctype = r.headers.get("content-type", "")
    body = r.text
    title = ""
    if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
        title = _clean_text(m.group(1))[:160] if m else ""
        body = re.sub(r"(?is)<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>",
                      " ", body)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
    text = _clean_text(body)
    if not text:
        raise RuntimeError(f"{url} came back empty.")
    return {"url": url, "title": title, "text": text[:2600],
            "chars": len(text)}


def _clean_text(s: str) -> str:
    s = re.sub(r"&nbsp;", " ", s or "")
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&#?\w+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- news
def _rss_items(feeds: list, limit: int = 5) -> list:
    import xml.etree.ElementTree as ET
    out = []
    for feed in feeds:
        try:
            r = requests.get(feed, timeout=7, headers={"User-Agent": "JARVIS/1.0"})
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception:  # noqa: BLE001 — next feed, or give up quietly
            continue
        for node in root.iter():
            if node.tag in ("item", "entry"):
                title = link = ""
                for child in node:
                    tag = child.tag.split("}")[-1].lower()
                    if tag == "title":
                        title = (child.text or "").strip()
                    elif tag == "link":
                        link = (child.text or child.attrib.get("href") or "").strip()
                if title:
                    out.append({"title": title, "url": link,
                                "snippet": "", "source": feed.split("/")[2]})
        if len(out) >= limit:
            break
    return out[:limit]


@tool("news", "Top world headlines right now (optionally about a topic).",
      {"topic": "string (optional): e.g. 'markets', 'technology'"})
def news(topic: str = "") -> dict:
    now = time.time()
    if not topic and _NEWS_CACHE["items"] and now - _NEWS_CACHE["ts"] < 900:
        return {"items": _NEWS_CACHE["items"], "cached": True}
    items = []
    simulated = False
    try:
        from ddgs import DDGS
        raw = DDGS().news(topic or "", max_results=5) or []
        items = [{"title": r.get("title", ""), "url": r.get("url") or r.get("link", ""),
                  "snippet": (r.get("body") or "")[:160],
                  "source": r.get("source", "")} for r in raw]
    except Exception:  # noqa: BLE001
        items = []
    if not items:
        items = _rss_items(DEFAULT_FEEDS, 5)
        if topic:
            kw = topic.lower().split()
            items = [i for i in items
                     if any(k in i["title"].lower() for k in kw)] or items[:3]
    if not items and _DEMO:
        items = [{"title": t, "url": "", "snippet": "", "source": "demo"}
                 for t in _DEMO_HEADLINES]
        simulated = True
    if not items:
        raise RuntimeError("No news provider is reachable from here right now — "
                           "I'll have headlines once you're online.")
    if not topic:
        _NEWS_CACHE.update(ts=now, items=items)
    return {"items": items[:5], "simulated": simulated}


# ---------------------------------------------------------------- world clock
_TZ = {
    "johannesburg": "Africa/Johannesburg", "pretoria": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg", "london": "Europe/London",
    "new york": "America/New_York", "los angeles": "America/Los_Angeles",
    "tokyo": "Asia/Tokyo", "singapore": "Asia/Singapore", "hong kong": "Asia/Hong_Kong",
    "dubai": "Asia/Dubai", "sydney": "Australia/Sydney", "paris": "Europe/Paris",
    "berlin": "Europe/Berlin", "amsterdam": "Europe/Amsterdam",
    "zurich": "Europe/Zurich", "frankfurt": "Europe/Berlin",
    "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "shanghai": "Asia/Shanghai",
    "beijing": "Asia/Shanghai", "seoul": "Asia/Seoul", "cairo": "Africa/Cairo",
    "lagos": "Africa/Lagos", "nairobi": "Africa/Nairobi",
    "sao paulo": "America/Sao_Paulo", "toronto": "America/Toronto",
    "chicago": "America/Chicago", "moscow": "Europe/Moscow",
    "istanbul": "Europe/Istanbul", "bangkok": "Asia/Bangkok",
}


@tool("world_time", "Current time in a city (forex sessions, calls across zones).",
      {"city": "string: e.g. 'Tokyo', 'New York'"})
def world_time(city: str) -> dict:
    key = (city or "").strip().lower()
    tzname = _TZ.get(key)
    if not tzname:
        import difflib
        close = difflib.get_close_matches(key, list(_TZ), n=1, cutoff=0.72)
        tzname = _TZ[close[0]] if close else None
    if not tzname:
        raise RuntimeError(f"I don't know the time zone for '{city}'. Try one of: "
                           + ", ".join(sorted(set(_TZ))[:12]) + " …")
    there = datetime.now(ZoneInfo(tzname))
    here = datetime.now().astimezone()
    diff_h = round((there.utcoffset().total_seconds()
                    - here.utcoffset().total_seconds()) / 3600, 1)
    rel = (f"{abs(diff_h):g}h ahead of you" if diff_h > 0 else
           f"{abs(diff_h):g}h behind you" if diff_h < 0 else "same zone as you")
    return {"city": city.strip().title(), "tz": tzname,
            "time": there.strftime("%H:%M"), "day": there.strftime("%A"),
            "relative": rel}
