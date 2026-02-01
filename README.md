# flirc-bridge

[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](./VERSION)

Convert IR remote signals (via FLIRC USB receiver) to Sony Bravia TV commands over HTTP.

A lightweight Python bridge that runs on Raspberry Pi Zero W, replacing complex Node-RED/Docker setups with a simple, reliable service.

**Version:** See [VERSION](./VERSION) file

## Features

- **39 Button Mappings**: Full remote control (numbers, navigation, media, apps, color buttons)
- **Self-Healing**: Systemd service with auto-restart on failure
- **MQTT Reporting**: Real-time status and event publishing
- **Home Assistant Discovery**: Automatic entity configuration (Last Key, CPU, RAM, etc.)
- **Debouncing**: Prevents double commands (configurable)
- **Retry Logic**: HTTP retry with configurable attempts
- **Lightweight**: Runs on Raspberry Pi Zero W (512MB RAM)

## Hardware Requirements

- **FLIRC USB IR Receiver** (flirc.tv)
- **Raspberry Pi Zero W** (or any Linux host with USB)
- **Sony Bravia TV** with IP Control enabled
- **USB OTG Adapter** (for Pi Zero W)

## Installation

### 1. Clone and Install

```bash
git clone https://github.com/markus-barta/flirc-bridge.git
cd flirc-bridge
./install.sh
```

### 2. Configure

Edit `/etc/ir-bridge.env`:

```bash
# Required: Sony TV IP and PSK
SONY_TV_IP=192.168.1.137
SONY_TV_PSK=your_psk_here

# Optional: MQTT for debug logging
MQTT_BROKER=192.168.1.101
MQTT_TOPIC=home/hsb2/ir-bridge
```

Get PSK from TV: Settings → Network → Home Network Setup → IP Control → Pre-Shared Key

### 3. Start Service

```bash
sudo systemctl start ir-bridge
sudo systemctl status ir-bridge
```

## Button Mappings

| Remote Button | Key Code | Sony Command |
|--------------|----------|--------------|
| 0-9 | 11, 2-10 | Number keys |
| Power | 44 | Power toggle |
| Volume +/- | 115/114 | Volume up/down |
| Mute | 113 | Mute toggle |
| Up/Down/Left/Right | 103/108/105/106 | Navigation |
| Enter | 96/28 | Confirm |
| Back | 1 | Return |
| Home | 102 | Home menu |
| Netflix | 49 | Netflix app |
| YouTube | 25 | YouTube app |
| Play/Pause/Stop | 164/166 | Media controls |
| Red/Green/Yellow/Blue | 19/34/21/48 | Color buttons |

Full mapping in `ir-bridge.py` (IRCC_CODES dictionary).

## MQTT Topics

| Topic | Type | Description |
|-------|------|-------------|
| `home/hsb2/ir-bridge/status` | Retained | Service health, version, and counters |
| `home/hsb2/ir-bridge/events` | Event | Command execution details with scancodes |
| `home/hsb2/ir-bridge/health` | Heartbeat | System metrics (CPU, RAM, Disk, Uptime) |
| `home/hsb2/ir-bridge/availability` | LWT | `online` or `offline` |
| `home/hsb2/ir-bridge/unknown` | Event | Unmapped key discovery |
| `home/hsb2/ir-bridge/commands` | Input | Remote control (status, restart) |

### Status Payload

```json
{
  "version": "0.2.1",
  "machine": "hsb2",
  "status": "running",
  "keys_pressed": 42,
  "commands_sent": 41,
  "errors": 1,
  "last_command": "volumeup",
  "started_at": "2026-02-01T12:00:00"
}
```

### Health Payload

```json
{
  "cpu": { "percent": 5.2, "load_avg": [0.1, 0.2, 0.5] },
  "memory": { "total_mb": 440.0, "available_mb": 210.5, "percent_used": 52.1 },
  "disk": { "total_gb": 14.2, "used_gb": 3.1, "percent_used": 22.4 },
  "uptime_seconds": 86400
}
```

## Configuration

All settings via environment variables in `/etc/ir-bridge.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SONY_TV_IP` | 192.168.1.137 | TV IP address |
| `SONY_TV_PSK` | (required) | Pre-Shared Key |
| `FLIRC_DEVICE` | /dev/input/event0 | Input device path |
| `MQTT_BROKER` | 192.168.1.101 | MQTT broker host |
| `MQTT_PORT` | 1883 | MQTT broker port |
| `MQTT_USER` | (optional) | MQTT username |
| `MQTT_PASS` | (optional) | MQTT password |
| `MQTT_TOPIC` | home/hsb2/ir-bridge | Base MQTT topic |
| `LOG_LEVEL` | INFO | DEBUG/INFO/WARNING/ERROR |
| `DEBOUNCE_MS` | 300 | Debounce time in ms |
| `RETRY_COUNT` | 3 | HTTP retry attempts |
| `RETRY_DELAY` | 1.0 | Seconds between retries |

## Button Holding

The bridge supports holding buttons (e.g., keeping volume up/down pressed for continuous adjustment):

- **Single press**: Press and release quickly → one command
- **Hold**: Keep button pressed → repeats command continuously

**How it works:**
- FLIRC generates `key_hold` events while button is held
- Bridge sends command on each `key_hold` event (no debounce)
- Initial press has debounce (300ms) to prevent accidental double-presses
- TV receives continuous commands while button is held

**Example:** Hold volume up button → TV volume increases continuously until released.

**Note:** Some buttons (like power) work best with single press only. The bridge handles both modes automatically.

## Troubleshooting

### Check if FLIRC is detected

```bash
lsusb | grep flirc
cat /proc/bus/input/devices | grep -A5 flirc
```

### Test input device

```bash
sudo evtest /dev/input/event0
# Press remote buttons to see events
```

### View logs

```bash
sudo journalctl -u ir-bridge -f
```

### Monitor MQTT

```bash
mosquitto_sub -h <broker> -t 'home/hsb2/ir-bridge/#' -v
```

## Architecture

```
IR Remote → FLIRC USB → Linux evdev → Python Script → HTTP → Sony TV
                                              ↓
                                           MQTT (debug)
```

## License

MIT License - See LICENSE file

## Author

Markus Barta
