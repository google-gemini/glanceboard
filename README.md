# Glanceboard

**A daily calendar your kids actually look at.**

Glanceboard turns your Google Calendar into generated art on an e-ink display. No screens. No notifications. Just a quiet picture frame that helps your family know what's happening today.

![Glanceboard on an e-ink display](web/public/display.jpg)

---

## Why I built this

I wanted to empower my kids to be more independent in the mornings — to know what's on today, what to pack in their bags, what to wear without asking and without giving them a screen to check.

I couldn't find anything that did this well, so I built Glanceboard. It reads our family calendar and generates a new illustrated scene every morning with the day's events, weather, and our characters on it.

My kids love it. They get excited every morning to see what the picture looks like and read what's coming up. It's become part of our routine.

It uses AI image generation, so sometimes the pictures do weird things. The kids think that's funny. So do I.

---

## How to get started

Glanceboard is self-hosted — you deploy it to your own Firebase project (or equivalent). Here's the [self-hosting guide](SELF_HOSTING.md).

---

## What you need

Just one piece of hardware — the display:

| Part | Description | Price |
|------|-------------|-------|
| [**Waveshare ESP32-S3 PhotoPainter**](https://link.amazon/B09xTtvBa) | 7.3" colour e-ink display in a wooden frame with built-in WiFi | ~$90 |
| **USB-C cable** | For power (or use an optional lithium battery) | ~$5 |

No Raspberry Pi. No soldering. No ribbon cables. Just one device.

> **Using a Raspberry Pi?** The legacy Pi + separate display setup is still supported — see [Legacy Pi Setup](pi/LEGACY_PI_SETUP.md).

---

## Features

- **AI-generated daily art** — Your calendar events become illustrated daily planners
- **Two art styles** — Whimsical pen-and-ink or elegant fashion sketch
- **Custom characters** — Add people and pets with reference photos for consistency
- **Google Calendar** — One-click OAuth connection (iCal URL fallback available)
- **Weather-aware** — Shows weather on the display; characters dress for the actual conditions
- **Location-aware** — Uses your location to generate regionally accurate scenes (no snow in Sydney!)
- **Smart countdowns** — AI scans your calendar for birthdays, trips, and holidays to count down to
- **Gemini-powered event rewriting** — Turns "9am Tavi Library Bag" into "Tavi — remember library bag!"
- **📧 Email Scanner** — Scans your Gmail for school newsletters, sports updates, etc. and auto-adds events you missed to your calendar (powered by Gemini 3.5 Flash)
- **E-ink ready** — Floyd-Steinberg dithered for 6-colour Spectra panels
- **Multi-user** — Each person gets their own account, settings, and display
- **Smart scheduling** — Auto-generates at your chosen times, only when your calendar or weather changes
- **Account management** — Pause generation anytime or delete your account and all data
- **Custom prompts** — Edit the image generation prompt template

---

## Suggested models

Glanceboard works with a range of AI image generation models. Here's what we've tested and recommend:

| Model | Provider | Est. Cost/Image | Notes |
|-------|----------|-----------------|-------|
| **Gemini 3 Pro** | Google AI Studio | ~$0.04 | **Recommended.** Best quality, great text rendering and character consistency. |
| **Gemini 3.1 Flash Lite** | Google AI Studio | ~$0.01 | Fast and cheap. Good for frequent refreshes on a budget. |

Glanceboard also uses **Gemini 3.1 Flash Lite** (essentially free) for text intelligence:
- Rewriting calendar events into friendly language
- Generating weather-accurate scene descriptions
- Scanning calendars for important upcoming events

And **Gemini 3.5 Flash** for the email scanner:
- Extracting calendar events from email subjects and snippets
- Smart deduplication against your existing calendar

---

## API key setup

Glanceboard needs a **Google AI Studio API key** to generate images. This is the only ongoing cost (~$1–3/month).

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Click **Create API Key** → select your Google Cloud project (or create one)
3. Copy the key (starts with `AIza...`)
4. Paste it into the Glanceboard dashboard during onboarding (Step 2: "AI Image Generation"), or later in **Settings → AI Image Generation → API Key**

> **That's it.** The key is stored securely in your Firestore database and used server-side to call the Gemini API. You are billed directly by Google for API usage.

---

## Display setup guide

### Step 1: Flash the Glanceboard firmware

The PhotoPainter ships with stock firmware. You need to flash the Glanceboard firmware to enable QR code setup and automatic image polling.

1. Connect your PhotoPainter to your computer via USB-C
2. Hold the **BOOT** button, then press **RESET** while holding BOOT — release both
3. Download the latest `merged.bin` from [Releases](https://github.com/raphdixon/glanceboard-firmware/releases)
4. Flash using [esptool](https://docs.espressif.com/projects/esptool/en/latest/):
   ```bash
   python3 -m esptool --chip esp32s3 --port /dev/cu.usbmodem* --baud 921600 write_flash 0x0 merged.bin
   ```
5. The device will reboot and show the Glanceboard setup screen

> **Important:** Keep the SD card inserted — the firmware needs certain system files to boot properly.

### Step 2: Connect to WiFi (scan QR code)

1. Power on the PhotoPainter — the Glanceboard setup screen appears
2. On your phone, scan the **left QR code** ("Scan to connect WiFi")
3. Your phone connects to the Glanceboard's WiFi hotspot
4. A captive portal opens — enter your home WiFi network and password
5. The device connects and shows a "Ready!" screen

### Step 3: Set up your board (scan QR code)

1. Scan the **right QR code** on the "Ready!" screen (or the link shown)
2. This opens your Glanceboard dashboard (your Firebase Hosting URL) with your device pre-registered
3. Sign in with Google or create an account
4. Follow the onboarding wizard:
   - **AI Image Generation** — Enter your Google AI Studio API key (get one free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey))
   - **Google Calendar** — Connect your family calendar
   - **Location** — Set your timezone and location for weather
   - **Art Style** — Choose whimsical or fashion sketch
   - **Characters** — Add your kids, pets, anyone
5. Click **Generate Now** — your first image appears on the display within ~30 seconds

### Factory Reset

If you need to start fresh (e.g. change WiFi, transfer to a new owner):
- **Hold the BOOT button for 10 seconds** — the device wipes all settings and reboots to the setup screen
- Alternatively, access the device's web interface and use `POST /api/factory-reset`

---

## Architecture

```
Server (Firebase or self-hosted)
──────────────────────────────────────────────────────
  Auth (Google + Email)     Secret Manager
                            GOOGLE_CLIENT_ID/SECRET

  Firestore                    Storage
  users/{uid}/settings/...     users/{uid}/devices/{id}/display/
  users/{uid}/characters/...   users/{uid}/devices/{id}/archive/
  users/{uid}/devices/...      devices/{id}/display/ ← ESP32 polls here

   Cloud Functions (Python 3.11)
   ├── generate_display      (on-demand, 3/day limit)
   ├── scheduled_generate    (cron, generates at user-chosen times)
   ├── create_device         (auto-register from QR code)
   ├── exchange_calendar_code  (OAuth for Calendar)
  └── delete_account          (full account deletion)

  Hosting: Vite SPA (dashboard + onboarding)
──────────────────────────────────────────────────────
         │                              │
         ▼                              ▼
  ESP32-S3 PhotoPainter         AI Provider
  QR code → WiFi setup          Google AI Studio
  polls devices/{MAC}/display   (Gemini Flash / Pro)
  updates e-ink
  Factory reset: BOOT 10s

  Gemini 3.1 Flash Lite
  • Rewrites calendar events in friendly text
  • Generates weather-accurate scene prompts
  • Scans calendar for important countdowns
```

---

## Self-hosting

See the full [Self-Hosting Guide](SELF_HOSTING.md) for step-by-step instructions.

Glanceboard was built on Firebase, but the codebase is straightforward Python + a Vite SPA — you could quite easily adapt it to run locally or on any cloud platform. The Cloud Functions are just Flask endpoints, and the frontend is static HTML/JS.

**Overview:**
1. Create a Firebase project (Blaze plan — generous free tier covers most usage)
2. Enable Auth, Firestore, Storage, Cloud Functions
3. Set up Google Calendar OAuth credentials
4. Get a [Google AI Studio API key](https://aistudio.google.com/apikey) for image generation
5. Copy `web/src/config.example.js` to `web/src/config.js` with your values
6. Deploy: `firebase deploy`
7. Flash and set up your PhotoPainter display (see [Display setup guide](#display-setup-guide))

**Estimated cost:** ~$1–3/month (just the AI image generation API). Firebase free tier covers everything else.

---

## Project structure

```
glanceboard/
├── web/                    # Frontend (Vite SPA)
│   ├── index.html          # Dashboard + landing page
│   └── src/
│       ├── main.js         # App logic
│       ├── style.css       # Styles
│       ├── config.js       # Your config (gitignored)
│       └── config.example.js # Template config
├── functions/              # Cloud Functions (Python)
│   ├── main.py             # All backend logic
│   └── requirements.txt    # Python dependencies
├── firmware/               # ESP32-S3 PhotoPainter docs
│   └── README.md           # SD card & firmware setup
├── pi/                     # Legacy Raspberry Pi scripts
│   ├── LEGACY_PI_SETUP.md  # Pi setup guide
│   ├── install.sh          # One-line installer
│   └── display_update.py   # Display update script
├── firestore.rules         # Firestore security rules
├── storage.rules           # Storage security rules
├── firebase.json           # Firebase config
├── SELF_HOSTING.md         # Self-hosting guide
└── LICENSE                 # CC BY-NC 4.0
```

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-thing`)
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

---

## License

[CC BY-NC 4.0](LICENSE) — free to use, fork, and modify for non-commercial purposes. For commercial licensing, contact the author.

---

Built with ❤️ by [Raph Dixon](https://raph.plus).
