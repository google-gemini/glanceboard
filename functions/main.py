# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Glanceboard — Firebase Cloud Functions (Multi-User, Multi-Device).

Serverless image generation pipeline with subscription tiers:
  - Free (self-hosted): User runs their own Firebase project
  - Hosted ($3/mo): User provides their own API key, we host the app
  - Plus ($9/mo): Fully managed, server-side API key
  - Additional devices: $10/mo per extra display (paid tiers only)

Display hardware: Waveshare ESP32-S3 PhotoPainter (all-in-one e-ink frame).
Legacy Raspberry Pi + separate display is still supported but no longer primary.

Pipeline (per device):
  1. Fetch calendar events via Google Calendar API (OAuth refresh token)
  2. Fetch weather via Open-Meteo API
  3. Load character config from user's Firestore subcollection
  4. Build an adventure prompt (with weather context)
  5. Generate image via appropriate API key (user's or server's)
  6. Resize & dither for the 6-color e-ink display
  7. Save to device's Firebase Storage path (publicly accessible for the Pi)

Data model:
  User-level (shared across devices):
    Firestore: users/{uid}/settings/account  (API key, timezone, location)
    Firestore: users/{uid}/settings/subscription
    Firestore: users/{uid}/settings/google_tokens
    Firestore: users/{uid}/characters/{id}

  Device-level (per display):
    Firestore: users/{uid}/devices/{deviceId}  (name, aesthetic, model, calendar)
    Firestore: users/{uid}/devices/{deviceId}/prompt/prompt
    Firestore: users/{uid}/devices/{deviceId}/status/status
    Storage:   users/{uid}/devices/{deviceId}/display/*
    Storage:   users/{uid}/devices/{deviceId}/archive/*

  Legacy (pre-migration, still supported with fallback reads):
    Firestore: users/{uid}/settings/config
    Firestore: users/{uid}/settings/prompt
    Storage:   users/{uid}/display/*
"""
import base64
import hashlib
import io
import json
import os
import random
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import requests

from firebase_admin import auth as admin_auth, firestore, initialize_app, storage
from firebase_functions import https_fn, options, scheduler_fn
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from PIL import Image

# ─── Firebase Init ──────────────────────────────────────────────

initialize_app()

# ─── Constants ──────────────────────────────────────────────────

DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480
DEFAULT_TIMEZONE = "Australia/Sydney"

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# E-Ink Spectra 6 color palette (RGB)
EINK_PALETTE = np.array([
    [0,   0,   0],      # Black
    [255, 255, 255],    # White
    [200, 30,  30],     # Red
    [0,   128, 0],      # Green
    [0,   50,  180],    # Blue
    [230, 200, 0],      # Yellow
], dtype=np.float64)

BACKUP_QUOTES = [
    "Be kind to everyone you meet today!",
    "Today is a great day to learn something new!",
    "You are brave and wonderful!",
    "What adventure will you find today?",
    "Read a book, change the world! 📚",
    "Smile at someone today — it's contagious!",
    "Try something you've never done before!",
    "Be a good friend today!",
    "The world is better because you're in it!",
    "Every day is a chance to be awesome!",
    "Kindness is a superpower — use it!",
    "Dream big, start small, act now!",
]

# Weather condition code mapping (WMO codes from Open-Meteo)
WMO_WEATHER_CODES = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Foggy", "🌫️"),
    48: ("Icy fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Drizzle", "🌦️"),
    55: ("Heavy drizzle", "🌧️"),
    56: ("Freezing drizzle", "🌧️"),
    57: ("Heavy freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"),
    63: ("Rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"),
    67: ("Heavy freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"),
    73: ("Snow", "🌨️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"),
    80: ("Light showers", "🌦️"),
    81: ("Showers", "🌧️"),
    82: ("Heavy showers", "⛈️"),
    85: ("Light snow showers", "🌨️"),
    86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm with hail", "⛈️"),
    99: ("Heavy thunderstorm with hail", "⛈️"),
}

DEFAULT_PROMPT_TEMPLATE = """Create a children's illustrated daily planner in pen-and-ink style on warm parchment/cream paper background with crosshatching. The output image MUST be EXACTLY 800×480 pixels — a wide landscape format (5:3 aspect ratio). The image MUST be significantly wider than it is tall.

CRITICAL FRAMING: Leave generous margins — at least 40 pixels of padding on ALL sides (top, bottom, left, right). Do NOT place any text, characters, or important elements near the edges. Everything must be well within the safe zone to avoid clipping on the e-ink display.

LAYOUT — FULL-WIDTH SCENE WITH OVERLAID TEXT:

The ENTIRE image is a single charming pen-and-ink illustration. {{SCENE_DESCRIPTION}} The scene fills the whole canvas.

TOP: A ribbon banner reads: '{{BANNER_TEXT}}' in bold hand-drawn block letters. Keep it well below the top edge.

{{TEXT_LAYOUT}}
{{EVENT_LIST}}

RIGHT SIDE ({{RIGHT_WIDTH}}) — MAIN SCENE:
This is where the main action and characters are. The illustration flows naturally from the left side but the main focal point (characters, action) is on the right so it doesn't compete with the text.
{{CHARACTERS}}

BOTTOM LEFT CORNER — WEATHER:
{{WEATHER}}

{{COUNTDOWN}}

STYLE RULES: Pen-and-ink illustration, warm parchment background, hand-drawn crosshatching, charming and whimsical.
Use ONLY these colors: black ink, cream/white paper, plus limited accents of red, green, blue, and yellow.
Kid-friendly, warm, joyful. No scary elements.
The text on the left must be CLEARLY READABLE — high contrast against the background.
Remember: 800×480 pixels, wide landscape, generous margins on all sides.

{{REGION_GUIDANCE}}"""


FASHION_PROMPT_TEMPLATE = """Create a stylish fashion-illustration daily planner in high-end editorial sketch style. The output image MUST be EXACTLY 800×480 pixels — a wide landscape format (5:3 aspect ratio). The image MUST be significantly wider than it is tall.

CRITICAL FRAMING: Leave generous margins — at least 40 pixels of padding on ALL sides (top, bottom, left, right). Do NOT place any text, characters, or important elements near the edges. Everything must be well within the safe zone to avoid clipping on the e-ink display.

LAYOUT — FULL-WIDTH SCENE WITH OVERLAID TEXT:

The ENTIRE image is a single elegant fashion illustration. {{SCENE_DESCRIPTION}} Think high-fashion editorial meets daily planner — loose, confident brush strokes and fine ink lines on a clean off-white or warm cream background.

TOP: An elegant hand-lettered header reads: '{{BANNER_TEXT}}' in stylish calligraphic or modern serif letters. Keep it well below the top edge.

{{TEXT_LAYOUT}}
{{EVENT_LIST}}

RIGHT SIDE ({{RIGHT_WIDTH}}) — MAIN SCENE:
This is the focal point. Show the characters in a scene related to the day's events, rendered in fashion illustration style — elongated proportions, confident ink lines, watercolor washes in muted tones, editorial poses. Think Garance Doré, Inslee Haynes, or Jason Brooks style illustration.
{{CHARACTERS}}

BOTTOM LEFT CORNER — WEATHER:
{{WEATHER}}

{{COUNTDOWN}}

STYLE RULES: Fashion illustration / editorial sketch style. Confident loose ink lines, watercolor washes, muted sophisticated color palette.
Use ONLY these colors: black ink, cream/white paper, plus limited accents of muted red, sage green, dusty blue, and ochre yellow.
Sophisticated, modern, editorial. Loose and artistic, not tight or cartoonish.
The text on the left must be CLEARLY READABLE — elegant but legible.
Remember: 800×480 pixels, wide landscape, generous margins on all sides.

{{REGION_GUIDANCE}}"""


# ─── Google OAuth Helpers ───────────────────────────────────────

# ─── Calendar Fetching (iCal) ───────────────────────────────────

def _fetch_events_ical(ical_url, range_start, range_end, timezone):
    """Fetch events from iCal feed (fallback if no Google OAuth)."""
    from icalendar import Calendar as ICalendar
    import recurring_ical_events

    try:
        response = requests.get(ical_url, timeout=15)
        if response.status_code != 200:
            return []

        cal = ICalendar.from_ical(response.content)
        tz = ZoneInfo(timezone)
        events_in_range = recurring_ical_events.of(cal).between(range_start, range_end)

        events = []
        for component in events_in_range:
            summary = str(component.get("summary", "Untitled event"))
            dtstart = component.get("dtstart")
            dtend = component.get("dtend")
            start_str = ""
            start_iso = None
            end_iso = None

            if dtstart:
                dt = dtstart.dt
                if hasattr(dt, "hour"):
                    if dt.tzinfo:
                        dt = dt.astimezone(tz)
                    start_str = dt.strftime("%H:%M")
                    start_iso = dt.isoformat()
                else:
                    start_str = "All day"

            if dtend:
                dt_end = dtend.dt
                if hasattr(dt_end, "hour"):
                    if dt_end.tzinfo:
                        dt_end = dt_end.astimezone(tz)
                    end_iso = dt_end.isoformat()

            location = str(component.get("location", "") or "")
            events.append({
                "summary": summary,
                "start": start_str,
                "start_iso": start_iso,
                "end_time": end_iso,
                "location": location,
            })

        events.sort(key=lambda e: e.get("start", ""))
        return events
    except Exception as e:
        print(f"iCal fetch error: {e}")
        return []


def fetch_events_ical(ical_url, timezone=DEFAULT_TIMEZONE, target_date=None):
    """Fetch events from iCal feed for a specific date."""
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    if target_date is None:
        target_date = now.date()
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
    end = start + timedelta(days=1)
    return _fetch_events_ical(ical_url, start, end, timezone)


# ─── Weather Fetching ───────────────────────────────────────────

def fetch_weather(latitude, longitude, temp_unit="celsius"):
    """
    Fetch current weather from Open-Meteo API (free, no API key needed).

    Returns a dict with: temp, temp_unit_symbol, condition, condition_emoji,
    high, low, clothing_hint.
    """
    try:
        temp_param = "celsius" if temp_unit == "celsius" else "fahrenheit"
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={latitude}&longitude={longitude}"
            f"&current=temperature_2m,weather_code"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&temperature_unit={temp_param}"
            f"&forecast_days=1"
            f"&timezone=auto"
        )

        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"Weather API error: HTTP {response.status_code}")
            return None

        data = response.json()
        current = data.get("current", {})
        daily = data.get("daily", {})

        current_temp = current.get("temperature_2m")
        weather_code = current.get("weather_code", 0)
        condition, emoji = WMO_WEATHER_CODES.get(weather_code, ("Unknown", "🌡️"))

        high = daily.get("temperature_2m_max", [None])[0]
        low = daily.get("temperature_2m_min", [None])[0]

        unit_symbol = "°C" if temp_unit == "celsius" else "°F"

        # Use the day's HIGH temperature for the main display and clothing.
        # Early-morning current temps are misleadingly cold and cause the AI
        # to overdress the characters. The high is what matters for the day.
        display_temp = high if high is not None else current_temp

        # Generate clothing hint based on the day's HIGH temperature (in celsius)
        if display_temp is not None:
            temp_c = display_temp if temp_unit == "celsius" else (display_temp - 32) * 5 / 9
        else:
            temp_c = None

        if temp_c is None:
            clothing_hint = ""
        elif temp_c >= 30:
            clothing_hint = "light summer clothes (shorts, t-shirts, sun hats)"
        elif temp_c >= 22:
            clothing_hint = "casual warm-weather clothes (t-shirts, light pants)"
        elif temp_c >= 15:
            clothing_hint = "layers or light jumpers"
        elif temp_c >= 8:
            clothing_hint = "warm clothes (jackets, long pants)"
        elif temp_c >= 0:
            clothing_hint = "heavy winter clothes (coats, scarves, beanies)"
        else:
            clothing_hint = "very heavy winter gear (thick coats, gloves, boots)"

        # Add rain gear if wet
        if weather_code in (51, 53, 55, 61, 63, 65, 80, 81, 82):
            clothing_hint += ", and rain gear (umbrellas, rain jackets)"
        elif weather_code in (71, 73, 75, 85, 86):
            clothing_hint += ", and snow-appropriate gear"

        return {
            "temp": display_temp,  # Day's high (used for display + clothing)
            "current_temp": current_temp,  # Actual current reading
            "unit_symbol": unit_symbol,
            "condition": condition,
            "emoji": emoji,
            "high": high,
            "low": low,
            "clothing_hint": clothing_hint,
        }

    except Exception as e:
        print(f"Weather fetch error: {e}")
        return None


def _reverse_geocode_location(latitude, longitude):
    """Get a rough location name from lat/long using Open-Meteo's geocoding.

    Returns a string like 'Sydney, Australia' or 'London, UK'.
    Falls back gracefully to empty string if the API fails.
    """
    try:
        resp = requests.get(
            f"https://nominatim.openstreetmap.org/reverse"
            f"?lat={latitude}&lon={longitude}&format=json&zoom=10",
            headers={"User-Agent": "Glanceboard/1.0"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            address = data.get("address", {})
            city = address.get("city") or address.get("town") or address.get("suburb", "")
            country = address.get("country", "")
            if city and country:
                return f"{city}, {country}"
            elif country:
                return country
    except Exception as e:
        print(f"  Reverse geocode failed: {e}")
    return ""


def describe_scene_weather_via_gemini(weather, season, timezone, api_key,
                                       api_provider="google", location_name="",
                                       events=None):
    """Use Gemini Flash Lite to generate a realistic, location-aware scene
    description based on actual weather conditions.

    Instead of just saying 'winter scene' (which causes the image model to draw
    snow everywhere), this produces something like 'a cool, overcast Sydney
    winter morning with green trees and grey skies — characters wear light
    jackets'.

    Returns a 1-2 sentence scene description string, or a sensible fallback.
    """
    if not api_key or not weather:
        return f"The setting is a {season} day."

    temp = weather.get("temp")
    unit = weather.get("unit_symbol", "°C")
    condition = weather.get("condition", "").lower()
    clothing = weather.get("clothing_hint", "")

    # Build event context so the scene relates to the day's activities
    event_context = ""
    if events:
        summaries = [e.get("humanized") or e.get("summary", "") for e in events[:5]]
        if summaries:
            event_context = f"\nToday's activities include: {', '.join(summaries)}."

    location_ctx = f" in {location_name}" if location_name else ""

    prompt = f"""You are writing a scene description for a children's illustrated daily planner.

Describe the outdoor setting for an illustration given these REAL weather conditions:
- Temperature: {temp}{unit}
- Condition: {condition}
- Season: {season}
- Location: {location_name or 'unspecified'}{event_context}

Rules:
- Be specific and REALISTIC for the actual location and temperature
- Do NOT mention snow, frost, or ice unless the temperature is below 2°C
- Do NOT include animals that don't exist in the location's region (e.g. no badgers, foxes, deer, or raccoons in Australia; no kangaroos in Europe)
- Focus on the sky, light, trees, atmosphere, and what people would wear
- If the location is known, use regionally appropriate vegetation (e.g. eucalyptus and gum trees for Australia, not oak and pine)
- Keep it to 1-2 SHORT sentences describing just the atmosphere and setting
- Do NOT mention specific people or characters

Example outputs:
- "A mild, cool winter morning{location_ctx} with grey overcast skies and green trees. The light is soft and gentle."
- "A bright, warm summer afternoon with clear blue skies and dappled sunlight through leafy trees."
- "A crisp autumn day with golden leaves and a gentle breeze under partly cloudy skies."

Now write the scene description:"""

    try:
        if api_provider == "openrouter":
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "google/gemini-3.1-flash-lite-001",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
            }
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers, json=payload, timeout=15,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 150, "temperature": 0.7},
            }
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            result = resp.json()
            text = result["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Clean up — remove quotes if Gemini wraps the response
        text = text.strip('"').strip("'")
        print(f"  🌤️ Scene description: {text[:100]}...")
        return text

    except Exception as e:
        print(f"  ⚠️ Scene description failed ({e}), using fallback")
        return f"The setting is a {season} day, {temp}{unit} and {condition}."


def scan_important_events_via_gemini(events_14_days, api_key, api_provider="google",
                                      characters=None):
    """Use Gemini Flash Lite to identify important upcoming events worth
    counting down to — birthdays, trips, holidays, celebrations.

    Args:
        events_14_days: List of event dicts for the next 14 days.
        api_key: API key for Gemini.
        api_provider: 'google' or 'openrouter'.
        characters: Optional character list for name context.

    Returns:
        List of dicts: [{"event": str, "date": str, "type": str, "days_away": int}]
    """
    if not events_14_days or not api_key:
        return []

    # Build people context
    people_context = ""
    if characters:
        names = [c.get("name", "") for c in characters if c.get("name")]
        if names:
            people_context = f"\nFamily members: {', '.join(names)}.\n"

    # Build the event list
    event_lines = []
    for ev in events_14_days:
        date_str = ev.get("date", ev.get("start", ""))
        summary = ev.get("summary", "")
        days = ev.get("days_away", "?")
        event_lines.append(f"- [{date_str}] (in {days} days) {summary}")

    events_text = "\n".join(event_lines)

    prompt = f"""Analyze this list of calendar events for the next 14 days and identify any IMPORTANT or SPECIAL events that a family would want to count down to.
{people_context}
IMPORTANT event types to look for:
- 🎂 Birthdays (any family member or friend)
- ✈️ Trips, holidays, or vacations
- 🏖️ School holidays or breaks
- 🎉 Celebrations, parties, or special occasions
- 👥 Visitors or guests coming
- 🎪 Concerts, shows, or special outings

Do NOT include:
- Routine events (swimming lessons, dentist, school, work meetings)
- Regular weekly activities
- Reminders for items (library bags, homework)

Calendar events:
{events_text}

Respond with ONLY a JSON array of important events. If none found, respond with []
Format: [{{"event": "Dad's birthday", "date": "2026-07-10", "type": "birthday", "days_away": 7}}]"""

    try:
        if api_provider == "openrouter":
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "google/gemini-3.1-flash-lite-001",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
            }
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers, json=payload, timeout=20,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 500, "temperature": 0.3},
            }
            resp = requests.post(url, json=payload, timeout=20)
            resp.raise_for_status()
            result = resp.json()
            text = result["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Parse JSON — handle markdown code blocks
        import json as json_module
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"```(?:json)?\s*", "", text)
            text = text.rstrip("`").strip()

        important = json_module.loads(text)
        print(f"  📅 Found {len(important)} important events via Gemini scan")
        return important if isinstance(important, list) else []

    except Exception as e:
        print(f"  ⚠️ Important events scan failed: {e}")
        return []


# ─── Prompt Building ────────────────────────────────────────────

def get_season(month):
    """Get the Australian season for a given month."""
    seasons = {
        12: "summer", 1: "summer", 2: "summer",
        3: "autumn", 4: "autumn", 5: "autumn",
        6: "winter", 7: "winter", 8: "winter",
        9: "spring", 10: "spring", 11: "spring",
    }
    return seasons.get(month, "spring")


def _filter_remaining_events(events, timezone, exclude_all_day=False):
    """Filter events to only those that haven't started yet.

    Once an event has started, it's already happening — no need to
    "prepare" for it.  This means the display transitions to tomorrow
    as soon as all remaining events have begun, rather than waiting
    for them to finish.

    If exclude_all_day is True, all-day events are also removed (used
    in the afternoon when they're no longer useful to display).
    """
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    remaining = []
    for ev in events:
        start_iso = ev.get("start_iso")
        if start_iso is None:
            # All-day events or events without start time
            if not exclude_all_day:
                remaining.append(ev)
        else:
            try:
                start_dt = datetime.fromisoformat(start_iso)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=tz)
                if start_dt > now:
                    remaining.append(ev)
            except (ValueError, TypeError):
                remaining.append(ev)  # Include if we can't parse
    return remaining


def _determine_mode_and_events(hour, today_events, tomorrow_events, timezone):
    """Determine the display mode, banner text, and filtered events.

    Logic:
    - Before 10am: Full day view — show ALL of today's events
    - 10am-3pm: Show remaining events (including all-day). If none left, switch to tomorrow
    - 3pm+: Show remaining timed events only (all-day events are dropped).
            If none left, switch to tomorrow

    Returns:
        (mode, banner_text, events) tuple
    """
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    day_name = now.strftime("%A")
    tomorrow_name = (now + timedelta(days=1)).strftime("%A")

    if hour < 10:
        # Early morning — show the full day ahead
        return "today", f"THIS {day_name.upper()}'S ADVENTURE!", today_events

    # After 3pm, drop all-day events — they've served their purpose
    exclude_all_day = (hour >= 15)
    remaining = _filter_remaining_events(today_events, timezone, exclude_all_day=exclude_all_day)

    if remaining:
        # There are still events today
        if hour < 15:
            banner = "COMING UP TODAY!"
        elif hour < 19:
            banner = "THIS EVENING!"
        else:
            banner = "TONIGHT!"
        return "today", banner, remaining
    else:
        # All today's events are done — switch to tomorrow
        return "tomorrow", f"TOMORROW'S ADVENTURE ({tomorrow_name.upper()})!", tomorrow_events


def _compute_generation_hash(mode, banner_text, events, weather_summary="", weather=None):
    """Compute a hash of the generation inputs to detect changes.

    Only regenerate when this hash differs from the last generation.
    Weather is coarsened to prevent minor fluctuations triggering regeneration —
    temperature is rounded to the nearest 5 degrees and condition is bucketed.
    """
    event_keys = []
    for ev in (events or []):
        event_keys.append(f"{ev.get('start', '')}|{ev.get('summary', '')}")
    event_keys.sort()

    # Coarsen weather so minor changes (17°C → 18°C, "clear" → "few clouds") don't trigger regen
    coarse_weather = ""
    if weather:
        temp = weather.get("temp", 0)
        rounded_temp = round(temp / 5) * 5  # Round to nearest 5°
        condition = weather.get("condition", "").lower()
        # Bucket conditions into broad categories
        if any(w in condition for w in ["rain", "drizzle", "shower"]):
            bucket = "rain"
        elif any(w in condition for w in ["storm", "thunder"]):
            bucket = "storm"
        elif any(w in condition for w in ["snow", "sleet", "ice"]):
            bucket = "snow"
        elif any(w in condition for w in ["cloud", "overcast"]):
            bucket = "cloudy"
        elif any(w in condition for w in ["fog", "mist", "haze"]):
            bucket = "fog"
        else:
            bucket = "clear"
        coarse_weather = f"{rounded_temp}|{bucket}"

    hash_input = json.dumps({
        "mode": mode,
        "banner": banner_text,
        "events": event_keys,
        "weather": coarse_weather,
    }, sort_keys=True)

    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


def humanize_events_via_gemini(events, api_key, api_provider="google", characters=None):
    """Use Gemini to rewrite raw calendar events into friendly, human language.

    Transforms entries like "9:00am Tavi Library Bag" into
    "📚 Tavi — remember Library bag!" with emojis and warmth.

    Args:
        events: List of event dicts with 'summary', 'start', 'end_time', 'location'.
        api_key: The user's API key (Google AI Studio or OpenRouter).
        api_provider: 'google' or 'openrouter'.
        characters: Optional list of character dicts to help Gemini recognize names.

    Returns:
        List of event dicts with an added 'humanized' key containing the
        friendly version. Falls back to original summary if anything fails.
    """
    if not events or not api_key:
        return events

    # Build context about known people so Gemini can personalise
    people_context = ""
    if characters:
        names = [c.get("name", "") for c in characters if c.get("name")]
        if names:
            people_context = f"\nThe family members / people you know about: {', '.join(names)}.\n"

    # Build the list of events for Gemini to rewrite
    event_lines = []
    for i, ev in enumerate(events):
        time_str = ev.get("start", "")
        summary = ev.get("summary", "")
        location = ev.get("location", "")
        line = f"{i+1}. [{time_str}] {summary}"
        if location:
            line += f" (at {location})"
        event_lines.append(line)

    events_text = "\n".join(event_lines)

    gemini_prompt = f"""You are a friendly family assistant writing for an e-ink daily display.

Rewrite each calendar event below into a SHORT, warm, human-friendly version.
Rules:
- Keep it brief — max ~8 words per event
- Add a relevant emoji at the start of each line
- If an event is a reminder (e.g. "Library Bag", "Homework Due"), phrase it as a friendly nudge like "remember your library bag!" or "homework is due today!"
- If a person's name is in the event, address or mention them directly (e.g. "Tavi — swimming today!")
- Keep the TIME as-is but convert 24h to 12h format with am/pm
- If it's an "All day" event, don't include a time
- Don't add quotation marks around the output
- Each line should start with the number, then the rewritten text
{people_context}
Calendar events to rewrite:
{events_text}

Respond with ONLY the numbered list, one per line. Example format:
1. 📚 9am — Tavi, remember library bag!
2. 🏊 3:30pm — Tavi has swimming
3. 🎂 All day — Grandma's birthday!"""

    try:
        if api_provider == "openrouter":
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "google/gemini-3.1-flash-lite-001",
                "messages": [{"role": "user", "content": gemini_prompt}],
                "max_tokens": 500,
            }
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers, json=payload, timeout=30,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
        else:
            # Google AI Studio
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": gemini_prompt}]}],
                "generationConfig": {"maxOutputTokens": 500, "temperature": 0.7},
            }
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            text = result["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Parse the numbered responses back into the events
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in lines:
            # Match lines like "1. 📚 9am — Tavi, remember library bag!"
            # or "1) 📚 9am — ..." 
            match = re.match(r"^(\d+)[.)\s]+(.+)$", line)
            if match:
                idx = int(match.group(1)) - 1
                humanized = match.group(2).strip()
                if 0 <= idx < len(events):
                    events[idx]["humanized"] = humanized

        print(f"  ✨ Humanized {sum(1 for e in events if 'humanized' in e)}/{len(events)} events via Gemini")

    except Exception as e:
        print(f"  ⚠️  Event humanization failed (falling back to raw): {e}")

    return events


def get_upcoming_countdowns(characters, today, days_ahead=14):
    """Compute upcoming countdowns for character birthdays and major holidays.

    Returns a sorted list of dicts: [{name, days_away, type}, ...]
    Only includes items within `days_ahead` days.
    """
    countdowns = []

    # ─── Character birthdays ─────────────────────────────────────
    for char in characters:
        bday_str = char.get("birthday")
        if not bday_str:
            continue
        try:
            bday = datetime.strptime(bday_str, "%Y-%m-%d").date()
            # This year's birthday
            this_year_bday = bday.replace(year=today.year)
            if this_year_bday < today:
                this_year_bday = bday.replace(year=today.year + 1)
            days = (this_year_bday - today).days
            if 0 <= days <= days_ahead:
                countdowns.append({
                    "name": f"{char.get('name', 'Someone')}'s birthday",
                    "days_away": days,
                    "type": "birthday",
                })
        except (ValueError, TypeError):
            continue

    # ─── Major holidays (fixed dates) ────────────────────────────
    holidays = [
        (12, 25, "Christmas"),
        (1, 1, "New Year's Day"),
        (2, 14, "Valentine's Day"),
        (10, 31, "Halloween"),
    ]
    for month, day, name in holidays:
        try:
            this_year = date(today.year, month, day)
            if this_year < today:
                this_year = date(today.year + 1, month, day)
            days = (this_year - today).days
            if 0 <= days <= days_ahead:
                countdowns.append({
                    "name": name,
                    "days_away": days,
                    "type": "holiday",
                })
        except ValueError:
            continue

    # ─── Easter (computed) ───────────────────────────────────────
    for yr in [today.year, today.year + 1]:
        easter = _compute_easter(yr)
        days = (easter - today).days
        if 0 <= days <= days_ahead:
            countdowns.append({
                "name": "Easter",
                "days_away": days,
                "type": "holiday",
            })
            break

    countdowns.sort(key=lambda x: x["days_away"])
    return countdowns


def _compute_easter(year):
    """Anonymous Gregorian algorithm for Easter date."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def build_prompt(events, characters, prompt_template, timezone=DEFAULT_TIMEZONE,
                 mode="today", banner_text=None, characters_enabled=True,
                 weather=None, birthdays=None, aesthetic="whimsical",
                 scene_description="", important_events=None,
                 location_name=""):
    """
    Build the image generation prompt from events + characters + weather + countdowns.
    """
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    raw_season = get_season(now.month)

    # Use Gemini-generated scene description if available, otherwise fall back
    if not scene_description:
        if weather and weather.get("temp") is not None:
            temp = weather["temp"]
            unit = weather.get("unit_symbol", "°C")
            condition = weather.get("condition", "").lower()
            scene_description = f"The setting is a {raw_season} day ({temp}{unit}, {condition})."
        else:
            scene_description = f"The setting is a {raw_season} day."

    # Build region-aware negative guidance
    region_guidance_parts = [
        "IMPORTANT REALISM RULES:",
        "- Do NOT include snow, frost, ice, or winter precipitation unless the temperature is below 2°C.",
        "- Do NOT include animals that don't exist in the local region.",
    ]
    if location_name:
        lower_loc = location_name.lower()
        if "australia" in lower_loc:
            region_guidance_parts.append(
                "- This is set in Australia. Do NOT draw badgers, foxes, deer, raccoons, "
                "squirrels, robins, or other Northern Hemisphere animals. "
                "Do NOT draw stereotypical Australian animals (kangaroos, koalas) "
                "unless specifically requested. Use native birds (magpies, lorikeets, kookaburras) "
                "sparingly and only if they fit the scene naturally. "
                "Use Australian vegetation (eucalyptus, gum trees, bottlebrush) not oak, maple, or pine."
            )
        elif any(x in lower_loc for x in ["united kingdom", "england", "scotland", "wales"]):
            region_guidance_parts.append(
                "- This is set in the UK. Use regionally appropriate flora and fauna."
            )
        # Add more regions as needed
    region_guidance = "\n".join(region_guidance_parts)

    # Always compute day_name (used in prompt template substitution)
    if mode == "tomorrow":
        target_date = now + timedelta(days=1)
        day_name = target_date.strftime("%A")
    else:
        day_name = now.strftime("%A")

    # Use provided banner_text, or fall back to default
    if not banner_text:
        if mode == "tomorrow":
            banner_text = f"WHAT'S ON TOMORROW ({day_name.upper()})"
        else:
            banner_text = f"THIS {day_name.upper()}'S ADVENTURE!"

    # Build event list — prefer Gemini-humanized text when available
    event_list_items = []
    if events:
        for ev in events:
            if ev.get("humanized"):
                # Gemini already formatted this with emoji, time, and friendly text
                item = f"• {ev['humanized']}"
            else:
                # Fallback: format the raw event as before
                time_str = ev.get("start", "")
                if time_str and ":" in str(time_str):
                    try:
                        h, m = str(time_str).split(":")[:2]
                        hour = int(h)
                        ampm = "AM" if hour < 12 else "PM"
                        h12 = hour if hour <= 12 else hour - 12
                        if h12 == 0:
                            h12 = 12
                        time_str = f"{h12}:{m} {ampm}"
                    except (ValueError, IndexError):
                        pass
                item = f"• {time_str} — {ev['summary']}"
                if ev.get("location"):
                    item += f" ({ev['location']})"
            event_list_items.append(item)
    else:
        # Weather-only mode (no calendar) — show daily inspiration instead
        inspiration_messages = [
            "Take a moment to enjoy the weather today! 🌤️",
            "A great day for something new! ✨",
            "Make someone smile today! 😊",
            "Enjoy the little things today! 💛",
            "A perfect day to explore! 🌿",
            "Be curious, be kind! 🌈",
            "Fresh air and good vibes today! 🍃",
            "Today is full of possibilities! 🚀",
        ]
        event_list_items.append(f"• {random.choice(inspiration_messages)}")

    event_count = len(event_list_items)
    event_list_str = "\n".join(event_list_items)

    # ─── Countdowns (birthdays + holidays) ───────────────────────
    today = now.date()
    countdowns = get_upcoming_countdowns(characters, today)

    # Also include Google Calendar birthdays if provided
    if birthdays:
        for bday in birthdays:
            days = bday.get("days_away", 999)
            name = bday.get("name", "Someone")
            if days <= 14 and not any(c["name"].startswith(name) for c in countdowns):
                countdowns.append({
                    "name": f"{name}'s birthday",
                    "days_away": days,
                    "type": "birthday",
                })
        countdowns.sort(key=lambda x: x["days_away"])

    # Also include Gemini-identified important events (trips, celebrations, etc.)
    if important_events:
        for ie in important_events:
            event_name = ie.get("event", "")
            days = ie.get("days_away", 999)
            event_type = ie.get("type", "event")
            # Avoid duplicates
            if days <= 14 and not any(event_name.lower() in c["name"].lower() for c in countdowns):
                countdowns.append({
                    "name": event_name,
                    "days_away": days,
                    "type": event_type,
                })
        countdowns.sort(key=lambda x: x["days_away"])

    # Build countdown text for the prompt
    countdown_text = ""
    countdown_items = []
    for cd in countdowns[:3]:  # Max 3 countdowns
        # Choose emoji based on event type
        type_emoji = {
            "birthday": "🎂",
            "holiday": "🎉",
            "trip": "✈️",
            "celebration": "🎉",
            "event": "⭐",
        }.get(cd.get("type", "event"), "📅")

        if cd["days_away"] == 0:
            if cd["type"] == "birthday":
                countdown_items.append(f"🎂 It's {cd['name']} TODAY!")
            else:
                countdown_items.append(f"{type_emoji} {cd['name']} is TODAY!")
        elif cd["days_away"] == 1:
            countdown_items.append(f"⏰ {cd['name']} is TOMORROW!")
        else:
            countdown_items.append(f"{type_emoji} {cd['days_away']} days until {cd['name']}!")

    if countdown_items:
        countdown_text = (
            "BOTTOM RIGHT CORNER — COUNTDOWN:\n"
            "In the BOTTOM RIGHT corner, draw a small countdown note in hand-drawn style. "
            "It should read:\n" + "\n".join(countdown_items)
        )
    else:
        # Explicitly tell the AI NOT to draw anything in the countdown area
        countdown_text = ""

    # Also add birthday text to event list for backwards compatibility
    birthday_text = ""
    for cd in countdowns:
        if cd["type"] == "birthday" and cd["days_away"] <= 7:
            if cd["days_away"] == 0:
                birthday_text = f"🎂 It's {cd['name']} today!"
            elif cd["days_away"] == 1:
                birthday_text = f"🎂 {cd['name']} is TOMORROW!"
            else:
                birthday_text = f"🎂 {cd['days_away']} days until {cd['name']}!"
            break

    if birthday_text:
        event_list_str += f"\n\n{birthday_text}"

    # Characters
    char_section = ""
    if characters_enabled and characters:
        people = [c for c in characters if c.get("type") == "kid"]
        extras = [c for c in characters if c.get("type") == "extra"]

        char_descs = []
        for i, person in enumerate(people):
            # Build age/gender description
            gender = person.get("gender", "male")
            age = person.get("age")
            name = person.get("name", "Person")

            if gender == "male":
                gender_word = "man" if (age and age >= 18) else "boy"
            elif gender == "female":
                gender_word = "woman" if (age and age >= 18) else "girl"
            else:
                gender_word = "person"

            age_str = f", age {age}" if age else ""
            desc = (
                f"{i+1}) A {gender_word} named {name}{age_str}. "
                f"{person.get('description', '')}"
            )
            char_descs.append(desc)
        for i, extra in enumerate(extras):
            char_descs.append(f"{len(people)+i+1}) {extra['name']}. {extra.get('description', '')}")

        all_chars = "\n".join(char_descs)

        # Add clothing guidance from weather — include actual temperature
        # so the AI doesn't draw snow gear on a mild 20°C winter day
        clothing_note = ""
        if weather and weather.get("clothing_hint"):
            temp = weather.get("temp")
            unit = weather.get("unit_symbol", "°C")
            condition = weather.get("condition", "")
            clothing_note = (
                f"\nIMPORTANT: Today's forecast high is {temp}{unit} ({condition.lower()}). "
                f"The characters should be dressed appropriately for {temp}{unit} "
                f"{raw_season} weather — wearing {weather['clothing_hint']}. "
                f"Do NOT draw snow, ice, or heavy frost unless the temperature is below 2°C."
            )

        char_section = (
            f"\n\nCHARACTERS (in the scene on the right side): "
            f"Show these characters in the scene. Incorporate the day's activities "
            f"into the illustration when relevant and appropriate."
            f"{clothing_note}"
            f"\nCHARACTERS:\n{all_chars}"
        )

    # Weather section
    weather_section = ""
    if weather:
        temp = weather.get("temp")
        unit = weather.get("unit_symbol", "°C")
        condition = weather.get("condition", "")
        emoji = weather.get("emoji", "")
        high = weather.get("high")
        low = weather.get("low")

        weather_badge = f"{emoji} {temp}{unit} {condition}"
        if high is not None and low is not None:
            weather_badge += f" (H:{high}{unit} L:{low}{unit})"

        weather_section = (
            f"In the BOTTOM LEFT corner of the image, draw a small weather badge or "
            f"banner in a clear, readable hand-drawn style. It should read: "
            f"'{weather_badge}'. Make it small but legible — like a little weather "
            f"stamp on the illustration."
        )

    # ─── Dynamic text layout based on event count ─────────────────
    # Adapt the left-side text area so a few events don't leave a huge
    # blank column. With many events the text panel is wider; with few
    # it's compact and vertically centred so the illustration fills more
    # of the canvas.
    if event_count <= 2:
        text_layout = (
            "LEFT SIDE — COMPACT TEXT OVERLAY (roughly 25% width, vertically centred):\n"
            "Because there are only a few items, keep the text block SHORT and vertically centred "
            "on the left side. The text area should be a compact, tidy cluster — NOT a tall column "
            "stretching the full height. Let the illustration fill most of the canvas. "
            "The text sits in the FOREGROUND — the scene continues behind and around it."
        )
        right_width = "roughly 75% width"
    elif event_count <= 5:
        text_layout = (
            "LEFT SIDE — TEXT OVERLAY (roughly 35% width, vertically centred):\n"
            "Place the schedule list on the left portion, vertically centred. The text block "
            "should be compact — only as tall as needed for the items. Don't stretch it to "
            "fill the full height. The text sits in the FOREGROUND on top of the illustration, "
            "but the scene continues behind and around it."
        )
        right_width = "roughly 65% width"
    else:
        text_layout = (
            "LEFT SIDE (roughly 40% width) — TEXT OVERLAY:\n"
            "Overlaid on top of the left portion of the scene, write a clear readable "
            "handwritten-style list of the day's schedule. The text sits in the FOREGROUND "
            "on top of the illustration, but the scene continues behind and around it — you "
            "might see trees, sky, a wall, or background details peeking around the edges. "
            "Keep the area behind the text relatively uncluttered so it stays legible."
        )
        right_width = "roughly 60% width"

    text_layout += (
        "\nEach event on its own line with a bullet.\n"
        "Events to show:\n"
    )

    # Build final prompt — choose template based on aesthetic
    if prompt_template and prompt_template.strip():
        template = prompt_template
    elif aesthetic == "fashion":
        template = FASHION_PROMPT_TEMPLATE
    else:
        template = DEFAULT_PROMPT_TEMPLATE

    prompt = template
    prompt = prompt.replace("{{DAY_NAME}}", day_name)
    prompt = prompt.replace("{{BANNER_TEXT}}", banner_text)
    prompt = prompt.replace("{{SCENE_DESCRIPTION}}", scene_description)
    prompt = prompt.replace("{{SEASON}}", raw_season)  # Kept for custom templates
    prompt = prompt.replace("{{TEXT_LAYOUT}}", text_layout)
    prompt = prompt.replace("{{RIGHT_WIDTH}}", right_width)
    prompt = prompt.replace("{{EVENT_LIST}}", event_list_str)
    prompt = prompt.replace("{{CHARACTERS}}", char_section)
    prompt = prompt.replace("{{BIRTHDAY}}", birthday_text)
    prompt = prompt.replace("{{MODE}}", mode)
    prompt = prompt.replace("{{WEATHER}}", weather_section)
    prompt = prompt.replace("{{COUNTDOWN}}", countdown_text)
    prompt = prompt.replace("{{REGION_GUIDANCE}}", region_guidance)

    return prompt


# ─── Image Generation ───────────────────────────────────────────

def generate_image_via_openrouter(prompt, api_key, model, reference_image_urls=None):
    """Call OpenRouter's Image API to generate an image."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": "3:2",
    }

    if reference_image_urls:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": url}}
            for url in reference_image_urls
        ]
        print(f"Passing {len(reference_image_urls)} reference images to the model")

    for attempt in range(3):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/images",
                headers=headers,
                json=payload,
                timeout=240,
            )
            if response.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if response.status_code != 200:
                print(f"Image API error {response.status_code}: {response.text[:300]}")
            response.raise_for_status()
            result = response.json()
            images = result.get("data", [])
            if images and images[0].get("b64_json"):
                return base64.b64decode(images[0]["b64_json"])
        except Exception as e:
            print(f"Image generation error (attempt {attempt+1}): {e}")

    return None


def generate_image_via_google_ai(prompt, api_key, model="gemini-3-pro-image", reference_image_urls=None):
    """Call Google AI Studio (Gemini API) to generate an image.

    Uses the generateContent endpoint with responseModalities=["IMAGE", "TEXT"].
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    # Build content parts
    parts = []

    # Add reference images if provided
    if reference_image_urls:
        for img_url in reference_image_urls:
            try:
                img_resp = requests.get(img_url, timeout=15)
                if img_resp.status_code == 200:
                    img_b64 = base64.b64encode(img_resp.content).decode("utf-8")
                    content_type = img_resp.headers.get("Content-Type", "image/png")
                    parts.append({
                        "inline_data": {
                            "mime_type": content_type,
                            "data": img_b64,
                        }
                    })
            except Exception as e:
                print(f"Failed to fetch reference image: {e}")
        if parts:
            print(f"Passing {len(parts)} reference images to Gemini")

    # Add the text prompt
    parts.append({"text": prompt})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=240)
            if response.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if response.status_code != 200:
                print(f"Gemini API error {response.status_code}: {response.text[:300]}")
            response.raise_for_status()

            result = response.json()
            # Extract image from response
            candidates = result.get("candidates", [])
            for candidate in candidates:
                content = candidate.get("content", {})
                for part in content.get("parts", []):
                    if "inlineData" in part:
                        return base64.b64decode(part["inlineData"]["data"])
                    if "inline_data" in part:
                        return base64.b64decode(part["inline_data"]["data"])

            print(f"No image in Gemini response (attempt {attempt+1})")
        except Exception as e:
            print(f"Gemini image generation error (attempt {attempt+1}): {e}")

    return None


# ─── Image Processing ───────────────────────────────────────────

def resize_and_dither(img_bytes):
    """Resize and apply Floyd-Steinberg dithering for the 6-color e-ink palette."""
    img = Image.open(io.BytesIO(img_bytes))

    # Center crop to display aspect ratio
    target_ratio = DISPLAY_WIDTH / DISPLAY_HEIGHT
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:
        new_width = int(img.height * target_ratio)
        left = (img.width - new_width) // 2
        img = img.crop((left, 0, left + new_width, img.height))
    elif img_ratio < target_ratio:
        new_height = int(img.width / target_ratio)
        top = (img.height - new_height) // 2
        img = img.crop((0, top, img.width, top + new_height))

    img = img.resize((DISPLAY_WIDTH, DISPLAY_HEIGHT), Image.LANCZOS)

    # Save full-color version
    full_color_buf = io.BytesIO()
    img.save(full_color_buf, format="PNG")
    full_color_bytes = full_color_buf.getvalue()

    # Apply Floyd-Steinberg dithering
    pixels = np.array(img.convert("RGB"), dtype=np.float64)
    h, w, _ = pixels.shape

    for y in range(h):
        for x in range(w):
            old_pixel = pixels[y, x].copy()
            distances = np.sqrt(np.sum((EINK_PALETTE - old_pixel) ** 2, axis=1))
            new_pixel = EINK_PALETTE[np.argmin(distances)]
            pixels[y, x] = new_pixel
            error = old_pixel - new_pixel

            if x + 1 < w:
                pixels[y, x + 1] += error * 7 / 16
            if y + 1 < h:
                if x - 1 >= 0:
                    pixels[y + 1, x - 1] += error * 3 / 16
                pixels[y + 1, x] += error * 5 / 16
                if x + 1 < w:
                    pixels[y + 1, x + 1] += error * 1 / 16

    pixels = np.clip(pixels, 0, 255).astype(np.uint8)
    dithered = Image.fromarray(pixels)

    dithered_buf = io.BytesIO()
    dithered.save(dithered_buf, format="PNG")
    dithered_bytes = dithered_buf.getvalue()

    return full_color_bytes, dithered_bytes


# ─── Helper: Run pipeline for a single user ─────────────────────

def _generate_for_device(uid, device_id, db, force=False):
    """Run the full image generation pipeline for a single device.

    Multi-device architecture: user-level settings (API key, timezone, location)
    come from settings/account, while device-level settings (aesthetic, model,
    calendar, prompt) come from devices/{device_id}/config.

    Args:
        uid: Firebase user ID
        device_id: Device document ID (e.g. "default", or auto-generated)
        db: Firestore client
        force: If True, skip the hash check and always regenerate.

    Returns:
        dict with results, {"skipped": True} if nothing changed, or None
        if user isn't configured.
    """
    user_ref = db.collection("users").document(uid)

    # ─── Load user-level settings ───────────────────────────────
    # Try new settings/account first, fall back to legacy settings/config
    account_doc = user_ref.collection("settings").document("account").get()
    if account_doc.exists:
        account = account_doc.to_dict()
    else:
        # Legacy fallback for pre-migration users
        legacy_doc = user_ref.collection("settings").document("config").get()
        if not legacy_doc.exists:
            return None
        account = legacy_doc.to_dict()

    api_key = account.get("openrouter_api_key", "")
    api_provider = account.get("api_provider", "google")
    ical_url = account.get("ical_url", "")
    timezone = account.get("timezone", DEFAULT_TIMEZONE)
    latitude = account.get("latitude")
    longitude = account.get("longitude")
    temp_unit = account.get("temp_unit", "celsius")

    # ─── Load device-level settings ─────────────────────────────
    device_ref = user_ref.collection("devices").document(device_id)
    device_doc = device_ref.collection("config").document("config").get()

    # Fall back: if no device doc exists, try legacy settings/config for
    # device-level fields (handles pre-migration single-device users)
    if device_doc.exists:
        device = device_doc.to_dict()
    else:
        # Check for device config directly on the device document
        device_direct = device_ref.get()
        if device_direct.exists:
            device = device_direct.to_dict()
        else:
            # Legacy: read from settings/config
            legacy = user_ref.collection("settings").document("config").get()
            device = legacy.to_dict() if legacy.exists else {}

    model = device.get("image_model", "gemini-3-pro-image")
    characters_enabled = device.get("characters_enabled", True)
    calendar_id = device.get("calendar_id", account.get("calendar_id", "primary"))
    aesthetic = device.get("aesthetic", "whimsical")

    # ─── API Key Verification ───────────────────────────────────
    if not api_key:
        print(f"  ❌ Missing API key for user {uid}")
        return None

    print(f"  🔑 Using API provider: {api_provider}")

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    hour = now.hour
    today = now.date()
    tomorrow = today + timedelta(days=1)

    # ─── Fetch events for today AND tomorrow (iCal) ─────────────
    today_events = []
    tomorrow_events = []
    birthdays = []
    
    if ical_url:
        today_events = fetch_events_ical(ical_url, timezone=timezone, target_date=today)
        tomorrow_events = fetch_events_ical(ical_url, timezone=timezone, target_date=tomorrow)
        print(f"  📅 iCal: {len(today_events)} today, {len(tomorrow_events)} tomorrow")
    else:
        print("  ⚠️ No iCal URL provided")

    # ─── Smart mode determination ───────────────────────────────
    mode, banner_text, events = _determine_mode_and_events(
        hour, today_events, tomorrow_events, timezone
    )
    print(f"  Mode: {mode}, Banner: '{banner_text}', Events: {len(events)}")

    # ─── Fetch weather ──────────────────────────────────────────
    weather = None
    weather_summary = ""
    if latitude and longitude:
        weather = fetch_weather(latitude, longitude, temp_unit=temp_unit)
        if weather:
            weather_summary = f"{weather['emoji']} {weather['condition']}"
            print(f"  Weather: {weather['temp']}{weather['unit_symbol']} {weather['condition']}")

    # ─── Change detection ───────────────────────────────────────
    generation_hash = _compute_generation_hash(mode, banner_text, events, weather_summary, weather=weather)

    if not force:
        # Check device-level status for hash
        status_doc = device_ref.collection("status").document("status").get()
        if not status_doc.exists:
            # Legacy fallback
            status_doc = user_ref.collection("settings").document("status").get()
        if status_doc.exists:
            last_hash = status_doc.to_dict().get("last_generation_hash", "")
            if last_hash == generation_hash:
                return {"skipped": True, "hash": generation_hash}

    print(f"  🎨 Changes detected (hash={generation_hash}), generating new image for device '{device_id}'...")

    # ─── Load characters ────────────────────────────────────────
    chars_snap = user_ref.collection("characters").stream()
    characters = []
    for doc_snap in chars_snap:
        char = doc_snap.to_dict()
        char["id"] = doc_snap.id
        characters.append(char)

    # Filter characters by device selection (if device has selected_characters)
    selected_chars = device.get("selected_characters")
    if selected_chars is not None and len(selected_chars) > 0:
        characters = [c for c in characters if c["id"] in selected_chars]

    # Load device-level prompt template
    prompt_doc = device_ref.collection("prompt").document("prompt").get()
    prompt_template = ""
    if prompt_doc.exists:
        prompt_template = prompt_doc.to_dict().get("template", "")
    else:
        # Legacy fallback
        legacy_prompt = user_ref.collection("settings").document("prompt").get()
        if legacy_prompt.exists:
            prompt_template = legacy_prompt.to_dict().get("template", "")

    # ─── Humanize events via Gemini ────────────────────────────────
    # Use a lightweight Gemini text call to rewrite raw calendar entries
    # (e.g. "9:00am Tavi Library Bag") into friendly human language
    # (e.g. "📚 9am — Tavi, remember library bag!") before the image prompt.
    events = humanize_events_via_gemini(
        events, api_key, api_provider=api_provider, characters=characters,
    )

    # ─── Location lookup (cached in account settings) ───────────
    location_name = account.get("location_name", "")
    if not location_name and latitude and longitude:
        location_name = _reverse_geocode_location(latitude, longitude)
        if location_name:
            # Cache it so we don't re-geocode every time
            user_ref.collection("settings").document("account").update({
                "location_name": location_name,
            })
            print(f"  📍 Location: {location_name} (cached)")
    elif location_name:
        print(f"  📍 Location: {location_name} (cached)")

    # ─── Scene description via Gemini Flash Lite ────────────────
    # Instead of just "winter scene" (which draws snow in Sydney),
    # use Gemini to generate a realistic, location-aware description.
    scene_description = ""
    if weather:
        raw_season = get_season(now.month)
        scene_description = describe_scene_weather_via_gemini(
            weather, raw_season, timezone, api_key,
            api_provider=api_provider,
            location_name=location_name,
            events=events,
        )

    # ─── Daily important events scan ────────────────────────────
    # Once per day, scan the next 14 days for important events
    # (birthdays, trips, holidays) and store in Firestore.
    important_events = []
    important_doc = user_ref.collection("settings").document("important_events").get()
    if important_doc.exists:
        ie_data = important_doc.to_dict()
        last_scanned = ie_data.get("last_scanned", "")
        important_events = ie_data.get("events", [])
    else:
        last_scanned = ""

    if last_scanned != str(today) and creds:
        # Fetch 14 days of events for the scan
        print(f"  📅 Running daily important events scan...")
        events_14_days = []
        for day_offset in range(14):
            target = today + timedelta(days=day_offset)
            day_events = fetch_events_google_api(
                creds, calendar_id, timezone, target_date=target,
            )
            for ev in day_events:
                ev["date"] = str(target)
                ev["days_away"] = day_offset
            events_14_days.extend(day_events)

        if events_14_days:
            important_events = scan_important_events_via_gemini(
                events_14_days, api_key,
                api_provider=api_provider,
                characters=characters,
            )

        # Store results in Firestore
        user_ref.collection("settings").document("important_events").set({
            "last_scanned": str(today),
            "events": important_events,
            "scanned_at": datetime.now(tz).isoformat(),
        })
        print(f"  📅 Stored {len(important_events)} important events")

    # ─── Build prompt ───────────────────────────────────────────
    prompt = build_prompt(
        events, characters, prompt_template,
        timezone=timezone, mode=mode,
        banner_text=banner_text,
        characters_enabled=characters_enabled,
        weather=weather,
        birthdays=birthdays,
        aesthetic=aesthetic,
        scene_description=scene_description,
        important_events=important_events,
        location_name=location_name,
    )

    # Collect reference images
    reference_urls = []
    if characters_enabled:
        for char in characters:
            if char.get("imageUrl"):
                reference_urls.append(char["imageUrl"])

    # ─── Generate image (route to correct provider) ──────────────
    refs = reference_urls if reference_urls else None

    if api_provider == "openrouter":
        # OpenRouter models need the 'google/' prefix
        or_model = model if "/" in model else f"google/{model}"
        print(f"  Using OpenRouter: {or_model}")
        img_bytes = generate_image_via_openrouter(prompt, api_key, or_model, reference_image_urls=refs)
    else:
        # Google AI Studio (default)
        # Strip 'google/' prefix if present
        gemini_model = model.replace("google/", "") if model.startswith("google/") else model
        print(f"  Using Google AI Studio: {gemini_model}")
        img_bytes = generate_image_via_google_ai(prompt, api_key, gemini_model, reference_image_urls=refs)

    if not img_bytes:
        return {"success": False, "error": "Image generation failed"}

    # Resize & dither
    full_color_bytes, dithered_bytes = resize_and_dither(img_bytes)

    # Upload to device-scoped Firebase Storage path
    bucket = storage.bucket()
    timestamp = now.strftime("%Y%m%d_%H%M%S")

    blob_latest = bucket.blob(f"users/{uid}/devices/{device_id}/display/latest_display.png")
    blob_latest.upload_from_string(full_color_bytes, content_type="image/png")
    blob_latest.make_public()

    blob_dithered = bucket.blob(f"users/{uid}/devices/{device_id}/display/latest_display_dithered.png")
    blob_dithered.upload_from_string(dithered_bytes, content_type="image/png")
    blob_dithered.make_public()

    # Also write to device-level path so ESP32 can fetch using only its MAC address
    blob_device = bucket.blob(f"devices/{device_id}/display/latest_display.png")
    blob_device.upload_from_string(full_color_bytes, content_type="image/png")
    blob_device.make_public()

    blob_archive = bucket.blob(f"users/{uid}/devices/{device_id}/archive/calendar_art_{timestamp}.png")
    blob_archive.upload_from_string(full_color_bytes, content_type="image/png")

    # ─── Update device status (with hash for next comparison) ───
    status_data = {
        "last_generated": now.isoformat(),
        "last_prompt": prompt,
        "last_mode": mode,
        "last_banner": banner_text,
        "events_count": len(events),
        "image_url": blob_latest.public_url,
        "dithered_url": blob_dithered.public_url,
        "last_generation_hash": generation_hash,
        "device_id": device_id,
    }
    if weather:
        status_data["last_weather"] = f"{weather['emoji']} {weather['temp']}{weather['unit_symbol']} {weather['condition']}"

    device_ref.collection("status").document("status").set(status_data)

    # Also update legacy status path for backwards compatibility
    db.collection("users").document(uid).collection("settings").document("status").set(status_data)

    return {
        "success": True,
        "image_url": blob_latest.public_url,
        "dithered_url": blob_dithered.public_url,
        "events_count": len(events),
        "mode": mode,
        "banner": banner_text,
        "hash": generation_hash,
        "device_id": device_id,
        "prompt_preview": prompt[:500],
    }


# ─── Cloud Functions ────────────────────────────────────────────

@https_fn.on_call(
    memory=options.MemoryOption.GB_1,
    timeout_sec=300,
    region="australia-southeast1",
    secrets=["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GLANCEBOARD_API_KEY"],
)
def generate_display(req: https_fn.CallableRequest):
    """Generate a new display image for a specific device.

    Enforces a daily regeneration limit of 3 manual generations per user.
    The scheduled cron job (scheduled_generate) is not subject to this limit.
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    uid = req.auth.uid
    device_id = req.data.get("device_id", "default") if req.data else "default"
    db = firestore.client()

    # Ensure parent user document exists (needed for scheduler to enumerate users)
    db.collection("users").document(uid).set({"last_seen": datetime.now().isoformat()}, merge=True)

    # ─── Daily regeneration limit (3 per user per day) ───────────
    # Only applies to Plus tier (server API key). Hosted users bring
    # their own key, so they get unlimited manual regenerations.
    DAILY_REGEN_LIMIT = 3
    user_ref = db.collection("users").document(uid)

    # Check subscription tier early to decide if limit applies
    sub_doc = user_ref.collection("settings").document("subscription").get()
    tier = "free"
    if sub_doc.exists:
        tier = sub_doc.to_dict().get("tier", "free")

    # Hosted tier users use their own API key — no limit
    limit_applies = (tier == "plus")

    if limit_applies:
        regen_ref = user_ref.collection("settings").document("regen_limit")
        regen_doc = regen_ref.get()

        # Load user timezone for date comparison
        account_doc_for_tz = user_ref.collection("settings").document("account").get()
        user_tz_str = DEFAULT_TIMEZONE
        if account_doc_for_tz.exists:
            user_tz_str = account_doc_for_tz.to_dict().get("timezone", DEFAULT_TIMEZONE)
        else:
            legacy_tz = user_ref.collection("settings").document("config").get()
            if legacy_tz.exists:
                user_tz_str = legacy_tz.to_dict().get("timezone", DEFAULT_TIMEZONE)

        user_tz = ZoneInfo(user_tz_str)
        today_str = datetime.now(user_tz).strftime("%Y-%m-%d")

        regen_count = 0
        if regen_doc.exists:
            regen_data = regen_doc.to_dict()
            if regen_data.get("date") == today_str:
                regen_count = regen_data.get("count", 0)
            # else: different day, reset to 0

        if regen_count >= DAILY_REGEN_LIMIT:
            remaining_msg = "You've used all 3 regenerations for today. New ones are available tomorrow, or wait for the automatic scheduled update."
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.RESOURCE_EXHAUSTED,
                message=remaining_msg,
            )

    # Check if user has settings (account or legacy config)
    account_doc = user_ref.collection("settings").document("account").get()
    if not account_doc.exists:
        # Try legacy path
        legacy_doc = user_ref.collection("settings").document("config").get()
        if not legacy_doc.exists:
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.NOT_FOUND,
                message="Settings not configured. Please complete setup first.",
            )
        settings = legacy_doc.to_dict()
    else:
        settings = account_doc.to_dict()

    # Check if user has an API key, is a Plus subscriber, or is in workshop mode
    # (sub_doc and tier were already loaded above for the regen limit check)
    is_plus = (tier == "plus")
    is_workshop = settings.get("workshop_mode", False)

    if not settings.get("openrouter_api_key") and not is_plus and not is_workshop:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            message="API key not set. Please add an API key in Settings, or upgrade to Glanceboard Plus.",
        )

    result = _generate_for_device(uid, device_id, db, force=True)
    if not result:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INTERNAL,
            message="Generation failed. Check your settings.",
        )

    if not result.get("success"):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INTERNAL,
            message=result.get("error", "Image generation failed."),
        )

    # ─── Increment daily regeneration count on success ───────────
    # Only track and enforce for Plus tier (server API key).
    # Hosted/free users use their own key — unlimited regenerations.
    if limit_applies:
        regen_ref.set({
            "date": today_str,
            "count": regen_count + 1,
            "last_regen": datetime.now(user_tz).isoformat(),
        })
        result["regen_count"] = regen_count + 1
        result["regen_limit"] = DAILY_REGEN_LIMIT
    else:
        # No limit for hosted/free tier — signal unlimited to the frontend
        result["regen_count"] = 0
        result["regen_limit"] = -1  # -1 signals "unlimited"

    return result


@https_fn.on_call(
    region="australia-southeast1",
    secrets=["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
)
def exchange_calendar_token(req: https_fn.CallableRequest):
    """
    Exchange a Google authorization code for access + refresh tokens.
    Called after the user completes the GIS authorization code flow on the frontend.
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    code = req.data.get("code")
    redirect_uri = req.data.get("redirect_uri", "postmessage")
    if not code:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message="Authorization code required.",
        )

    client_id, client_secret = _get_google_secrets()

    # Exchange authorization code for tokens
    token_response = requests.post(GOOGLE_TOKEN_URI, data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })

    if token_response.status_code != 200:
        print(f"Token exchange failed: {token_response.text}")
        raise https_fn.HttpsError(

@https_fn.on_call(region="australia-southeast1")
def get_status(req: https_fn.CallableRequest):
    """Get the current generation status for the calling user's device."""
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    uid = req.auth.uid
    device_id = req.data.get("device_id", "default") if req.data else "default"
    db = firestore.client()

    # Ensure parent user document exists (needed for scheduler to enumerate users)
    db.collection("users").document(uid).set({"last_seen": datetime.now().isoformat()}, merge=True)

    # Try device-scoped status first
    status_doc = db.collection("users").document(uid).collection("devices").document(device_id).collection("status").document("status").get()
    if status_doc.exists:
        result = status_doc.to_dict()
    else:
        # Legacy fallback
        legacy_doc = db.collection("users").document(uid).collection("settings").document("status").get()
        if legacy_doc.exists:
            result = legacy_doc.to_dict()
        else:
            result = {"last_generated": None, "image_url": None}

    # Hosted/free tier — no limit (they use their own API key)
    result["regen_count"] = 0
    result["regen_limit"] = -1  # -1 signals "unlimited" to the frontend
    result["regen_remaining"] = -1

    return result


@https_fn.on_call(
    region="australia-southeast1",
)
def preview_prompt(req: https_fn.CallableRequest):
    """Preview the prompt with the calling user's current device settings."""
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    uid = req.auth.uid
    device_id = req.data.get("device_id", "default") if req.data else "default"
    db = firestore.client()
    user_ref = db.collection("users").document(uid)

    # Load user-level settings
    account_doc = user_ref.collection("settings").document("account").get()
    if not account_doc.exists:
        account_doc = user_ref.collection("settings").document("config").get()
    account = account_doc.to_dict() if account_doc.exists else {}

    ical_url = account.get("ical_url", "")
    timezone = account.get("timezone", DEFAULT_TIMEZONE)
    latitude = account.get("latitude")
    longitude = account.get("longitude")
    temp_unit = account.get("temp_unit", "celsius")

    # Load device-level settings
    device_ref = user_ref.collection("devices").document(device_id)
    device_doc = device_ref.get()
    device = device_doc.to_dict() if device_doc.exists else account
    characters_enabled = device.get("characters_enabled", True)
    calendar_id = device.get("calendar_id", account.get("calendar_id", "primary"))

    # Determine mode
    tz = ZoneInfo(timezone)
    hour = datetime.now(tz).hour
    mode = "tomorrow" if hour >= 14 else "today"

    # Fetch events
    events = []
    birthdays = []
    if ical_url:
        tz = ZoneInfo(timezone)
        target_date = datetime.now(tz).date()
        if mode == "tomorrow":
            target_date += timedelta(days=1)
        events = fetch_events_ical(ical_url, timezone=timezone, target_date=target_date)

    # Fetch weather
    weather = None
    if latitude and longitude:
        weather = fetch_weather(latitude, longitude, temp_unit=temp_unit)

    # Load characters (shared, but filter by device selection)
    chars_snap = user_ref.collection("characters").stream()
    characters = [doc_snap.to_dict() | {"id": doc_snap.id} for doc_snap in chars_snap]
    selected_chars = device.get("selected_characters")
    if selected_chars is not None and len(selected_chars) > 0:
        characters = [c for c in characters if c["id"] in selected_chars]

    # Load device-level prompt template
    prompt_doc = device_ref.collection("prompt").document("prompt").get()
    prompt_template = ""
    if prompt_doc.exists:
        prompt_template = prompt_doc.to_dict().get("template", "")
    else:
        legacy_prompt = user_ref.collection("settings").document("prompt").get()
        if legacy_prompt.exists:
            prompt_template = legacy_prompt.to_dict().get("template", "")

    prompt = build_prompt(
        events, characters, prompt_template,
        timezone=timezone, mode=mode,
        characters_enabled=characters_enabled,
        weather=weather,
        birthdays=birthdays,
    )

    return {
        "prompt": prompt,
        "events": events,
        "characters_count": len(characters),
        "weather": weather,
    }


@scheduler_fn.on_schedule(
    schedule="*/15 * * * *",
    timezone=scheduler_fn.Timezone("Australia/Sydney"),
    memory=options.MemoryOption.GB_1,
    timeout_sec=540,
    region="australia-southeast1",
    secrets=["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GLANCEBOARD_API_KEY"],
)
def scheduled_generate(event: scheduler_fn.ScheduledEvent):
    """Time-slot scheduled generation — runs every 15 minutes.

    For each user, checks if the current hour (in their timezone) matches one
    of their configured generation times (default: 4am, 10am, 2pm, 6pm).
    Only generates if:
      1. Current hour is in the user's generation_schedule
      2. This time slot hasn't already been generated today
      3. Content hash differs from last generation (secondary optimisation)

    Plus tier: max 4 generation times per day.
    Hosted (BYO key) / Self-hosted: unlimited.
    """
    import sys

    DEFAULT_SCHEDULE = [4, 10, 14, 18]

    user_count = 0
    generated_count = 0
    skipped_count = 0
    not_scheduled_count = 0
    inactive_count = 0
    device_count = 0
    error_count = 0
    no_config_count = 0

    try:
        print(f"Scheduled generate starting at {datetime.now().isoformat()}", flush=True)
        db = firestore.client()
        users_list = list(db.collection("users").stream())
        print(f"Found {len(users_list)} users", flush=True)

        for user_doc in users_list:
            uid = user_doc.id
            user_count += 1

            # Check subscription status — skip users with inactive paid subscriptions
            sub_doc = db.collection("users").document(uid).collection("settings").document("subscription").get()
            tier = "free"
            if sub_doc.exists:
                sub = sub_doc.to_dict()
                status = sub.get("status", "")
                tier = sub.get("tier", "free")
                if tier in ("hosted", "plus") and status not in ("active", "trialing"):
                    inactive_count += 1
                    continue  # Don't generate for users with lapsed subscriptions

            # ─── Get user's timezone and generation schedule ────────
            account_doc = db.collection("users").document(uid).collection("settings").document("account").get()
            if not account_doc.exists:
                # Try legacy config
                account_doc = db.collection("users").document(uid).collection("settings").document("config").get()

            if not account_doc.exists:
                no_config_count += 1
                continue

            account = account_doc.to_dict()
            # Skip paused accounts
            if account.get("paused"):
                inactive_count += 1
                continue

            user_tz_str = account.get("timezone", DEFAULT_TIMEZONE)
            generation_schedule = account.get("generation_schedule", DEFAULT_SCHEDULE)

            # Validate schedule — ensure it's a list of integers 0-23
            if not isinstance(generation_schedule, list):
                generation_schedule = DEFAULT_SCHEDULE
            generation_schedule = [int(h) for h in generation_schedule if isinstance(h, (int, float)) and 0 <= h <= 23]
            if not generation_schedule:
                generation_schedule = DEFAULT_SCHEDULE

            # ─── Check if current hour matches a scheduled time ─────
            try:
                user_tz = ZoneInfo(user_tz_str)
            except Exception:
                user_tz = ZoneInfo(DEFAULT_TIMEZONE)
            user_now = datetime.now(user_tz)
            current_hour = user_now.hour
            today_str = user_now.strftime("%Y-%m-%d")

            if current_hour not in generation_schedule:
                not_scheduled_count += 1
                continue

            # ─── Check if this slot was already generated today ──────
            # We track per-user (not per-device) to avoid double-checking
            slot_key = f"{today_str}_{current_hour}"
            status_ref = db.collection("users").document(uid).collection("settings").document("generation_status")
            gen_status_doc = status_ref.get()
            if gen_status_doc.exists:
                gen_status = gen_status_doc.to_dict()
                completed_slots = gen_status.get("completed_slots", [])
                if slot_key in completed_slots:
                    skipped_count += 1
                    continue
            else:
                completed_slots = []

            # ─── Generate for all devices ────────────────────────────
            devices = list(db.collection("users").document(uid).collection("devices").stream())

            if not devices:
                # Pre-migration user with no devices collection — treat as single "default" device
                device_ids = ["default"]
            else:
                device_ids = [d.id for d in devices]

            slot_generated = False
            for device_id in device_ids:
                device_count += 1
                try:
                    result = _generate_for_device(uid, device_id, db)
                    if result and result.get("success"):
                        generated_count += 1
                        slot_generated = True
                        print(f"Generated for {uid}/{device_id}: {result['events_count']} events, mode={result['mode']}", flush=True)
                    elif result and result.get("skipped"):
                        # Hash-based skip (nothing changed) — still mark slot as done
                        skipped_count += 1
                        slot_generated = True
                    elif result is None:
                        no_config_count += 1
                    else:
                        error_count += 1
                        print(f"Failed for {uid}/{device_id}: {result.get('error', 'unknown') if result else 'no result'}", flush=True)
                except Exception as e:
                    error_count += 1
                    print(f"Error for {uid}/{device_id}: {e}", flush=True)

            # ─── Mark this slot as completed ─────────────────────────
            if slot_generated:
                # Reset completed_slots if it's a new day
                if completed_slots and not completed_slots[0].startswith(today_str):
                    completed_slots = []
                completed_slots.append(slot_key)
                status_ref.set({
                    "completed_slots": completed_slots,
                    "last_slot": slot_key,
                    "last_run": user_now.isoformat(),
                }, merge=True)

        print(f"Scheduled run complete: {generated_count} generated, {skipped_count} skipped, {not_scheduled_count} not-scheduled, {inactive_count} inactive, {no_config_count} no-config, {error_count} errors, {device_count} devices across {user_count} users.", flush=True)

    except Exception as e:
        print(f"FATAL ERROR in scheduled_generate: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.stdout.flush()



# ─── Device Management Functions ────────────────────────────────

ADDITIONAL_DEVICE_PRICE_ID = "price_1ToIH4EuTcW8yunEOiKHC6BY"


@https_fn.on_call(
    region="australia-southeast1",
)
def create_device(req: https_fn.CallableRequest):
    """Create a new device for the calling user.

    Args (in req.data):
        name: Display name for the device (e.g. "Kitchen", "Kids Room")
        aesthetic: Art style (default: "whimsical")
        device_id: Optional — hardware ID (MAC address) from QR code.
                   If not provided, a Firestore auto-ID is used.
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    uid = req.auth.uid
    name = req.data.get("name", "New Display")
    aesthetic = req.data.get("aesthetic", "whimsical")
    explicit_device_id = req.data.get("device_id")  # MAC address from QR code
    db = firestore.client()
    user_ref = db.collection("users").document(uid)

    # Count existing devices
    devices = list(user_ref.collection("devices").stream())
    device_count = len(devices)

    # Check subscription — paid users get 1 free, extras need billing
    sub_doc = user_ref.collection("settings").document("subscription").get()
    tier = "free"
    if sub_doc.exists:
        tier = sub_doc.to_dict().get("tier", "free")

    # For paid tiers, check device limits
    if tier in ("hosted", "plus") and device_count >= 1:
        # They need to pay for additional devices
        # The frontend will handle the Stripe billing flow
        pass  # Allow creation — billing is handled by update_device_billing

    # Create the device document
    device_data = {
        "name": name,
        "aesthetic": aesthetic,
        "image_model": "google/gemini-3-pro-image",
        "characters_enabled": True,
        "calendar_id": "primary",
        "selected_characters": [],  # Empty = use all characters
        "created_at": datetime.now().isoformat(),
    }

    # Use explicit device_id (MAC from QR code) or auto-generate
    if explicit_device_id:
        new_device_ref = user_ref.collection("devices").document(explicit_device_id)
        # Check if this device is already claimed by this user
        existing = new_device_ref.get()
        if existing.exists:
            return {
                "device_id": explicit_device_id,
                "name": existing.to_dict().get("name", name),
                "device_count": device_count,
                "billing_required": False,
                "already_exists": True,
            }
        new_device_ref.set(device_data)
    else:
        new_device_ref = user_ref.collection("devices").document()
        new_device_ref.set(device_data)

    return {
        "device_id": new_device_ref.id,
        "name": name,
        "device_count": device_count + 1,
        "billing_required": tier in ("hosted", "plus") and device_count >= 1,
    }


@https_fn.on_call(
    region="australia-southeast1",
)
def delete_device(req: https_fn.CallableRequest):
    """Delete a device and its associated data.

    Args (in req.data):
        device_id: The device ID to delete
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    uid = req.auth.uid
    device_id = req.data.get("device_id")
    if not device_id:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message="device_id required.",
        )

    db = firestore.client()
    user_ref = db.collection("users").document(uid)

    # Can't delete the last device
    devices = list(user_ref.collection("devices").stream())
    if len(devices) <= 1:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            message="Cannot delete your only device.",
        )

    # Delete device document and subcollections
    device_ref = user_ref.collection("devices").document(device_id)
    if not device_ref.get().exists:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.NOT_FOUND,
            message="Device not found.",
        )

    # Delete subcollection docs
    for subcol_name in ["config", "prompt", "status"]:
        for doc_snap in device_ref.collection(subcol_name).stream():
            doc_snap.reference.delete()

    device_ref.delete()

    # Clean up Storage files for this device
    try:
        bucket = storage.bucket()
        blobs = bucket.list_blobs(prefix=f"users/{uid}/devices/{device_id}/")
        for blob in blobs:
            blob.delete()
        print(f"🗑️ Cleaned up storage for {uid}/devices/{device_id}")
    except Exception as e:
        print(f"⚠️ Storage cleanup error: {e}")

    remaining = len(devices) - 1
    return {
        "deleted": device_id,
        "remaining_devices": remaining,
    }


@https_fn.on_call(
    region="australia-southeast1",
)
def list_devices(req: https_fn.CallableRequest):
    """List all devices for the calling user."""
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    uid = req.auth.uid
    db = firestore.client()
    user_ref = db.collection("users").document(uid)

    devices = []
    for doc_snap in user_ref.collection("devices").stream():
        device_data = doc_snap.to_dict()
        device_data["id"] = doc_snap.id

        # Also load the latest status for this device
        status_doc = doc_snap.reference.collection("status").document("status").get()
        if status_doc.exists:
            status = status_doc.to_dict()
            device_data["last_generated"] = status.get("last_generated")
            device_data["image_url"] = status.get("image_url")
            device_data["dithered_url"] = status.get("dithered_url")

        devices.append(device_data)

    return {"devices": devices}


@https_fn.on_call(
    region="australia-southeast1",
)
def migrate_to_devices(req: https_fn.CallableRequest):
    """One-time migration: move a user's single-device data into devices/default.

    Safe to call multiple times — skips if devices/default already exists.
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    uid = req.auth.uid
    db = firestore.client()
    user_ref = db.collection("users").document(uid)
    device_ref = user_ref.collection("devices").document("default")

    # Skip if already migrated
    if device_ref.get().exists:
        return {"status": "already_migrated"}

    # Read legacy settings/config
    config_doc = user_ref.collection("settings").document("config").get()
    if not config_doc.exists:
        return {"status": "no_config"}

    config = config_doc.to_dict()

    # Split into user-level (account) and device-level fields
    user_fields = [
        "openrouter_api_key", "api_provider", "ical_url", "timezone",
        "latitude", "longitude", "temp_unit",
    ]
    device_fields = [
        "image_model", "characters_enabled", "calendar_id", "aesthetic",
    ]

    account_data = {k: config[k] for k in user_fields if k in config}
    device_data = {k: config[k] for k in device_fields if k in config}
    device_data["name"] = "Main Display"
    device_data["selected_characters"] = []  # Use all characters
    device_data["created_at"] = datetime.now().isoformat()

    # Write user-level settings to settings/account
    user_ref.collection("settings").document("account").set(account_data)

    # Write device-level settings to devices/default
    device_ref.set(device_data)

    # Copy prompt template to device-level
    prompt_doc = user_ref.collection("settings").document("prompt").get()
    if prompt_doc.exists:
        device_ref.collection("prompt").document("prompt").set(prompt_doc.to_dict())

    # Copy status to device-level
    status_doc = user_ref.collection("settings").document("status").get()
    if status_doc.exists:
        device_ref.collection("status").document("status").set(status_doc.to_dict())

    # Copy storage files to new device-scoped paths
    try:
        bucket = storage.bucket()
        old_files = {
            f"users/{uid}/display/latest_display.png": f"users/{uid}/devices/default/display/latest_display.png",
            f"users/{uid}/display/latest_display_dithered.png": f"users/{uid}/devices/default/display/latest_display_dithered.png",
        }
        for old_path, new_path in old_files.items():
            old_blob = bucket.blob(old_path)
            if old_blob.exists():
                bucket.copy_blob(old_blob, bucket, new_path)
                new_blob = bucket.blob(new_path)
                new_blob.make_public()
                print(f"  Copied {old_path} -> {new_path}")
    except Exception as e:
        print(f"⚠️ Storage migration error: {e}")

    print(f"✅ Migrated {uid} to multi-device (devices/default)")
    return {"status": "migrated", "device_id": "default"}


# ─── Workshop: Claim Board ──────────────────────────────────────

@https_fn.on_call(
    region="australia-southeast1",
)
def claim_workshop_board(req: https_fn.CallableRequest):
    """Claim a workshop board for the authenticated user.

    Called when a workshop participant scans a QR code and signs in.
    Atomically marks the board as claimed and creates their device document
    with pre-configured workshop settings.

    Args (in req.data):
        board_id: The workshop board ID (e.g. "BOARD_01")
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    uid = req.auth.uid
    board_id = req.data.get("board_id") if req.data else None

    if not board_id:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message="board_id is required.",
        )

    db = firestore.client()

    # Check board exists
    board_ref = db.collection("workshop_boards").document(board_id)
    board_doc = board_ref.get()

    if not board_doc.exists:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.NOT_FOUND,
            message="Board not found.",
        )

    board_data = board_doc.to_dict()

    # Check if already claimed by someone else
    if board_data.get("claimed") and board_data.get("claimed_by_uid") != uid:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.ALREADY_EXISTS,
            message=f"{board_data.get('board_name', 'This board')} has already been claimed.",
        )

    # Claim the board
    board_ref.update({
        "claimed": True,
        "claimed_by_uid": uid,
        "claimed_at": datetime.now().isoformat(),
    })

    # Create user document
    user_ref = db.collection("users").document(uid)
    user_ref.set({"last_seen": datetime.now().isoformat()}, merge=True)

    # Create device document with workshop defaults
    device_id = board_data.get("device_id", f"workshop_{board_id}")
    device_ref = user_ref.collection("devices").document(device_id)
    device_ref.set({
        "name": board_data.get("board_name", "Workshop Board"),
        "aesthetic": "whimsical",
        "image_model": "google/gemini-3-pro-image",
        "characters_enabled": True,
        "calendar_id": "primary",
        "selected_characters": [],
        "workshop_board_id": board_id,
        "created_at": datetime.now().isoformat(),
    }, merge=True)

    return {
        "status": "claimed",
        "board_name": board_data.get("board_name"),
        "device_id": device_id,
    }


# ─── Weekly Model List Refresh ──────────────────────────────────

# Google AI Studio models are manually curated (their API doesn't clearly
# flag image-generation capability). We maintain this allowlist and only
# auto-discover new models via OpenRouter.
GOOGLE_CURATED_MODELS = [
    {
        "id": "google/gemini-2.5-flash-image",
        "name": "Nano Banana — Gemini 2.5 Flash",
        "provider": "Google",
        "group": "Google (Gemini)",
    },
    {
        "id": "google/gemini-3.1-flash-image",
        "name": "Nano Banana 2 — Gemini 3.1 Flash",
        "provider": "Google",
        "group": "Google (Gemini)",
    },
    {
        "id": "google/gemini-3-pro-image",
        "name": "Nano Banana Pro — Gemini 3 Pro",
        "provider": "Google",
        "group": "Google (Gemini)",
    },
]

# Only include OpenRouter models from these providers
OPENROUTER_ALLOWED_PROVIDERS = {
    "google", "openai", "black-forest-labs",
}


@scheduler_fn.on_schedule(
    schedule="0 3 * * 1",  # Every Monday at 3am
    timezone=scheduler_fn.Timezone("Australia/Sydney"),
    region="australia-southeast1",
    memory=options.MemoryOption.MB_256,
    timeout_sec=60,
)
def refresh_available_models(event: scheduler_fn.ScheduledEvent):
    """Refresh the list of available image generation models.

    Runs weekly. Fetches from OpenRouter's public API, filters to
    known-working providers, and stores in Firestore for the frontend.
    Google models are manually curated.
    """
    print("🔄 Refreshing available models list...")

    # ─── 1. Fetch OpenRouter image models (public API, no key needed) ──
    openrouter_models = []
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            params={"output_modalities": "image"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        for m in data.get("data", []):
            model_id = m.get("id", "")
            provider_slug = model_id.split("/")[0] if "/" in model_id else ""

            # Skip models not from allowed providers
            if provider_slug not in OPENROUTER_ALLOWED_PROVIDERS:
                continue

            # Skip preview models, vector/SVG models, and the auto-router
            name = m.get("name", "")
            if "preview" in model_id.lower() or "vector" in model_id.lower():
                continue
            if model_id == "openrouter/auto":
                continue

            # Determine display group
            if provider_slug == "google":
                group = "Google (Gemini)"
            elif provider_slug == "openai":
                group = "OpenAI"
            elif provider_slug == "black-forest-labs":
                group = "Black Forest Labs (FLUX)"
            else:
                group = provider_slug.title()

            openrouter_models.append({
                "id": model_id,
                "name": name.replace(f"{provider_slug.title()}: ", "").replace("Google: ", "").replace("OpenAI: ", "").replace("Black Forest Labs: ", ""),
                "provider": provider_slug,
                "group": group,
            })

        print(f"  ↳ Found {len(openrouter_models)} OpenRouter models from allowed providers")

    except Exception as e:
        print(f"  ⚠️ OpenRouter fetch error: {e}")

    # ─── 2. Build the final model lists ──────────────────────────
    # Google AI Studio list: curated only (OpenRouter Google models may
    # differ from what's available directly on AI Studio)
    google_models = GOOGLE_CURATED_MODELS

    # OpenRouter list: everything from allowed providers
    # Use OpenRouter's list for all providers (includes Google models too)
    or_models = openrouter_models if openrouter_models else []

    # ─── 3. Write to Firestore ───────────────────────────────────
    db = firestore.client()
    db.collection("system").document("available_models").set({
        "google": google_models,
        "openrouter": or_models,
        "updated_at": datetime.now().isoformat(),
    })

    print(f"✅ Model list updated: {len(google_models)} Google, {len(or_models)} OpenRouter")


# ─── Account: Delete ────────────────────────────────────────────

@https_fn.on_call(
    region="australia-southeast1",
    memory=options.MemoryOption.MB_512,
    timeout_sec=120,
    secrets=["STRIPE_SECRET_KEY"],
)
def delete_account(req: https_fn.CallableRequest):
    """Permanently delete a user's account and all associated data.

    Deletes:
      - All Firestore documents under users/{uid}/ (settings, characters, devices, etc.)
      - All Storage files under users/{uid}/
      - All Storage files under devices/{deviceId}/ for each user device
      - Cancels any active Stripe subscription
      - Deletes the Firebase Auth user
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required.",
        )

    uid = req.auth.uid
    db = firestore.client()
    user_ref = db.collection("users").document(uid)

    print(f"🗑️ Starting account deletion for {uid}")

    # ─── 2. Collect device IDs for storage cleanup ───────────────
    device_ids = []
    try:
        for device_doc in user_ref.collection("devices").stream():
            device_ids.append(device_doc.id)
    except Exception as e:
        print(f"  ⚠️ Error listing devices: {e}")

    # ─── 3. Delete all Firestore data recursively ────────────────
    def delete_collection(coll_ref):
        """Recursively delete all documents in a collection."""
        for doc_snap in coll_ref.stream():
            # Delete known subcollections first
            for subcol_name in ["config", "prompt", "status"]:
                delete_collection(doc_snap.reference.collection(subcol_name))
            doc_snap.reference.delete()

    # Delete subcollections
    for subcol_name in ["settings", "characters", "devices"]:
        try:
            delete_collection(user_ref.collection(subcol_name))
            print(f"  ↳ Deleted {subcol_name} collection")
        except Exception as e:
            print(f"  ⚠️ Error deleting {subcol_name}: {e}")

    # Delete the user document itself
    try:
        user_ref.delete()
        print(f"  ↳ Deleted user document")
    except Exception as e:
        print(f"  ⚠️ Error deleting user document: {e}")

    # ─── 4. Delete all Storage files ─────────────────────────────
    try:
        bucket = storage.bucket()

        # User-level storage
        blobs = list(bucket.list_blobs(prefix=f"users/{uid}/"))
        for blob in blobs:
            blob.delete()
        print(f"  ↳ Deleted {len(blobs)} user storage files")

        # Device-level storage (public display URLs)
        for device_id in device_ids:
            device_blobs = list(bucket.list_blobs(prefix=f"devices/{device_id}/"))
            for blob in device_blobs:
                blob.delete()
            if device_blobs:
                print(f"  ↳ Deleted {len(device_blobs)} device storage files for {device_id}")

    except Exception as e:
        print(f"  ⚠️ Storage cleanup error: {e}")

    # ─── 5. Delete Firebase Auth user ────────────────────────────
    try:
        admin_auth.delete_user(uid)
        print(f"  ↳ Deleted Firebase Auth user")
    except Exception as e:
        print(f"  ⚠️ Auth deletion error: {e}")

    print(f"✅ Account deletion complete for {uid}")
    return {"status": "deleted"}
