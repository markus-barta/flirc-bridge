#!/bin/bash
#
# Install IR Bridge on hsb2 (Raspberry Pi Zero W)
#
# Usage: ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/home/mba/ir-bridge"
CONFIG_FILE="/etc/ir-bridge.env"
SERVICE_FILE="/etc/systemd/system/ir-bridge.service"

echo "=========================================="
echo "IR Bridge Installation Script"
echo "=========================================="
echo ""

# Check if running as root for some operations
if [ "$EUID" -eq 0 ]; then
  echo "WARNING: Running as root. Some operations will change ownership to 'mba' user."
  SUDO=""
else
  SUDO="sudo"
fi

# Step 1: Install system dependencies
echo "[1/7] Installing system dependencies..."
$SUDO apt-get update
$SUDO apt-get install -y python3 python3-pip

# Step 2: Install Python dependencies
echo "[2/7] Installing Python dependencies..."
$SUDO pip3 install evdev requests paho-mqtt

# Step 3: Add user to input group (for reading input devices)
echo "[3/7] Configuring user permissions..."
$SUDO usermod -a -G input mba

# Step 4: Create installation directory
echo "[4/7] Creating installation directory..."
$SUDO mkdir -p "$INSTALL_DIR"
$SUDO mkdir -p "$INSTALL_DIR/logs"
$SUDO cp "$SCRIPT_DIR/ir-bridge.py" "$INSTALL_DIR/"
$SUDO chmod +x "$INSTALL_DIR/ir-bridge.py"
$SUDO chown -R mba:mba "$INSTALL_DIR"

# Step 5: Install configuration file
echo "[5/7] Installing configuration..."
if [ -f "$CONFIG_FILE" ]; then
  echo "Configuration file already exists at $CONFIG_FILE"
  echo "Keeping existing configuration."
else
  echo "Creating configuration file from template..."
  $SUDO cp "$SCRIPT_DIR/ir-bridge.env.example" "$CONFIG_FILE"
  $SUDO chmod 600 "$CONFIG_FILE"
  echo ""
  echo "⚠️  IMPORTANT: Edit $CONFIG_FILE and set SONY_TV_PSK!"
  echo ""
fi

# Step 6: Install systemd service
echo "[6/7] Installing systemd service..."
$SUDO cp "$SCRIPT_DIR/ir-bridge.service" "$SERVICE_FILE"
$SUDO systemctl daemon-reload

# Step 7: Enable service
echo "[7/7] Enabling service..."
$SUDO systemctl enable ir-bridge

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit configuration: sudo nano $CONFIG_FILE"
echo "   - Set SONY_TV_PSK from your TV settings"
echo "   - Set MQTT credentials if required"
echo ""
echo "2. Verify FLIRC is connected: lsusb | grep flirc"
echo ""
echo "3. Find input device: ls -la /dev/input/event*"
echo "   Update FLIRC_DEVICE in config if needed"
echo ""
echo "4. Start the service: sudo systemctl start ir-bridge"
echo ""
echo "5. Check status: sudo systemctl status ir-bridge"
echo ""
echo "6. View logs: sudo journalctl -u ir-bridge -f"
echo ""
echo "7. Monitor MQTT: mosquitto_sub -h localhost -t 'home/hsb2/ir-bridge/#' -v"
echo ""
echo "To uninstall: sudo systemctl stop ir-bridge && sudo systemctl disable ir-bridge && sudo rm -rf $INSTALL_DIR $CONFIG_FILE $SERVICE_FILE"
