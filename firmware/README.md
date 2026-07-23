# ESP32-S3 PhotoPainter — Firmware & Setup

The Waveshare ESP32-S3 PhotoPainter is a 7.3" colour e-ink display in a wooden frame with built-in WiFi. Glanceboard uses the community [esp32-photoframe](https://github.com/aitjcize/esp32-photoframe) firmware which adds URL-based image fetching over WiFi.

## Flashing the Firmware

> ⚠️ **You must flash the community firmware.** The stock Waveshare firmware does not support fetching images from URLs over WiFi.

### Requirements
- Google Chrome browser (for Web Serial API)
- USB-C cable connected to your computer
- SD card inserted in the PhotoPainter (with stock BMP files)

### Steps

1. Open the [ESP32 PhotoFrame Web Flasher](https://aitjcize.github.io/esp32-photoframe/#flash) in **Chrome**
2. Connect your PhotoPainter to your computer via USB-C
3. Put the device in flash mode:
   - Hold the **BOOT** button
   - While holding BOOT, press and release the **RESET** button
   - Release the **BOOT** button
4. In Chrome, click **Connect** → select the USB serial device (e.g. `cu.usbmodem311101`)
5. Click **Install** → wait for the flash (~2 minutes)
6. The device will reboot with the community firmware

### After Flashing

The device will create a WiFi hotspot named `PhotoFrame-XXXX`. Connect to it and open `http://192.168.4.1` to configure.

## SD Card Structure

The firmware expects these directories on the MicroSD card (FAT32):

```
/
├── 01_sys_init_img/         # Boot splash image (800x480 BMP)
├── 02_sys_ap_img/           # Image shown when in AP mode
├── 03_sys_ap_html/          # Web interface served in AP mode
├── 04_sys_ai_img/           # Stock images (must contain at least one BMP)
├── 05_user_ai_img/          # User AI images
└── 06_user_Foundation_img/  # User images + config
```

> ⚠️ **Keep the stock BMP files.** The firmware needs images in `01_sys_init_img/` and `04_sys_ai_img/` to boot. If these are missing or empty, the device may fail to start.

## WiFi Configuration

### Initial Setup (AP Mode)

1. Power on the PhotoPainter
2. Connect to WiFi: `PhotoFrame-XXXX` (password shown on screen or printed on device)
3. Open `http://192.168.4.1`
4. Enter your home WiFi credentials → Save
5. The device restarts and connects to your network

### Finding the Device on Your Network

After connecting to your home WiFi, the device is accessible at:
- `http://photoframe.local` (mDNS)
- Or check your router's DHCP client list for the device IP

### Configuring Glanceboard Image URL

1. Open the device's web interface (e.g. `http://192.168.68.80`)
2. Go to **Settings** → **Auto Rotate**
3. Set **Rotation Mode** → `url`
4. Paste your Glanceboard display URL:
   ```
   https://firebasestorage.googleapis.com/v0/b/{project}/o/users%2F{uid}%2Fdevices%2Fdefault%2Fdisplay%2Flatest_display.png?alt=media
   ```
   > Find this URL in the Glanceboard dashboard: **Settings → E-Ink Display Setup → Copy URL**
5. Set **Auto Rotate** → **On**
6. Set **Interval** → `300` (seconds, = 5 minutes)
7. Set **Deep Sleep** → **Off**
8. Click **Save**

## Configuration via API

The device has a REST API for programmatic configuration:

```bash
# Read current config
curl http://192.168.68.80/api/config

# Update config
curl -X POST http://192.168.68.80/api/config \
  -H 'Content-Type: application/json' \
  -d '{
    "rotation_mode": "url",
    "image_url": "https://firebasestorage.googleapis.com/...",
    "rotate_interval": 300,
    "deep_sleep_enabled": false,
    "auto_rotate": true
  }'

# Trigger immediate image refresh
curl -X POST http://192.168.68.80/api/rotate
```

## Troubleshooting

### Device won't boot (red blinking LED)
- Make sure the SD card has stock BMP files in `01_sys_init_img/` and `04_sys_ai_img/`
- Re-flash the firmware

### Display stuck on "Setup complete"
- The image URL may be wrong — check it returns HTTP 200:
  ```bash
  curl -o /dev/null -w "%{http_code}" "YOUR_IMAGE_URL"
  ```
- Trigger a manual rotation: `curl -X POST http://DEVICE_IP/api/rotate`

### Can't find device on network
- Try `http://photoframe.local` or check your router's DHCP list
- The device may be in deep sleep — press the BOOT button to wake it

### Image looks wrong / stretched
- Glanceboard generates 800×480 images which match the PhotoPainter's native resolution
- If stretched, check the display orientation in the device's web interface
