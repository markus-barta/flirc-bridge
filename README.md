# flirc-bridge

Convert IR remote signals (via FLIRC USB receiver) to Sony Bravia TV commands over HTTP.

A lightweight Python bridge that runs on Raspberry Pi Zero W, replacing complex Node-RED/Docker setups with a simple, reliable service.

## Features

- **39 Button Mappings**: Full remote control (numbers, navigation, media, apps, color buttons)
- **Self-Healing**: Systemd service with auto-restart on failure
- **MQTT Reporting**: Real-time status and event publishing
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
| `home/hsb2/ir-bridge/status` | Retained | Service status (JSON) |
| `home/hsb2/ir-bridge/event` | Event | Per-keypress events |
| `home/hsb2/ir-bridge/control` | Input | Control commands (status, restart) |

### Status Payload

```json
{
  "started_at": "2026-01-31T15:30:00",
  "keys_pressed": 42,
  "commands_sent": 41,
  "errors": 1,
  "last_command": "volumeup",
  "status": "running"
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
