#!/usr/bin/env python3
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
E-Ink Display Updater — runs on the Raspberry Pi Zero 2W.

Fetches the latest calendar art from Firebase Storage and renders it
on the Waveshare 7.3" E6 Full Color E-Paper display (PhotoPainter ACCE).

Modes:
  1. Polling (default):  Runs continuously, checking every POLL_INTERVAL seconds.
  2. One-shot (--once):  Fetches image, updates display, then shuts down the Pi
                         to save battery. Pair with a systemd timer or cron for
                         scheduled wake-update-shutdown cycles.
  3. One-shot dry run (--once-no-halt): Same as --once but doesn't halt the Pi.

Features:
  - Hash-based change detection (only refreshes when image changes)
  - Graceful error handling with retry
  - Clean shutdown on SIGINT/SIGTERM
  - Battery-saving shutdown mode for e-ink displays
  - Configurable via environment variables

Usage:
    python3 display_update.py              # Continuous polling mode
    python3 display_update.py --once       # Update once, then shutdown Pi
    python3 display_update.py --once-no-halt  # Update once, no shutdown (testing)

Environment variables:
    EINK_SERVER_URL    - URL to fetch latest_display.png (required)
    EINK_POLL_INTERVAL - Seconds between polls (default: 300 = 5 min)
    EINK_HASH_FILE     - Path to store last image hash (default: /tmp/eink_last_hash.txt)
"""
import hashlib
import io
import struct
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
import logging
from datetime import datetime

# Boot grace period — don't halt within this many seconds of boot
# so you can always SSH in after a reboot, even on battery
BOOT_GRACE_SECONDS = int(os.environ.get("EINK_BOOT_GRACE", "600"))  # 10 minutes

from PIL import Image

# ─── Configuration ───────────────────────────────────────────────

SERVER_URL = os.environ.get(
    "EINK_SERVER_URL",
    "http://192.168.68.52:8080/latest_display.png"
)
POLL_INTERVAL = int(os.environ.get("EINK_POLL_INTERVAL", "300"))
HASH_FILE = os.environ.get("EINK_HASH_FILE", "/tmp/eink_last_hash.txt")

# Display dimensions (Waveshare 7.3" E6 = 800×480)
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

# ─── Logging ─────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("eink-updater")

# ─── Graceful Shutdown ──────────────────────────────────────────

_running = True


def _shutdown(signum, frame):
    global _running
    log.info(f"Received signal {signum}, shutting down gracefully...")
    _running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# ─── Display Driver ─────────────────────────────────────────────

# Try importing the Waveshare driver. If we're on a non-Pi machine
# (e.g. testing on the Mac), we fall back to a stub.
try:
    # Use the PhotoPainter ACCE driver — it has the correct PWR_PIN (GPIO 27)
    # The standard e-Paper HAT driver uses PWR_PIN=18, which doesn't work
    # with the PhotoPainter hat.
    sys.path.insert(0, os.path.expanduser(
        "~/RPi_Zero_PhotoPainter/Waveshare_E-Paper/lib"
    ))
    from waveshare_epd import epd7in3e
    DRIVER_AVAILABLE = True
    log.info("Waveshare epd7in3e driver loaded successfully")
except ImportError:
    DRIVER_AVAILABLE = False
    log.warning(
        "Waveshare driver not found — running in dry-run mode "
        "(image will be fetched but not displayed)"
    )

# ─── Battery Monitor ────────────────────────────────────────────

try:
    import smbus2
    BATTERY_AVAILABLE = True
except ImportError:
    BATTERY_AVAILABLE = False
    log.warning("smbus2 not available — battery monitoring disabled")


def read_battery():
    """
    Read battery level from the INA219 power monitor on the PhotoPainter hat.

    Returns (voltage, percentage, current_ma) or (None, None, None) on failure.
    The INA219 is at I2C address 0x43.
    Battery range: 3.0V (empty) to 4.2V (full).

    Current is positive when discharging (on battery), negative when charging (USB power).
    """
    if not BATTERY_AVAILABLE:
        return None, None, None

    try:
        bus = smbus2.SMBus(1)
        addr = 0x43

        # Calibrate: 16V range, 0.01 ohm shunt
        cal = 26868
        bus.write_i2c_block_data(addr, 0x05, [(cal >> 8) & 0xFF, cal & 0xFF])
        config = (0x00 << 13) | (0x01 << 11) | (0x0D << 7) | (0x0D << 3) | 0x07
        bus.write_i2c_block_data(addr, 0x00, [(config >> 8) & 0xFF, config & 0xFF])

        import time as _t
        _t.sleep(0.1)

        # Re-write calibration (needed for current reading)
        bus.write_i2c_block_data(addr, 0x05, [(cal >> 8) & 0xFF, cal & 0xFF])

        # Read bus voltage (register 0x02)
        data = bus.read_i2c_block_data(addr, 0x02, 2)
        raw = (data[0] << 8 | data[1]) >> 3
        voltage = raw * 0.004

        # Read current (register 0x04) — signed 16-bit
        data = bus.read_i2c_block_data(addr, 0x04, 2)
        raw_current = data[0] << 8 | data[1]
        if raw_current > 32767:
            raw_current -= 65536  # Convert to signed
        current_ma = raw_current * 0.1  # Scale depends on calibration

        # Percentage: 3.0V = 0%, 4.2V = 100%
        pct = (voltage - 3.0) / 1.2 * 100
        pct = max(0.0, min(100.0, pct))

        bus.close()
        return voltage, pct, current_ma

    except Exception as e:
        log.warning(f"Battery read failed: {e}")
        return None, None, None


def is_on_battery():
    """Detect whether the Pi is running on battery or USB power.

    Returns True if on battery, False if on USB power.

    Detection logic:
    - If battery monitor isn't available (no INA219) → assume USB power (False)
    - If battery voltage > 4.15V → charging, so USB power (False)
    - If current is negative → charging, so USB power (False)
    - Otherwise → on battery (True)
    """
    voltage, pct, current_ma = read_battery()

    if voltage is None:
        # No battery monitor = probably plugged into USB with no battery
        log.info("No battery detected — assuming USB power")
        return False

    log.info(f"Battery: {pct:.0f}% ({voltage:.2f}V, {current_ma:.0f}mA)")

    # Charging indicators: voltage above fully-charged threshold,
    # or current is negative (flowing into battery)
    if voltage > 4.15:
        log.info("Battery voltage > 4.15V — USB power detected (charging)")
        return False

    if current_ma is not None and current_ma < -10:
        log.info(f"Negative current ({current_ma:.0f}mA) — USB power detected (charging)")
        return False

    log.info("Running on battery power")
    return True


def draw_battery_indicator(image, pct):
    """
    Draw a battery indicator on the bottom-right of the image.

    Always shows the battery icon, but uses color to indicate level:
      - Green fill when > 50%
      - Yellow fill when 20-50%
      - Red fill when < 20%
      - Red outline + empty when critically low (< 5%)
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)

    # Battery icon dimensions (bottom-right corner)
    bw, bh = 40, 20          # body width/height
    nub_w, nub_h = 4, 10     # positive terminal nub
    margin = 10
    x = image.width - bw - nub_w - margin
    y = image.height - bh - margin

    # Colors (from e-ink palette)
    black = (0, 0, 0)
    white = (255, 255, 255)
    red = (200, 30, 30)
    green = (0, 128, 0)
    yellow = (230, 200, 0)

    # Choose fill color by level
    if pct > 50:
        fill_color = green
    elif pct > 20:
        fill_color = yellow
    else:
        fill_color = red

    # White background behind the icon
    draw.rectangle([x - 3, y - 3, x + bw + nub_w + 3, y + bh + 3], fill=white)

    # Battery body outline
    draw.rectangle([x, y, x + bw, y + bh], outline=black, width=2)

    # Positive terminal nub
    nub_y = y + (bh - nub_h) // 2
    draw.rectangle([x + bw, nub_y, x + bw + nub_w, nub_y + nub_h], fill=black)

    # Fill level
    fill_width = int((bw - 4) * pct / 100)
    if fill_width > 0:
        draw.rectangle([x + 2, y + 2, x + 2 + fill_width, y + bh - 2], fill=fill_color)

    return image


# ─── Helper Functions ───────────────────────────────────────────


def get_last_hash():
    """Read the MD5 hash of the last displayed image from disk."""
    try:
        with open(HASH_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def save_hash(h):
    """Persist the MD5 hash of the current image."""
    with open(HASH_FILE, "w") as f:
        f.write(h)


def fetch_image():
    """
    Download the latest display image from the Mac Studio.

    Returns the raw image bytes, or None on failure.
    """
    try:
        req = urllib.request.Request(SERVER_URL)
        response = urllib.request.urlopen(req, timeout=15)
        return response.read()
    except urllib.error.URLError as e:
        log.error(f"Network error fetching image: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching image: {e}")
        return None


def update_display(image_data):
    """
    Render the image on the Waveshare 7.3" E6 e-ink display.

    The image is resized to fit the display (800×480) and then
    pushed to the e-paper panel via SPI.
    """
    image = Image.open(io.BytesIO(image_data))
    image = image.resize((DISPLAY_WIDTH, DISPLAY_HEIGHT), Image.LANCZOS)

    # Overlay battery indicator only when critically low
    voltage, pct, _ = read_battery()
    if pct is not None:
        log.info(f"Battery: {pct:.0f}% ({voltage:.2f}V)")
        if pct < 5:
            image = draw_battery_indicator(image, pct)
    else:
        log.info("Battery: unavailable")

    if not DRIVER_AVAILABLE:
        log.info(
            f"[DRY RUN] Would display image "
            f"({image.size[0]}×{image.size[1]})"
        )
        return True

    epd = None
    try:
        epd = epd7in3e.EPD()
        epd.init()
        log.info("Display initialized, pushing image...")

        epd.display(epd.getbuffer(image))
        log.info("Image rendered on display")

        epd.sleep()
        log.info("Display entered sleep mode")
        return True

    except Exception as e:
        log.error(f"Display error: {e}")
        if epd:
            try:
                epd.sleep()
            except Exception:
                pass
        return False


def get_uptime_seconds():
    """Read system uptime from /proc/uptime."""
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.readline().split()[0])
    except Exception:
        return 9999  # Assume long uptime if can't read


def run_once(halt="auto"):
    """Fetch the latest image, update the display, then decide whether to halt.

    halt modes:
      - "auto":  Check power source. On battery → shutdown. On USB → stay running
                  in continuous polling mode (so you can SSH in).
      - True:    Always shutdown after update.
      - False:   Never shutdown (testing/dry-run).

    Boot grace period: The Pi will NOT halt within BOOT_GRACE_SECONDS (default
    10 minutes) of booting, even on battery. This ensures you can always SSH
    in after a reboot to debug or reconfigure.
    """
    log.info("=" * 50)
    log.info("E-Ink Display — One-Shot Update")
    log.info(f"   Server:  {SERVER_URL}")
    log.info(f"   Display: {DISPLAY_WIDTH}x{DISPLAY_HEIGHT}")
    log.info("=" * 50)

    # Check boot grace period
    uptime = get_uptime_seconds()
    in_grace_period = uptime < BOOT_GRACE_SECONDS
    if in_grace_period:
        remaining = int(BOOT_GRACE_SECONDS - uptime)
        log.info(f"⏳ Boot grace period active — {remaining}s remaining (won't halt)")

    # Detect power source
    on_battery = is_on_battery()

    if halt == "auto":
        should_halt = on_battery and not in_grace_period
        if on_battery and in_grace_period:
            log.info("On battery but within boot grace period — staying on for SSH")
        elif on_battery:
            log.info("On battery — will shutdown after update to save power")
        else:
            log.info("On USB power — will stay running for SSH access")
    else:
        should_halt = halt and not in_grace_period

    # Fetch image
    log.info("Fetching image...")
    image_data = fetch_image()
    if image_data is None:
        log.error("Could not fetch image. Will try again next wake cycle.")
        if should_halt:
            log.info("Shutting down Pi in 10 seconds...")
            time.sleep(10)
            subprocess.run(["sudo", "shutdown", "-h", "now"])
        return

    # Check if image has changed
    current_hash = hashlib.md5(image_data).hexdigest()
    last_hash = get_last_hash()

    if current_hash != last_hash:
        log.info("New image detected, updating display...")
        success = update_display(image_data)
        if success:
            save_hash(current_hash)
            log.info("Display updated successfully!")
        else:
            log.error("Display update failed.")
    else:
        log.info("Image unchanged — display is already current.")

    if should_halt:
        log.info("On battery — shutting down Pi to save power...")
        time.sleep(5)  # Brief pause for logs to flush
        subprocess.run(["sudo", "shutdown", "-h", "now"])
    elif on_battery is False:
        # On USB power — fall through to continuous polling
        log.info("On USB power — switching to continuous polling mode")
        main()
    elif in_grace_period:
        # On battery but in grace period — wait then re-check
        log.info(f"Grace period: waiting {remaining}s then will re-evaluate...")
        _sleep(remaining)
        run_once(halt=halt)  # Re-run after grace period expires
    else:
        log.info("Done. Exiting.")


# ─── Main Loop ──────────────────────────────────────────────────


def main():
    log.info("=" * 50)
    log.info("E-Ink Calendar Display Updater")
    log.info(f"   Server:   {SERVER_URL}")
    log.info(f"   Interval: {POLL_INTERVAL}s")
    log.info(f"   Display:  {DISPLAY_WIDTH}x{DISPLAY_HEIGHT}")
    log.info(f"   Driver:   {'loaded' if DRIVER_AVAILABLE else 'DRY RUN'}")
    log.info("=" * 50)

    if "YOUR-MAC-IP" in SERVER_URL:
        log.error(
            "SERVER_URL still has placeholder! "
            "Set EINK_SERVER_URL environment variable or edit this script."
        )
        sys.exit(1)

    # Initial display update on startup (always refresh once)
    first_run = True

    while _running:
        try:
            log.info("Fetching image from server...")
            image_data = fetch_image()

            if image_data is None:
                log.warning(
                    f"Could not fetch image. Retrying in {POLL_INTERVAL}s..."
                )
                _sleep(POLL_INTERVAL)
                continue

            current_hash = hashlib.md5(image_data).hexdigest()
            last_hash = get_last_hash()

            if current_hash != last_hash or first_run:
                reason = "first run" if first_run else "image changed"
                log.info(f"Updating display ({reason})...")

                success = update_display(image_data)
                if success:
                    save_hash(current_hash)
                    log.info("Display updated successfully!")
                    first_run = False
                else:
                    log.error("Display update failed, will retry next cycle")
            else:
                log.info("No change detected, display is current")

        except Exception as e:
            log.error(f"Unexpected error in main loop: {e}")

        log.info(f"Sleeping {POLL_INTERVAL}s until next check...")
        _sleep(POLL_INTERVAL)

    log.info("Updater stopped.")


def _sleep(seconds):
    """Interruptible sleep — breaks early if _running becomes False."""
    end = time.time() + seconds
    while _running and time.time() < end:
        time.sleep(1)


if __name__ == "__main__":
    if "--once" in sys.argv:
        # Auto-detect: shutdown on battery, stay running on USB
        run_once(halt="auto")
    elif "--once-halt" in sys.argv:
        # Force shutdown after update (even on USB power)
        run_once(halt=True)
    elif "--once-no-halt" in sys.argv:
        # Never shutdown (for testing)
        run_once(halt=False)
    else:
        # Default: continuous polling
        main()


