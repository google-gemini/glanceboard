#!/bin/bash
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

# ─────────────────────────────────────────────────────────────────
# Pi Setup Script — run this on the Raspberry Pi after first boot
#
# Usage:
#   scp pi/setup_pi.sh pi@eink-display.local:~/
#   ssh pi@eink-display.local
#   chmod +x setup_pi.sh && ./setup_pi.sh
# ─────────────────────────────────────────────────────────────────

set -e

echo "══════════════════════════════════════════════════"
echo "🖼️  E-Ink Calendar Display — Pi Setup"
echo "══════════════════════════════════════════════════"

# ── Step 1: Update system ────────────────────────────────────────
echo ""
echo "📦 Step 1: Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

# ── Step 2: Enable SPI ──────────────────────────────────────────
echo ""
echo "🔧 Step 2: Enabling SPI interface..."
if ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null && \
   ! grep -q "^dtparam=spi=on" /boot/config.txt 2>/dev/null; then
    # Bookworm uses /boot/firmware/config.txt
    CONFIG_FILE="/boot/firmware/config.txt"
    if [ ! -f "$CONFIG_FILE" ]; then
        CONFIG_FILE="/boot/config.txt"
    fi
    echo "dtparam=spi=on" | sudo tee -a "$CONFIG_FILE"
    echo "   SPI enabled in $CONFIG_FILE"
    SPI_CHANGED=true
else
    echo "   SPI already enabled ✓"
    SPI_CHANGED=false
fi

# ── Step 3: Install Python dependencies ─────────────────────────
echo ""
echo "🐍 Step 3: Installing Python dependencies..."
sudo apt-get install -y \
    python3-pip \
    python3-pil \
    python3-numpy \
    python3-spidev \
    python3-gpiozero \
    git

# ── Step 4: Download Waveshare demo package ─────────────────────
echo ""
echo "📺 Step 4: Downloading Waveshare PhotoPainter demo..."
if [ ! -d "$HOME/RPi_Zero_PhotoPainter" ]; then
    cd "$HOME"
    wget -q https://files.waveshare.com/wiki/RPi_Zero_PhotoPainter/Demo/RPi_Zero_PhotoPainter.zip
    unzip -o RPi_Zero_PhotoPainter.zip -d RPi_Zero_PhotoPainter
    rm RPi_Zero_PhotoPainter.zip
    echo "   Demo package downloaded ✓"
else
    echo "   Demo package already exists ✓"
fi

# ── Step 5: Clone Waveshare e-Paper library ─────────────────────
echo ""
echo "📚 Step 5: Cloning Waveshare e-Paper library..."
if [ ! -d "$HOME/e-Paper" ]; then
    git clone https://github.com/waveshare/e-Paper.git "$HOME/e-Paper"
    echo "   Library cloned ✓"
else
    cd "$HOME/e-Paper" && git pull
    echo "   Library updated ✓"
fi

# ── Step 6: Install the e-Paper Python library ──────────────────
echo ""
echo "📦 Step 6: Installing e-Paper Python library..."
cd "$HOME/e-Paper/RaspberryPi_JetsonNano/python"
pip3 install -e . --break-system-packages 2>/dev/null || pip3 install -e .

# ── Step 7: Copy display_update.py ──────────────────────────────
echo ""
echo "📋 Step 7: Checking display_update.py..."
if [ -f "$HOME/display_update.py" ]; then
    echo "   display_update.py found ✓"
else
    echo "   ⚠️  display_update.py not found!"
    echo "   Copy it from your Mac:"
    echo "     scp pi/display_update.py pi@eink-display.local:~/"
fi

# ── Step 8: Install systemd service ─────────────────────────────
echo ""
echo "🔄 Step 8: Installing systemd service..."
if [ -f "$HOME/eink-display.service" ]; then
    sudo cp "$HOME/eink-display.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    echo "   Service installed ✓"
    echo "   To start:  sudo systemctl start eink-display"
    echo "   To enable: sudo systemctl enable eink-display"
else
    echo "   ⚠️  eink-display.service not found!"
    echo "   Copy it from your Mac:"
    echo "     scp pi/eink-display.service pi@eink-display.local:~/"
fi

# ── Done ────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════"
echo "✅ Setup complete!"
echo ""
if [ "$SPI_CHANGED" = true ]; then
    echo "⚠️  SPI was just enabled — you MUST reboot now:"
    echo "   sudo reboot"
    echo ""
fi
echo "Next steps:"
echo "  1. Reboot if SPI was just enabled"
echo "  2. Test the display: cd ~/e-Paper/RaspberryPi_JetsonNano/python/examples && python3 epd_7in3e_test.py"
echo "  3. Edit display_update.py to set your Mac's IP address"
echo "  4. Test: python3 ~/display_update.py"
echo "  5. Enable auto-start: sudo systemctl enable --now eink-display"
echo "══════════════════════════════════════════════════"
