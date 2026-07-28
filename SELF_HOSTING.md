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

# Self-Hosting Guide

Run Glanceboard on your own server — a Raspberry Pi, old laptop, or any always-on machine on your home network. No cloud, no subscription, no Firebase.

---

## Quick version

If you've already followed the [Quick Start](README.md#quick-start) and have Glanceboard running, you just need to keep it running permanently:

```bash
# From the project root
cd server
source venv/bin/activate
nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 &
```

That's it. But read on for a proper setup that survives reboots.

---

## Full setup

### 1. Clone and install

```bash
git clone https://github.com/google-gemini/glanceboard.git
cd glanceboard

# Server
cd server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# Dashboard
cd web
npm install
npm run build
cd ..
```

### 2. Run the setup wizard

Start the server once to configure it:

```bash
cd server
source venv/bin/activate
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://<your-server-ip>:8000` and complete the onboarding:

- **API key** — Get one free from [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **Calendar** — Paste your iCal URL ([how to find it](#finding-your-ical-url))
- **Location** — Set your timezone and location for weather
- **Art style** — Choose your preferred style
- **Characters** — Add your family (optional)

Press `Ctrl+C` to stop the server once you're done configuring.

### 3. Keep it running (systemd)

Create a systemd service so it starts on boot and restarts if it crashes:

```bash
sudo tee /etc/systemd/system/glanceboard.service > /dev/null << 'EOF'
[Unit]
Description=Glanceboard Server
Documentation=https://github.com/google-gemini/glanceboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/glanceboard/server
ExecStart=/home/$USER/glanceboard/server/venv/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=glanceboard

[Install]
WantedBy=multi-user.target
EOF
```

> **Note:** Edit the paths above if you cloned Glanceboard somewhere other than your home directory.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable glanceboard
sudo systemctl start glanceboard
```

Check it's running:

```bash
sudo systemctl status glanceboard
```

View logs:

```bash
journalctl -u glanceboard -f
```

### 4. Connect your display

Your e-ink display needs to fetch images from your server over your local network.

1. Find your server's local IP: `hostname -I` (e.g. `192.168.1.50`)
2. In the Glanceboard dashboard, go to **Settings → E-Ink Display Setup → 📋 Copy URL**
3. On your PhotoPainter's web interface (see [display setup](README.md#display-setup-guide)):
   - Set **Rotation Mode** → `url`
   - Paste the display URL (it will look like `http://192.168.1.50:8000/images/latest_display.bmp`)
   - Set **Interval** → `300` (5 minutes)
   - Enable **Auto Rotate**

> **Using a Pi as the display too?** See [Legacy Pi Setup](pi/LEGACY_PI_SETUP.md) — just use your local server URL instead of a Firebase URL.

---

## Raspberry Pi as the server

A Raspberry Pi 4 or Pi 5 works great as a dedicated Glanceboard server. A Pi Zero 2W works too but image generation API calls may be slower.

### Pi-specific tips

- **Use Raspberry Pi OS Lite (64-bit)** — you don't need a desktop environment
- **Set a static IP** on your router so the display URL doesn't change
- **Python version:** Pi OS Bookworm ships with Python 3.11, which is perfect
- **Node.js:** Install Node 18+ via [NodeSource](https://github.com/nodesource/distributions):
  ```bash
  curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
  sudo apt-get install -y nodejs
  ```

### One-line install for Pi

SSH into your Pi and run:

```bash
git clone https://github.com/google-gemini/glanceboard.git
cd glanceboard
cd server && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && cd ..
cd web && npm install && npm run build && cd ..
```

Then set up the systemd service as described in [Step 3](#3-keep-it-running-systemd) above.

---

## Updating

```bash
cd ~/glanceboard
git pull
cd server && source venv/bin/activate && pip install -r requirements.txt && cd ..
cd web && npm install && npm run build && cd ..
sudo systemctl restart glanceboard
```

---

## Finding your iCal URL

### Google Calendar
1. Open [Google Calendar](https://calendar.google.com) on desktop
2. Click the ⋮ menu next to your calendar → **Settings and sharing**
3. Scroll to **Integrate calendar** → copy **Secret address in iCal format**

### Apple Calendar (iCloud)
1. Go to [icloud.com/calendar](https://www.icloud.com/calendar)
2. Click the share icon next to a calendar → enable **Public Calendar**
3. Copy the URL

### Outlook / Microsoft 365
1. Go to [Outlook Calendar](https://outlook.live.com/calendar) on the web
2. Click ⚙️ → **View all Outlook settings** → **Calendar** → **Shared calendars**
3. Under **Publish a calendar**, select your calendar → **ICS** → copy the link

---

## Troubleshooting

### Server won't start
- Check Python version: `python3 --version` (need 3.9+)
- Check you're in the `server/` directory
- Check the venv is activated: `source venv/bin/activate`
- Check logs: `journalctl -u glanceboard -f`

### Dashboard shows but images don't generate
- Check your API key is set in the dashboard
- Check your calendar URL is valid (paste it in a browser — it should download an `.ics` file)
- Try clicking **Generate Now** in the dashboard to see the error

### Display not updating
- Make sure the display can reach your server: `curl http://YOUR_SERVER_IP:8000/images/latest_display.bmp` from another device
- Check the URL in the PhotoPainter settings matches your server IP
- Your server and display must be on the same local network

### Port 8000 already in use
Set a different port:
```bash
python3 -m uvicorn app:app --host 0.0.0.0 --port 9000
```
Update the systemd service and display URL accordingly.

---

## Network notes

- The server binds to `0.0.0.0:8000` — accessible to all devices on your local network
- The e-ink display polls the server every few minutes for new images
- All AI generation happens via API calls to the Gemini API — only your API key leaves your network
- No data is stored in the cloud — everything stays on your server in `server/data/`
