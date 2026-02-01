# Operations Manual: FLIRC Bridge

**Document ID:** FLIRC-BRIDGE-OPS-001
**Version:** 0.1.1
**Status:** Active
**Date:** 2026-02-01

## 1. Installation & Deployment

### 1.1 Local Installation (on Raspberry Pi)
If you are on the target device (e.g., Raspberry Pi Zero W):
```bash
cd /path/to/flirc-bridge
sudo ./scripts/install.sh
```
*Note: This sets up the directory `/home/mba/ir-bridge`, installs dependencies, and registers the systemd service.*

### 1.2 Remote Deployment (to hsb2)
If you are developing on another machine and want to push updates:
```bash
./scripts/deploy-hsb2.sh
```
*Note: This uses SSH/SCP to push `ir-bridge.py` to `mba@192.168.1.95` and restarts the service.*

## 2. Configuration Management

The bridge is configured via environment variables in `/etc/ir-bridge.env`.

### 2.1 Editing Configuration
```bash
sudo nano /etc/ir-bridge.env
```

### 2.2 Applying Changes
After editing the config, restart the service:
```bash
sudo systemctl restart ir-bridge
```

## 3. Service Management

| Action | Command |
|--------|---------|
| Start | `sudo systemctl start ir-bridge` |
| Stop | `sudo systemctl stop ir-bridge` |
| Restart | `sudo systemctl restart ir-bridge` |
| Status | `sudo systemctl status ir-bridge` |
| View Logs | `sudo journalctl -u ir-bridge -f` |

## 4. Troubleshooting & Diagnostics

### 4.1 Hardware Verification
Check if the FLIRC USB receiver is detected by the OS:
```bash
lsusb | grep -i flirc
cat /proc/bus/input/devices | grep -A5 flirc
```

### 4.2 Input Testing
Verify that IR signals are being translated to key events:
```bash
# Install evtest if not present
sudo apt-get install evtest
# Run evtest on the FLIRC device (usually /dev/input/event0)
sudo evtest /dev/input/event0
```

### 4.3 MQTT Monitoring
Monitor real-time events and status updates:
```bash
mosquitto_sub -h <mqtt_broker_ip> -t 'home/hsb2/ir-bridge/#' -v
```

### 4.4 Sony TV Connectivity
Test if the TV is reachable on the network:
```bash
ping <SONY_TV_IP>
```

## 5. Maintenance Tasks

### 5.1 Updating Button Mappings
1. Edit `ir-bridge.py`.
2. Locate the `IRCC_CODES` dictionary.
3. Update or add scancodes and their corresponding Sony IRCC Base64 commands.
4. Deploy/Restart the service.

### 5.2 Uninstalling
```bash
sudo systemctl stop ir-bridge
sudo systemctl disable ir-bridge
sudo rm -rf /home/mba/ir-bridge
sudo rm -f /etc/systemd/system/ir-bridge.service
sudo rm -f /etc/ir-bridge.env
```
