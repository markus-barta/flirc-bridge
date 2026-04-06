#!/usr/bin/env python3
"""
IR → Sony TV Bridge

Converts IR remote signals (via FLIRC USB receiver) to Sony Bravia TV commands.
Runs on Raspberry Pi Zero W (hsb2) as a lightweight replacement for Node-RED implementation.

Environment Variables:
    SONY_TV_IP: Sony TV IP address (default: 192.168.1.137)
    SONY_TV_PSK: Pre-Shared Key for TV authentication (required)
    FLIRC_DEVICE: Input device path (default: /dev/input/event0)
    MQTT_BROKER: MQTT broker host (default: 192.168.1.101)
    MQTT_PORT: MQTT broker port (default: 1883)
    MQTT_USER: MQTT username (optional)
    MQTT_PASS: MQTT password (optional)
    MQTT_TOPIC: Base MQTT topic (default: home/hsb2/ir-bridge)
    LOG_LEVEL: Logging level (default: INFO)
    DEBOUNCE_MS: Debounce time in milliseconds (default: 100)
    RETRY_COUNT: HTTP retry attempts (default: 3)
    RETRY_DELAY: Seconds between retries (default: 1.0)
    WEB_PORT: Web UI port (default: 8080)
"""

import os
import sys
import time
import json
import logging
import signal
import threading
from collections import deque
from datetime import datetime
from typing import Optional, Dict, Any

import requests
import paho.mqtt.client as mqtt

try:
    from flask import Flask, render_template, request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Read version from VERSION file
def get_version():
    try:
        version_file = os.path.join(os.path.dirname(__file__), 'VERSION')
        with open(version_file, 'r') as f:
            return f.read().strip()
    except:
        return 'unknown'

VERSION = get_version()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPINGS_FILE = os.path.join(BASE_DIR, 'mappings.json')
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')

# Try to import evdev, handle gracefully if not available
try:
    from evdev import InputDevice, categorize, ecodes
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    logging.warning("evdev module not available. Running in simulation mode.")

# Configuration from environment variables
CONFIG = {
    'sony_tv_ip': os.getenv('SONY_TV_IP', '192.168.1.137'),
    'sony_tv_psk': os.getenv('SONY_TV_PSK', ''),
    'flirc_device': os.getenv('FLIRC_DEVICE', '/dev/input/event0'),
    'mqtt_broker': os.getenv('MQTT_BROKER', '192.168.1.101'),
    'mqtt_port': int(os.getenv('MQTT_PORT', '1883')),
    'mqtt_user': os.getenv('MQTT_USER', ''),
    'mqtt_pass': os.getenv('MQTT_PASS', ''),
    'mqtt_topic': os.getenv('MQTT_TOPIC', 'home/hsb2/ir-bridge'),
    'log_level': os.getenv('LOG_LEVEL', 'INFO'),
    'debounce_ms': int(os.getenv('DEBOUNCE_MS', '100')),
    'retry_count': int(os.getenv('RETRY_COUNT', '3')),
    'retry_delay': float(os.getenv('RETRY_DELAY', '1.0')),
    'web_port': int(os.getenv('WEB_PORT', '8080')),
}


def load_mappings() -> Dict[int, tuple]:
    """Load scancode→IRCC mappings from JSON file.

    Returns dict of scancode -> (command, ircc, debounce_ms, action).
    action: 'direct' (send IRCC), 'mqtt' (HA handles), 'disabled'
    """
    try:
        with open(MAPPINGS_FILE, 'r') as f:
            raw = json.load(f)
        result = {}
        for scancode_hex, entry in raw.items():
            scancode = int(scancode_hex, 16)
            debounce = entry.get('debounce_ms')
            action = entry.get('action', 'direct')
            result[scancode] = (entry['command'], entry['ircc'], debounce, action)
        return result
    except Exception as e:
        logging.error(f"Failed to load mappings from {MAPPINGS_FILE}: {e}")
        return {}


def load_mappings_raw() -> dict:
    """Load raw JSON mappings for web UI."""
    try:
        with open(MAPPINGS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}


def save_mappings_raw(data: dict):
    """Save raw JSON mappings from web UI."""
    with open(MAPPINGS_FILE, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')


SETTINGS_DEFAULTS = {
    'debug_mode': False,
    'debounce_ms': 100,
    'hold_throttle_ms': 200,
    'retry_count': 3,
    'retry_delay': 1.0,
    'log_level': 'INFO',
    'ha_url': '',
    'ha_token': '',
}

def load_settings() -> dict:
    """Load bridge settings, merging with defaults."""
    settings = dict(SETTINGS_DEFAULTS)
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings.update(json.load(f))
    except:
        pass
    return settings


def save_settings(data: dict):
    """Save bridge settings."""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')


class IRBridge:
    """Main IR Bridge class handling input, TV control, and MQTT."""

    def __init__(self):
        self.logger = self._setup_logging()
        self.mqtt_client: Optional[mqtt.Client] = None
        self.input_device: Optional[Any] = None
        self.running = False
        self.last_key_time: Dict[int, float] = {}
        self.last_hold_time: Dict[int, float] = {}
        self.ircc_codes: Dict[int, tuple] = {}
        self.recent_events: deque = deque(maxlen=50)
        self.settings = load_settings()
        self._mappings_mtime: float = 0
        self.stats = {
            'version': VERSION,
            'machine': 'hsb2',
            'started_at': datetime.now().isoformat(),
            'keys_pressed': 0,
            'commands_sent': 0,
            'errors': 0,
            'last_command': "",
            'last_key': "",
            'status': 'initializing'
        }

        # Validate configuration
        if not CONFIG['sony_tv_psk']:
            self.logger.error("SONY_TV_PSK environment variable not set!")
            sys.exit(1)

        # Load mappings
        self._reload_mappings()

    def _reload_mappings(self):
        """Reload mappings from JSON if file changed."""
        try:
            mtime = os.path.getmtime(MAPPINGS_FILE)
            if mtime != self._mappings_mtime:
                self.ircc_codes = load_mappings()
                self._mappings_mtime = mtime
                self.logger.info(f"Loaded {len(self.ircc_codes)} mappings from {MAPPINGS_FILE}")
        except Exception as e:
            self.logger.error(f"Failed to reload mappings: {e}")

    @property
    def mqtt_topic(self) -> str:
        """Return current MQTT topic prefix based on debug mode."""
        base = CONFIG['mqtt_topic']
        if self.settings.get('debug_mode', False):
            # Replace first path segment with 'debug'
            parts = base.split('/')
            parts[0] = 'debug'
            return '/'.join(parts)
        return base

    def _setup_logging(self) -> logging.Logger:
        """Configure logging."""
        logger = logging.getLogger('ir-bridge')
        logger.setLevel(getattr(logging, CONFIG['log_level'].upper()))

        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        return logger

    def _setup_mqtt(self) -> bool:
        """Setup MQTT connection with LWT and Discovery."""
        try:
            try:
                from paho.mqtt.enums import CallbackAPIVersion
                self.mqtt_client = mqtt.Client(CallbackAPIVersion.VERSION2)
            except ImportError:
                self.mqtt_client = mqtt.Client()

            self.mqtt_client.will_set(
                f"{self.mqtt_topic}/availability",
                payload="offline",
                retain=True
            )

            if CONFIG['mqtt_user'] and CONFIG['mqtt_pass']:
                self.mqtt_client.username_pw_set(
                    CONFIG['mqtt_user'],
                    CONFIG['mqtt_pass']
                )

            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_message = self._on_mqtt_message

            self.mqtt_client.connect(
                CONFIG['mqtt_broker'],
                CONFIG['mqtt_port'],
                keepalive=60
            )

            self.mqtt_client.loop_start()

            self.logger.info(f"MQTT connected to {CONFIG['mqtt_broker']}:{CONFIG['mqtt_port']}")
            return True

        except Exception as e:
            self.logger.error(f"MQTT connection failed: {e}")
            return False

    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        """MQTT connect callback (paho-mqtt v2 compatible)."""
        if rc == 0:
            self.logger.info("MQTT connected successfully")
            client.subscribe(f"{self.mqtt_topic}/commands")
            self.mqtt_client.publish(f"{self.mqtt_topic}/availability", "online", retain=True)
            self._setup_ha_discovery()
            self._publish_status()
        else:
            self.logger.error(f"MQTT connection failed with code {rc}")

    def _setup_ha_discovery(self):
        """Register device and entities in Home Assistant via MQTT Discovery."""
        base_topic = self.mqtt_topic
        node_id = "flirc_bridge_hsb2"
        device_info = {
            "identifiers": [node_id],
            "name": "FLIRC Bridge",
            "model": "Raspberry Pi Zero W",
            "manufacturer": "Markus Barta",
            "sw_version": VERSION
        }

        entities = [
            {
                "type": "sensor",
                "id": "last_key",
                "name": "Last Key",
                "icon": "mdi:remote",
                "state_topic": f"{base_topic}/status",
                "value_template": "{{ value_json.last_key }}"
            },
            {
                "type": "sensor",
                "id": "cpu_usage",
                "name": "CPU Usage",
                "unit": "%",
                "class": "power_factor",
                "icon": "mdi:cpu-64-bit",
                "state_topic": f"{base_topic}/health",
                "value_template": "{{ value_json.cpu.percent }}"
            },
            {
                "type": "sensor",
                "id": "memory_usage",
                "name": "Memory Usage",
                "unit": "%",
                "icon": "mdi:memory",
                "state_topic": f"{base_topic}/health",
                "value_template": "{{ value_json.memory.percent_used }}"
            },
            {
                "type": "sensor",
                "id": "disk_usage",
                "name": "Disk Usage",
                "unit": "%",
                "icon": "mdi:harddisk",
                "state_topic": f"{base_topic}/health",
                "value_template": "{{ value_json.disk.percent_used }}"
            },
            {
                "type": "sensor",
                "id": "uptime",
                "name": "Uptime",
                "unit": "s",
                "class": "duration",
                "icon": "mdi:clock-outline",
                "state_topic": f"{base_topic}/health",
                "value_template": "{{ value_json.uptime_seconds }}"
            },
            {
                "type": "binary_sensor",
                "id": "status",
                "name": "Connectivity",
                "device_class": "connectivity",
                "state_topic": f"{base_topic}/availability",
                "payload_on": "online",
                "payload_off": "offline"
            }
        ]

        for entity in entities:
            discovery_topic = f"homeassistant/{entity['type']}/{node_id}/{entity['id']}/config"
            payload = {
                "name": entity['name'],
                "unique_id": f"{node_id}_{entity['id']}",
                "state_topic": entity['state_topic'],
                "availability_topic": f"{base_topic}/availability",
                "device": device_info
            }
            if "value_template" in entity:
                payload["value_template"] = entity["value_template"]
            if "unit" in entity:
                payload["unit_of_measurement"] = entity["unit"]
            if "class" in entity:
                payload["device_class"] = entity["class"]
            if "icon" in entity:
                payload["icon"] = entity["icon"]
            if "payload_on" in entity:
                payload["payload_on"] = entity["payload_on"]
                payload["payload_off"] = entity["payload_off"]

            self.mqtt_client.publish(discovery_topic, json.dumps(payload), retain=True)

        self.logger.info("Home Assistant Discovery payloads published")

    def _teardown_ha_discovery(self, topic_prefix: str):
        """Remove HA discovery entities and mark offline for a topic prefix."""
        if not self.mqtt_client:
            return
        node_id = "flirc_bridge_hsb2"
        entity_ids = [
            ("sensor", "last_key"), ("sensor", "cpu_usage"),
            ("sensor", "memory_usage"), ("sensor", "disk_usage"),
            ("sensor", "uptime"), ("binary_sensor", "status"),
        ]
        # Remove discovery entries
        for etype, eid in entity_ids:
            discovery_topic = f"homeassistant/{etype}/{node_id}/{eid}/config"
            self.mqtt_client.publish(discovery_topic, "", retain=True)
        # Mark offline
        self.mqtt_client.publish(f"{topic_prefix}/availability", "offline", retain=True)
        self.logger.info(f"HA Discovery removed, marked offline on {topic_prefix}")

    def set_debug_mode(self, enabled: bool):
        """Switch debug mode, updating MQTT topics and HA discovery."""
        old_topic = self.mqtt_topic
        self.settings['debug_mode'] = enabled
        save_settings(self.settings)
        new_topic = self.mqtt_topic

        if old_topic != new_topic:
            # Tear down old topic
            self._teardown_ha_discovery(old_topic)
            # Setup new topic
            self.mqtt_client.publish(f"{new_topic}/availability", "online", retain=True)
            if not enabled:
                # Back to production — re-register HA discovery
                self._setup_ha_discovery()
            self.mqtt_client.subscribe(f"{new_topic}/commands")
            self._publish_status()

        self.logger.info(f"Debug mode {'ON' if enabled else 'OFF'} — topic: {new_topic}")

    def _on_mqtt_disconnect(self, client, userdata, flags, rc, properties=None):
        """MQTT disconnect callback (paho-mqtt v2 compatible)."""
        self.logger.warning(f"MQTT disconnected (rc={rc})")

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT message callback."""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')

            if topic.endswith('/commands'):
                if payload == 'status':
                    self._publish_status()
                elif payload == 'restart':
                    self.logger.info("Restart requested via MQTT")
                    self.stop()

        except Exception as e:
            self.logger.error(f"Error handling MQTT message: {e}")

    def _publish_status(self):
        """Publish current status to MQTT."""
        if not self.mqtt_client:
            return

        try:
            self.stats['status'] = 'running' if self.running else 'stopped'
            self.stats['updated_at'] = datetime.now().isoformat()

            self.mqtt_client.publish(
                f"{self.mqtt_topic}/status",
                json.dumps(self.stats),
                retain=True
            )

            self.logger.debug("Status published to MQTT")

        except Exception as e:
            self.logger.error(f"Failed to publish status: {e}")

    def _publish_event(self, key_name: str, key_code: int, command_name: str, success: bool, input_type: str):
        """Publish key event to MQTT."""
        if not self.mqtt_client:
            return

        try:
            event = {
                'timestamp': datetime.now().isoformat(),
                'version': VERSION,
                'machine': 'hsb2',
                'event': {
                    'key_name': key_name,
                    'key_code': key_code,
                    'key_code_hex': hex(key_code) if key_code > 1000 else None,
                    'input_type': input_type,
                    'command': command_name,
                    'success': success
                },
                'target': {
                    'type': 'sony_tv',
                    'ip': CONFIG['sony_tv_ip']
                }
            }

            self.mqtt_client.publish(
                f"{self.mqtt_topic}/events",
                json.dumps(event)
            )

        except Exception as e:
            self.logger.error(f"Failed to publish event: {e}")

    def _publish_raw_key(self, key_code: int, input_type: str, mapped: bool, command_name: str = None):
        """Publish raw key event to MQTT and store for web UI."""
        event = {
            'timestamp': datetime.now().isoformat(),
            'version': VERSION,
            'machine': 'hsb2',
            'key': {
                'key_code': key_code,
                'key_code_hex': hex(key_code),
                'input_type': input_type,
                'command': command_name,
                'mapped': mapped,
            }
        }

        # Store for web UI polling
        self.recent_events.append(event)

        if not self.mqtt_client:
            return

        try:
            self.mqtt_client.publish(
                f"{self.mqtt_topic}/raw",
                json.dumps(event)
            )

            if not mapped:
                self.logger.info(f"Published unmapped key {key_code} to MQTT")

        except Exception as e:
            self.logger.error(f"Failed to publish raw key: {e}")

    def _send_ircc_command(self, ircc_code: str, command_name: str) -> bool:
        """Send IRCC command to Sony TV."""
        url = f"http://{CONFIG['sony_tv_ip']}/sony/IRCC"
        headers = {
            'Content-Type': 'text/xml; charset=UTF-8',
            'SOAPACTION': '"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"',
            'X-Auth-PSK': CONFIG['sony_tv_psk']
        }

        body = f'''<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1">
      <IRCCCode>{ircc_code}</IRCCCode>
    </u:X_SendIRCC>
  </s:Body>
</s:Envelope>'''

        retry_count = self.settings.get('retry_count', 3)
        retry_delay = self.settings.get('retry_delay', 1.0)

        for attempt in range(retry_count):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    data=body,
                    timeout=5
                )

                if response.status_code == 200:
                    self.logger.debug(f"Command sent successfully: {command_name}")
                    return True
                else:
                    self.logger.warning(
                        f"Command failed with status {response.status_code}: {command_name}"
                    )

            except requests.exceptions.RequestException as e:
                self.logger.error(f"Request failed (attempt {attempt + 1}): {e}")

            if attempt < retry_count - 1:
                time.sleep(retry_delay)

        return False

    def _handle_key(self, key_code: int, is_hold: bool = False):
        """Handle a key press event."""
        now = time.time() * 1000  # ms
        input_type = 'hardware_scancode' if key_code > 1000 else 'linux_keycode'

        # Check for mapping changes
        self._reload_mappings()

        # Get per-key debounce and action if mapped
        per_key_debounce = None
        per_key_action = 'direct'
        if key_code in self.ircc_codes:
            _, _, per_key_debounce, per_key_action = self.ircc_codes[key_code]

        # Throttling for held buttons
        hold_throttle = self.settings.get('hold_throttle_ms', 200)
        # Per-key debounce also suppresses hold events (e.g. power must not repeat)
        if per_key_debounce is not None:
            hold_throttle = max(hold_throttle, per_key_debounce)

        if is_hold:
            if key_code in self.last_hold_time:
                elapsed_hold = now - self.last_hold_time[key_code]
                if elapsed_hold < hold_throttle:
                    return
            self.last_hold_time[key_code] = now
        else:
            # Per-key debounce overrides global
            debounce_limit = per_key_debounce if per_key_debounce is not None else self.settings.get('debounce_ms', 100)

            if key_code in self.last_key_time:
                elapsed = now - self.last_key_time[key_code]
                if elapsed < debounce_limit:
                    return

            self.last_key_time[key_code] = now
            self.last_hold_time[key_code] = now

        # Lookup command
        if key_code not in self.ircc_codes:
            self.logger.info(f"Unknown {input_type}: {key_code} ({hex(key_code)})")
            self._publish_raw_key(key_code, input_type, mapped=False)
            return

        command_name, ircc_code, _, action = self.ircc_codes[key_code]

        if action == 'disabled':
            self.logger.debug(f"Disabled key: {command_name} ({input_type}: {key_code})")
            self._publish_raw_key(key_code, input_type, mapped=True, command_name=command_name)
            return

        if is_hold:
            self.logger.debug(f"Key held: {command_name} ({input_type}: {key_code})")
        else:
            self.logger.info(f"Key pressed: {command_name} [{action}] ({input_type}: {key_code})")

        self.stats['keys_pressed'] += 1
        self.stats['last_key'] = command_name

        # Publish raw key for all presses
        self._publish_raw_key(key_code, input_type, mapped=True, command_name=command_name)

        if action == 'mqtt':
            # Don't send IRCC — HA handles this via MQTT
            self._publish_event(command_name, key_code, command_name, True, input_type)
            self._publish_status()
            return

        # action == 'direct': send to TV in background thread
        threading.Thread(
            target=self._send_and_report,
            args=(ircc_code, command_name, key_code, input_type),
            daemon=True
        ).start()

    def _send_and_report(self, ircc_code: str, command_name: str, key_code: int, input_type: str):
        """Send IRCC command and update stats/events (runs in background thread)."""
        if self.settings.get('debug_mode', False):
            self.logger.info(f"Debug mode: suppressed {command_name} (not sent to TV)")
            success = True  # pretend success for stats
        else:
            success = self._send_ircc_command(ircc_code, command_name)

        if success:
            self.stats['commands_sent'] += 1
            self.stats['last_command'] = command_name
        else:
            self.stats['errors'] += 1

        self._publish_event(command_name, key_code, command_name, success, input_type)
        self._publish_status()

    def _setup_input(self) -> bool:
        """Setup input device (FLIRC)."""
        if not EVDEV_AVAILABLE:
            self.logger.warning("evdev not available, running in simulation mode")
            return True

        try:
            device_path = CONFIG['flirc_device']

            from evdev import list_devices
            devices = [InputDevice(path) for path in list_devices()]

            flirc_devices = [d for d in devices if 'flirc' in d.name.lower()]

            if flirc_devices:
                target_device = flirc_devices[0]
                self.input_device = target_device
                self.logger.info(f"Auto-discovered FLIRC device: {target_device.name}")
                self.logger.info(f"Device path: {target_device.path}")
                return True

            self.input_device = InputDevice(device_path)
            self.logger.info(f"Using configured input device: {self.input_device.name}")
            self.logger.info(f"Device path: {device_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to setup input device: {e}")
            return False

    def _read_input(self):
        """Read and process input events."""
        if not EVDEV_AVAILABLE or not self.input_device:
            self.logger.warning("Input device not available, simulating...")
            while self.running:
                self._publish_status()
                time.sleep(30)
            return

        try:
            self.logger.info("Starting input event loop")

            scancode = None
            last_scancode = {}  # linux_keycode -> hardware_scancode
            for event in self.input_device.read_loop():
                if not self.running:
                    break

                # Capture MSC_SCAN (arrives before EV_KEY for key_down)
                if event.type == ecodes.EV_MSC and event.code == ecodes.MSC_SCAN:
                    scancode = event.value
                    self.logger.debug(f"Hardware Scancode received: {hex(scancode)}")

                # Process key press and hold events
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    linux_code = key_event.scancode

                    if scancode is not None:
                        target_code = scancode
                        last_scancode[linux_code] = scancode
                        scancode = None
                    elif linux_code in last_scancode:
                        target_code = last_scancode[linux_code]
                    else:
                        target_code = linux_code

                    if key_event.keystate == key_event.key_down:
                        self.logger.info(f"Input: Code {hex(target_code)} ({key_event.keycode})")
                        self._handle_key(target_code, is_hold=False)
                    elif key_event.keystate == key_event.key_hold:
                        self._handle_key(target_code, is_hold=True)

        except Exception as e:
            self.logger.error(f"Input read error: {e}")
            self.stats['errors'] += 1

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.stop()

    def _setup_web(self):
        """Setup Flask web UI in a background thread."""
        if not FLASK_AVAILABLE:
            self.logger.warning("Flask not available, web UI disabled")
            return

        bridge = self
        app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))

        # Suppress Flask request logging
        flog = logging.getLogger('werkzeug')
        flog.setLevel(logging.WARNING)

        @app.route('/')
        def index():
            return render_template('index.html',
                version=VERSION,
                debug_mode='true' if bridge.settings.get('debug_mode', False) else 'false',
                mqtt_topic=bridge.mqtt_topic,
                mappings_json=json.dumps(load_mappings_raw())
            )

        @app.route('/api/mappings', methods=['GET', 'POST'])
        def api_mappings():
            if request.method == 'GET':
                return jsonify(load_mappings_raw())
            data = request.get_json()
            try:
                save_mappings_raw(data)
                bridge._reload_mappings()
                return jsonify({'ok': True, 'count': len(data)})
            except Exception as e:
                return jsonify({'ok': False, 'error': str(e)}), 500

        @app.route('/api/settings', methods=['GET', 'POST'])
        def api_settings():
            if request.method == 'GET':
                return jsonify(bridge.settings)
            data = request.get_json()
            # Handle debug mode separately (needs MQTT teardown/setup)
            if 'debug_mode' in data and data['debug_mode'] != bridge.settings.get('debug_mode'):
                bridge.set_debug_mode(bool(data['debug_mode']))
            # Apply all other settings
            for key in ('debounce_ms', 'hold_throttle_ms', 'retry_count', 'retry_delay', 'log_level', 'ha_url', 'ha_token'):
                if key in data:
                    bridge.settings[key] = data[key]
            # Apply log level if changed
            if 'log_level' in data:
                bridge.logger.setLevel(getattr(logging, str(data['log_level']).upper(), logging.INFO))
            save_settings(bridge.settings)
            return jsonify({'ok': True, 'mqtt_topic': bridge.mqtt_topic})

        @app.route('/api/events', methods=['GET', 'DELETE'])
        def api_events():
            if request.method == 'DELETE':
                bridge.recent_events.clear()
                return jsonify({'ok': True})
            last_ts = request.args.get('last_ts', '')
            events = list(bridge.recent_events)
            if last_ts:
                events = [e for e in events if e['timestamp'] > last_ts]
            return jsonify(events)

        @app.route('/api/test', methods=['POST'])
        def api_test():
            data = request.get_json()
            ircc = data.get('ircc', '')
            command = data.get('command', 'test')
            if not ircc:
                return jsonify({'ok': False, 'error': 'No IRCC code'}), 400
            success = bridge._send_ircc_command(ircc, command)
            return jsonify({'ok': success, 'command': command})

        @app.route('/api/status')
        def api_status():
            return jsonify(bridge.stats)

        @app.route('/api/ha-scan', methods=['POST'])
        def api_ha_scan():
            ha_url = bridge.settings.get('ha_url', '').rstrip('/')
            ha_token = bridge.settings.get('ha_token', '')
            if not ha_url or not ha_token:
                return jsonify({'ok': False, 'error': 'Set HA URL and token in settings first'}), 400
            headers = {'Authorization': f'Bearer {ha_token}'}
            search_terms = ['ir-bridge', 'ir_bridge', 'flirc_bridge', 'flirc', 'last_key']
            try:
                # Get all automation entity IDs from states
                r = requests.get(f"{ha_url}/api/states", headers=headers, timeout=10)
                if r.status_code != 200:
                    return jsonify({'ok': False, 'error': f'HA API returned {r.status_code}'}), 502
                states = r.json()
                automations = [s for s in states if s['entity_id'].startswith('automation.')]

                results = []
                for a in automations:
                    auto_id = a.get('attributes', {}).get('id', '')
                    if not auto_id:
                        continue
                    # Fetch full config for each automation
                    cr = requests.get(f"{ha_url}/api/config/automation/config/{auto_id}", headers=headers, timeout=5)
                    if cr.status_code != 200:
                        continue
                    config = cr.json()
                    config_str = json.dumps(config).lower()
                    if any(term in config_str for term in search_terms):
                        # Extract trigger details
                        triggers = config.get('triggers', config.get('trigger', []))
                        if isinstance(triggers, dict):
                            triggers = [triggers]
                        trigger_info = []
                        for t in triggers:
                            t_str = json.dumps(t)
                            if any(term in t_str.lower() for term in search_terms):
                                to_val = t.get('to', '')
                                entity = t.get('entity_id', '')
                                if isinstance(entity, list):
                                    entity = ', '.join(entity)
                                if isinstance(to_val, list):
                                    to_val = ', '.join(str(v) for v in to_val)
                                trigger_info.append(f"{entity} = {to_val}" if to_val else str(entity))
                        results.append({
                            'name': config.get('alias', a['entity_id']),
                            'entity_id': a['entity_id'],
                            'state': a.get('state', ''),
                            'triggers': trigger_info,
                        })
                return jsonify({'ok': True, 'automations': results})
            except requests.exceptions.RequestException as e:
                return jsonify({'ok': False, 'error': str(e)}), 502

        def run_flask():
            app.run(host='0.0.0.0', port=CONFIG['web_port'], threaded=True)

        t = threading.Thread(target=run_flask, daemon=True)
        t.start()
        self.logger.info(f"Web UI started on http://0.0.0.0:{CONFIG['web_port']}")

    def start(self):
        """Start the IR bridge."""
        self.logger.info("=" * 60)
        self.logger.info(f"IR → Sony TV Bridge v{VERSION}")
        self.logger.info("=" * 60)

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Setup MQTT
        self._setup_mqtt()

        # Setup input
        if not self._setup_input():
            self.logger.error("Failed to setup input device")
            sys.exit(1)

        self.running = True
        self.stats['status'] = 'running'

        # Publish initial status
        self._publish_status()

        # Start background loops
        status_thread = threading.Thread(target=self._status_loop, daemon=True)
        status_thread.start()

        health_thread = threading.Thread(target=self._health_loop, daemon=True)
        health_thread.start()

        # Start web UI
        self._setup_web()

        self.logger.info("Bridge started successfully")

        # Main input loop
        while self.running:
            try:
                self._read_input()
            except Exception as e:
                self.logger.error(f"Error in input loop: {e}")
                self.stats['errors'] += 1

                if self.running:
                    self.logger.info("Restarting input loop in 5 seconds...")
                    time.sleep(5)

    def _status_loop(self):
        """Background thread to periodically publish status."""
        while self.running:
            self._publish_status()
            time.sleep(60)

    def _health_loop(self):
        """Background thread to periodically publish system health."""
        while self.running:
            self._publish_health()
            time.sleep(60)

    def _get_system_health(self) -> Dict[str, Any]:
        """Gather system metrics using psutil."""
        health = {
            'timestamp': datetime.now().isoformat(),
            'version': VERSION,
            'machine': 'hsb2',
            'cpu': {},
            'memory': {},
            'disk': {},
            'uptime_seconds': 0
        }

        try:
            if PSUTIL_AVAILABLE:
                health['cpu'] = {
                    'percent': psutil.cpu_percent(interval=None),
                    'load_avg': psutil.getloadavg()
                }

                mem = psutil.virtual_memory()
                health['memory'] = {
                    'total_mb': round(mem.total / (1024**2), 1),
                    'available_mb': round(mem.available / (1024**2), 1),
                    'percent_used': mem.percent
                }

                disk = psutil.disk_usage('/')
                health['disk'] = {
                    'total_gb': round(disk.total / (1024**3), 1),
                    'used_gb': round(disk.used / (1024**3), 1),
                    'percent_used': disk.percent
                }

                health['uptime_seconds'] = int(time.time() - psutil.boot_time())
            else:
                self.logger.warning("psutil not available, health metrics skipped")

        except Exception as e:
            self.logger.error(f"Error gathering health metrics: {e}")

        return health

    def _publish_health(self):
        """Publish system health to MQTT."""
        if not self.mqtt_client:
            return

        try:
            health = self._get_system_health()
            self.mqtt_client.publish(
                f"{self.mqtt_topic}/health",
                json.dumps(health),
                retain=False
            )
        except Exception as e:
            self.logger.error(f"Failed to publish health: {e}")

    def stop(self):
        """Stop the IR bridge."""
        self.logger.info("Stopping IR bridge...")
        self.running = False
        self.stats['status'] = 'stopped'

        # Publish final status
        self._publish_status()

        # Cleanup
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        self.logger.info("IR bridge stopped")


def main():
    """Main entry point."""
    bridge = IRBridge()

    try:
        bridge.start()
    except KeyboardInterrupt:
        bridge.stop()
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
