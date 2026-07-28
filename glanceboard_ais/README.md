<!--
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the Apache License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Glanceboard AIS

**Your calendar, illustrated daily by AI — runs entirely in the browser**

Glanceboard AIS is a single-file web app that transforms your Google Calendar into beautiful AI-generated illustrated daily planners. No server needed — just open the file, enter your API key, and go.

## Features
- Daily Gemini-generated calendar art (Nano Banana / Gemini image models)
- 6 art styles: pen-and-ink, fashion sketch, watercolour, pixel art, comic book, Japanese sumi-e
- Custom characters with reference photos
- Drag-and-drop widget layout editor (calendar, weather, sports, stocks, news, quotes, history, countdown)
- Google Calendar via iCal URL
- Weather-aware (Open-Meteo API, no key needed)
- Smart scheduling with auto-generation
- Floyd-Steinberg dithering for e-ink displays
- All settings saved to localStorage
- Export/import config for backup
- Zero dependencies — runs entirely client-side

## Quick Start
1. Open index.html in your browser (or upload to Google AI Studio)
2. Enter your Gemini API key
3. Paste your iCal calendar URL
4. Set your location for weather
5. Click Generate!

## Getting an API Key
1. Go to aistudio.google.com/apikey
2. Click Create API Key
3. Copy it and paste into Glanceboard

## Getting Your Calendar URL
- Google Calendar: Settings → your calendar → 'Secret address in iCal format'
- Outlook: Calendar settings → Shared Calendars → Publish → ICS link
- Apple Calendar: Right-click calendar → Share → Public Calendar

## Using with Google AI Studio
1. Upload index.html to a new AI Studio project
2. The app runs entirely in the browser
3. Settings persist via localStorage

## Using with an E-Ink Display
If you have a Waveshare ESP32-S3 PhotoPainter, you can set it up to display your Glanceboard:
1. Flash your device with the custom firmware using the [Glanceboard Web Flasher](https://raphdixon.github.io/glanceboard-firmware/) in Chrome or Edge.
2. Connect the display to your WiFi.
3. Configure it to fetch your image via URL, or manually generate an image in the dashboard, click 'Download for E-Ink' to get the dithered version, and upload to your display.

## Architecture
Everything runs client-side:
- iCal parsing: JavaScript
- Weather: Open-Meteo API (free, CORS-friendly)
- AI: Direct Gemini API calls from browser
- Image processing: Canvas API + Floyd-Steinberg dithering
- Storage: localStorage

## Differences from Glanceboard
- No Python server needed
- No Firebase/Firestore
- No background scheduler (uses browser setInterval)
- Email widget not supported (requires server-side OAuth)
- Character images stored as base64 in localStorage

## License
Apache 2.0 — see LICENSE file

Built with ❤️ using Gemini
