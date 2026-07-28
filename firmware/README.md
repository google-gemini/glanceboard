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

# ESP32-S3 PhotoPainter — Firmware & Setup

The Waveshare ESP32-S3 PhotoPainter is a 7.3" colour e-ink display in a wooden frame with built-in WiFi. Glanceboard uses [custom firmware](https://github.com/google-gemini/glanceboard-firmware) that handles WiFi setup, image fetching, and display rendering — no SD card or manual configuration needed.

## Flashing the Firmware

> ⚠️ **You must flash the Glanceboard firmware.** The stock Waveshare firmware does not support automatic image fetching from a URL.

### Requirements
- **Google Chrome or Microsoft Edge** (Web Serial API required)
- **USB-C cable** connected to your computer

### Steps

1. Open the [Glanceboard Web Flasher](https://raphdixon.github.io/glanceboard-firmware/) in **Chrome or Edge**
2. Connect your PhotoPainter to your computer via USB-C
3. Click **Install Glanceboard Firmware** and select the USB serial device
4. Wait for the flash to complete (~2 minutes)
5. Unplug and replug the USB-C cable to reboot

## WiFi Setup & Configuration

After flashing, the device handles everything through a single setup flow:

### Initial Setup

1. **Power on** the PhotoPainter — the e-ink display shows a setup screen with the WiFi name `Glanceboard-XXXX`
2. On your phone or computer, **connect to the `Glanceboard-XXXX` WiFi network** (no password needed)
3. A captive portal page opens automatically (or navigate to `http://192.168.4.1`)
4. Enter your **WiFi network name** and **password** (leave password blank for open networks)
5. Paste the **Display Image URL** from your Glanceboard dashboard:
   - Found in **Settings → E-Ink Display Setup → 📋 Copy URL**
   - Looks like: `http://YOUR_SERVER_IP:8000/images/latest_display.bmp`
6. Choose a **poll interval** (how often the display checks for new images)
7. Click **Save & Connect**

The device restarts, connects to your WiFi, and begins polling for images. The display updates within ~60 seconds.

### After Setup

- The display shows an **"Online"** screen with the device's IP address
- Access the device's IP in any browser on the same network to update settings
- The device automatically fetches new images at the configured interval

### Factory Reset

Hold the **BOOT** button for 10 seconds to reset all settings. The device will restart in setup mode.

## Troubleshooting

### Display stays black after flashing
- Unplug and replug the USB-C cable — e-paper displays retain their old image until the firmware boots and refreshes

### Can't connect to Glanceboard-XXXX WiFi
- Make sure the device has been flashed with the Glanceboard firmware
- Try unplugging and replugging the device
- The setup WiFi network may take 10-15 seconds to appear after boot

### Display shows "WiFi connect failed"
- Double-check your WiFi credentials
- Make sure the device is within range of your WiFi router
- Hold the BOOT button for 10 seconds to factory reset and try again

### Image not updating
- Check that the image URL is correct and accessible from the device's network
- Verify the Glanceboard server is running
- Check the poll interval setting
