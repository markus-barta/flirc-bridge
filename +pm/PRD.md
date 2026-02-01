# Product Requirements Document: FLIRC Bridge

**Document ID:** FLIRC-BRIDGE-PRD-001
**Version:** 0.2.1
**Status:** Active
**Date:** 2026-02-01
**Author:** Markus Barta

## 1. Overview

A lightweight Python-based bridge that converts Infrared (IR) remote signals received via a FLIRC USB receiver into IP-based commands for Sony Bravia TVs. It is designed to run on resource-constrained hardware like the Raspberry Pi Zero W, providing a reliable, self-healing alternative to complex Node-RED or Docker-based setups.

## 2. Target Audience

- Home automation enthusiasts
- Users with legacy IR remotes wanting to control Sony Smart TVs
- Users looking for a low-power, dedicated hardware bridge (RPi Zero W)

## 3. Core Requirements

### 3.1 Functionality
- **IR Translation**: Map Linux input events (evdev) from FLIRC to Sony IRCC (Base64) commands.
- **Persistent Input**: Support for stable device identification via `/dev/input/by-id/` or name-based auto-discovery.
- **Sony TV Control**: Send commands over HTTP using Pre-Shared Key (PSK) authentication.
- **Button Holding**: Support continuous command repetition when a remote button is held down (e.g., volume ramp).
- **Debouncing**: Configurable software debouncing to prevent accidental double-triggers.
- **MQTT Integration**: 
  - Publish real-time events and status.
  - **System Health Reporting**: Periodic heartbeat with CPU, RAM, Disk, and Uptime metrics.
  - Report unknown key codes for easy discovery/mapping.
  - Basic remote control (status requests, service restart).

### 3.2 Reliability & Performance
- **Self-Healing**: Runs as a Systemd service with auto-restart on failure.
- **Retries**: Configurable HTTP retry logic for resilient TV communication.
- **Efficiency**: Optimized for Raspberry Pi Zero W (minimal CPU/RAM footprint).
- **Simulation Mode**: Fallback mode if `evdev` is missing (for testing/development).

### 3.3 Technical Requirements
- **Hardware**: 
  - Raspberry Pi Zero W (or similar Linux host)
  - FLIRC USB IR Receiver
  - Sony Bravia TV with IP Control enabled
- **Software Stack**: 
  - Python 3.x
  - `python-evdev` for input handling
  - `requests` for Sony TV API communication
  - `paho-mqtt` for messaging
- **Connectivity**: Local Network (HTTP + MQTT)

## 4. Functional Specifications

### 4.1 Input Handling
- **Device**: Listens on `/dev/input/event*` (default: `event0`).
- **Event Types**: Monitors `EV_KEY` events.
- **States**: Handles `key_down` (initial press) and `key_hold` (repetition).

### 4.2 Sony TV Integration
- **Protocol**: SOAP/XML over HTTP.
- **Authentication**: `X-Auth-PSK` header.
- **Endpoint**: `http://{TV_IP}/sony/IRCC`.
- **Command Set**: Supports 39+ mappings including navigation, media, apps (Netflix/YouTube), and numeric keys.

### 4.3 MQTT API
- **Base Topic**: `home/hsb2/ir-bridge` (configurable).
- **Sub-topics**:
  - `/status`: Retained JSON payload with uptime, stats, and health.
  - `/event`: JSON payload per successful/failed command.
  - `/unknown`: JSON payload for unmapped scancodes.
  - `/control`: Input topic for `status` or `restart` commands.

## 5. Configuration (Environment Variables)

Settings are managed via `/etc/ir-bridge.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `SONY_TV_IP` | IP address of the Bravia TV | 192.168.1.137 |
| `SONY_TV_PSK` | Pre-Shared Key (required) | - |
| `FLIRC_DEVICE` | Path to the FLIRC input device | /dev/input/event0 |
| `MQTT_BROKER` | MQTT Broker address | 192.168.1.101 |
| `MQTT_TOPIC` | Base topic for MQTT | home/hsb2/ir-bridge |
| `DEBOUNCE_MS` | Debounce threshold in ms | 300 |
| `LOG_LEVEL` | Logging verbosity (INFO/DEBUG/...) | INFO |

## 6. Non-Functional Requirements

- **Deployment**: Simple `install.sh` script for RPi environment setup.
- **Logging**: Journald integration via Systemd.
- **Maintainability**: Clean Python code with minimal external dependencies.

## 7. Future Enhancements

- [ ] Web-based configuration UI for mapping buttons.
- [ ] Support for multiple TV targets.
- [ ] Integration with Home Assistant Discovery (MQTT).
- [ ] Dynamic device discovery for FLIRC.

## 8. Acceptance Criteria

- [ ] Bridge successfully maps power/volume/navigation to Sony TV.
- [ ] Holding volume button results in continuous volume change on TV.
- [ ] Service automatically restarts if the process crashes.
- [ ] MQTT receives "unknown" event when a new remote button is pressed.
- [ ] TV commands succeed even if the network has transient failures (retries).
