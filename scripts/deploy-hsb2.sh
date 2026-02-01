#!/bin/bash
#
# Deploy flirc-bridge to hsb2 (Raspberry Pi Zero W)
#
# Usage: ./deploy-hsb2.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HSB2_HOST="mba@192.168.1.95"
REMOTE_DIR="/home/mba/ir-bridge"

echo "=========================================="
echo "Deploy flirc-bridge to hsb2"
echo "=========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "$REPO_ROOT/ir-bridge.py" ]; then
	echo "Error: ir-bridge.py not found in $REPO_ROOT"
	exit 1
fi

# Check if hsb2 is reachable
echo "[1/5] Checking connection to hsb2..."
if ! ssh -q "$HSB2_HOST" "exit" 2>/dev/null; then
	echo "Error: Cannot connect to hsb2 ($HSB2_HOST)"
	echo "Make sure hsb2 is online and you can SSH to it"
	exit 1
fi
echo "✓ hsb2 is reachable"

# Copy files
echo ""
echo "[2/5] Copying files to hsb2..."
scp "$REPO_ROOT/ir-bridge.py" "$HSB2_HOST:$REMOTE_DIR/"
scp "$REPO_ROOT/ir-bridge.service" "$HSB2_HOST:$REMOTE_DIR/" 2>/dev/null || echo "Note: ir-bridge.service not updated (optional)"
echo "✓ Files copied"

# Restart service
echo ""
echo "[3/5] Restarting ir-bridge service..."
ssh "$HSB2_HOST" "sudo systemctl restart ir-bridge"
echo "✓ Service restarted"

# Wait for service to start
echo ""
echo "[4/5] Waiting for service to start..."
sleep 3

# Check status
echo ""
echo "[5/5] Checking service status..."
if ssh "$HSB2_HOST" "sudo systemctl is-active ir-bridge" >/dev/null 2>&1; then
	echo "✓ Service is active"
	echo ""
	echo "Recent logs:"
	ssh "$HSB2_HOST" "sudo journalctl -u ir-bridge --since '5 seconds ago' --no-pager | tail -5"
else
	echo "✗ Service failed to start!"
	echo ""
	echo "Checking logs:"
	ssh "$HSB2_HOST" "sudo journalctl -u ir-bridge --since '10 seconds ago' --no-pager | tail -10"
	exit 1
fi

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Monitor logs:"
echo "  ssh $HSB2_HOST 'sudo journalctl -u ir-bridge -f'"
echo ""
echo "Monitor MQTT:"
echo "  mosquitto_sub -h hsb1.lan -u smarthome -P '2Au_wX_7q975dx7Ht' -t 'home/hsb2/ir-bridge/#' -v"
