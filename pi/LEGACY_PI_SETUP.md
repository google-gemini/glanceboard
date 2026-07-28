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

# Legacy Raspberry Pi Setup Guide

> **Note:** Glanceboard now recommends the **Waveshare ESP32-S3 PhotoPainter** as the primary display hardware. This guide is for users who prefer a Raspberry Pi + separate e-ink display setup.

---

## What You Need

| Part | Description | Est. Price |
|------|-------------|------------|
| **E-Ink Display** | Waveshare 7.3" Spectra 6 (ACeP) — full color | ~$65 |
| **Raspberry Pi** | Zero 2W (or any Pi with GPIO) | ~$15 |
| **MicroSD Card** | 16GB or larger | ~$8 |
| **Battery** *(optional)* | PhotoPainter HAT + battery for cable-free | ~$25 |

---

## Step 1: Flash the SD Card

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Click **"Choose Device"** → select **Raspberry Pi Zero 2 W**
3. Click **"Choose OS"** → select **Raspberry Pi OS (other)** → **Raspberry Pi OS Lite (64-bit)**
4. Click **"Choose Storage"** → select your SD card
5. Click the **⚙️ gear icon** to configure:
   - ☑️ **Set hostname:** `glanceboard`
   - ☑️ **Set username and password** (e.g., username: `pi`)
   - ☑️ **Configure wireless LAN:** Your WiFi SSID and password
   - ☑️ **Set locale settings:** Your timezone
   - Go to **Services** → ☑️ **Enable SSH**
6. Click **Save**, then **Write**

---

## Step 2: Assemble

1. Insert the flashed SD card into the Raspberry Pi
2. Connect the e-ink display ribbon cable to the Pi's GPIO pins (or HAT connector)
3. If using a battery HAT, attach it between the Pi and display
4. Power on the Pi (plug in USB-C or connect battery)
5. Wait 2-3 minutes for first boot

---

## Step 3: Install Software

SSH into your Pi and run the one-line installer:

```bash
ssh pi@glanceboard.local
```

Then:

```bash
curl -sSL https://raw.githubusercontent.com/google-gemini/glanceboard/main/pi/install.sh | bash
```

When prompted, paste your **Display Image URL** from the Glanceboard dashboard:
- Go to **Settings** → **E-Ink Display Setup** → **📋 Copy URL**
- If running a local server, the URL will look like: `http://YOUR_SERVER_IP:8000/images/latest_display.bmp`

---

## Step 4: Verify

Your display should update within a few minutes. Check logs:

```bash
journalctl -u eink-display -f
```

---

## Troubleshooting

- **Can't find Pi on network?** Check your router's admin page for the Pi's IP, then use `ssh pi@192.168.x.x`
- **Display not updating?** Check that the Display URL is correct in `~/.glanceboard.conf`
- **Generate an image first** from the dashboard before expecting the display to show something

---

## How It Works

The Pi runs a Python script (`display_update.py`) that:
1. Polls the image URL every 5 minutes (either your local Glanceboard server or Firebase Storage)
2. Downloads the latest image when it changes (hash-based detection)
3. Pushes the image to the e-ink display via SPI

The Pi is just a display client — it fetches images from wherever your Glanceboard server is running (local server or Firebase). See the main [Self-Hosting Guide](../SELF_HOSTING.md) for setting up the server.
