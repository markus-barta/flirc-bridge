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
    DEBOUNCE_MS: Debounce time in milliseconds (default: 300)
    RETRY_COUNT: HTTP retry attempts (default: 3)
    RETRY_DELAY: Seconds between retries (default: 1.0)
"""

import os
import sys
import time
import json
import logging
import signal
import threading
from datetime import datetime
from typing import Optional, Dict, Any

import requests
import paho.mqtt.client as mqtt

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
    'debounce_ms': int(os.getenv('DEBOUNCE_MS', '300')),
    'retry_count': int(os.getenv('RETRY_COUNT', '3')),
    'retry_delay': float(os.getenv('RETRY_DELAY', '1.0')),
}

# Sony IRCC command mapping
# Maps Linux input event codes to Sony IRCC Base64 commands
IRCC_CODES = {
    # Numbers
    2: ('num1', 'AAAAAQAAAAEAAAAAAw=='),
    3: ('num2', 'AAAAAQAAAAEAAAABAw=='),
    4: ('num3', 'AAAAAQAAAAEAAAACAw=='),
    5: ('num4', 'AAAAAQAAAAEAAAADAw=='),
    6: ('num5', 'AAAAAQAAAAEAAAAEAw=='),
    7: ('num6', 'AAAAAQAAAAEAAAAFAw=='),
    8: ('num7', 'AAAAAQAAAAEAAAAGAw=='),
    9: ('num8', 'AAAAAQAAAAEAAAAHAw=='),
    10: ('num9', 'AAAAAQAAAAEAAAAIAw=='),
    11: ('num0', 'AAAAAQAAAAEAAAAJAw=='),
    
    # Navigation
    103: ('up', 'AAAAAQAAAAEAAAB0Aw=='),
    108: ('down', 'AAAAAQAAAAEAAAB1Aw=='),
    105: ('left', 'AAAAAQAAAAEAAAA0Aw=='),
    106: ('right', 'AAAAAQAAAAEAAAAzAw=='),
    96: ('enter', 'AAAAAQAAAAEAAABlAw=='),
    28: ('enter', 'AAAAAQAAAAEAAABlAw=='),  # KEY_ENTER alternate
    1: ('back', 'AAAAAQAAAAEAAAAAw=='),
    102: ('home', 'AAAAAQAAAAEAAABgAw=='),
    
    # Volume
    113: ('mute', 'AAAAAQAAAAEAAAAUAw=='),
    114: ('volumedown', 'AAAAAQAAAAEAAAASAw=='),
    115: ('volumeup', 'AAAAAQAAAAEAAAATAw=='),
    
    # Media
    164: ('play', 'AAAAAQAAAAEAAAANAw=='),
    166: ('stop', 'AAAAAQAAAAEAAAAOAw=='),
    168: ('rewind', 'AAAAAQAAAAEAAAA4Aw=='),
    208: ('fastforward', 'AAAAAQAAAAEAAAA5Aw=='),
    163: ('next', 'AAAAAQAAAAEAAAAXAw=='),
    165: ('previous', 'AAAAAQAAAAEAAAAYAw=='),
    
    # System
    44: ('power', 'AAAAAQAAAAEAAAAVAw=='),
    23: ('input', 'AAAAAQAAAAEAAAAlAw=='),
    30: ('actionmenu', 'AAAAAQAAAAEAAAA6Aw=='),
    49: ('netflix', 'AAAAAQAAAAEAAAAMAw=='),
    25: ('youtube', 'AAAAAQAAAAEAAABDAw=='),
    
    # Color buttons
    19: ('red', 'AAAAAQAAAAEAAAATAw=='),
    34: ('green', 'AAAAAQAAAAEAAAAUAw=='),
    21: ('yellow', 'AAAAAQAAAAEAAAAVAw=='),
    48: ('blue', 'AAAAAQAAAAEAAAAWAw=='),
    
    # Channel
    20: ('channelup', 'AAAAAQAAAAEAAAA+Aw=='),
    47: ('channeldown', 'AAAAAQAAAAEAAAA9Aw=='),
    17: ('hdmi1', 'AAAAAQAAAAEAAABAAw=='),
    22: ('hdmi2', 'AAAAAQAAAAEAAABBAw=='),
}


class IRBridge:
    """Main IR Bridge class handling input, TV control, and MQTT."""
    
    def __init__(self):
        self.logger = self._setup_logging()
        self.mqtt_client: Optional[mqtt.Client] = None
        self.input_device: Optional[Any] = None
        self.running = False
        self.last_key_time: Dict[int, float] = {}
        self.stats = {
            'started_at': datetime.now().isoformat(),
            'keys_pressed': 0,
            'commands_sent': 0,
            'errors': 0,
            'last_command': None,
            'last_key': None,
            'status': 'initializing'
        }
        
        # Validate configuration
        if not CONFIG['sony_tv_psk']:
            self.logger.error("SONY_TV_PSK environment variable not set!")
            sys.exit(1)
    
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
        """Setup MQTT connection."""
        try:
            self.mqtt_client = mqtt.Client()
            
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
            
            # Start network loop in background thread
            self.mqtt_client.loop_start()
            
            self.logger.info(f"MQTT connected to {CONFIG['mqtt_broker']}:{CONFIG['mqtt_port']}")
            return True
            
        except Exception as e:
            self.logger.error(f"MQTT connection failed: {e}")
            return False
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connect callback."""
        if rc == 0:
            self.logger.info("MQTT connected successfully")
            # Subscribe to control topics
            client.subscribe(f"{CONFIG['mqtt_topic']}/control")
            # Publish birth message
            self._publish_status()
        else:
            self.logger.error(f"MQTT connection failed with code {rc}")
    
    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback."""
        self.logger.warning(f"MQTT disconnected (rc={rc})")
    
    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT message callback."""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            
            if topic.endswith('/control'):
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
                f"{CONFIG['mqtt_topic']}/status",
                json.dumps(self.stats),
                retain=True
            )
            
            self.logger.debug("Status published to MQTT")
            
        except Exception as e:
            self.logger.error(f"Failed to publish status: {e}")
    
    def _publish_event(self, key_name: str, key_code: int, command_name: str, success: bool):
        """Publish key event to MQTT."""
        if not self.mqtt_client:
            return
        
        try:
            event = {
                'timestamp': datetime.now().isoformat(),
                'key_name': key_name,
                'key_code': key_code,
                'command': command_name,
                'success': success,
                'tv_ip': CONFIG['sony_tv_ip']
            }
            
            self.mqtt_client.publish(
                f"{CONFIG['mqtt_topic']}/event",
                json.dumps(event)
            )
            
        except Exception as e:
            self.logger.error(f"Failed to publish event: {e}")
    
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
        
        for attempt in range(CONFIG['retry_count']):
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
                
            if attempt < CONFIG['retry_count'] - 1:
                time.sleep(CONFIG['retry_delay'])
        
        return False
    
    def _handle_key(self, key_code: int):
        """Handle a key press event."""
        now = time.time() * 1000  # Current time in milliseconds
        
        # Check debounce
        if key_code in self.last_key_time:
            elapsed = now - self.last_key_time[key_code]
            if elapsed < CONFIG['debounce_ms']:
                self.logger.debug(f"Key {key_code} debounced ({elapsed:.0f}ms)")
                return
        
        self.last_key_time[key_code] = now
        
        # Lookup command
        if key_code not in IRCC_CODES:
            self.logger.debug(f"Unknown key code: {key_code}")
            return
        
        command_name, ircc_code = IRCC_CODES[key_code]
        
        self.logger.info(f"Key pressed: {command_name} (code: {key_code})")
        self.stats['keys_pressed'] += 1
        self.stats['last_key'] = command_name
        
        # Send to TV
        success = self._send_ircc_command(ircc_code, command_name)
        
        if success:
            self.stats['commands_sent'] += 1
            self.stats['last_command'] = command_name
        else:
            self.stats['errors'] += 1
        
        # Publish event
        self._publish_event(command_name, key_code, command_name, success)
    
    def _setup_input(self) -> bool:
        """Setup input device (FLIRC)."""
        if not EVDEV_AVAILABLE:
            self.logger.warning("evdev not available, running in simulation mode")
            return True
        
        try:
            self.input_device = InputDevice(CONFIG['flirc_device'])
            self.logger.info(f"Input device opened: {self.input_device.name}")
            self.logger.info(f"Device path: {CONFIG['flirc_device']}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to open input device: {e}")
            return False
    
    def _read_input(self):
        """Read and process input events."""
        if not EVDEV_AVAILABLE or not self.input_device:
            self.logger.warning("Input device not available, simulating...")
            # Simulation mode - just publish status periodically
            while self.running:
                self._publish_status()
                time.sleep(30)
            return
        
        try:
            self.logger.info("Starting input event loop")
            
            for event in self.input_device.read_loop():
                if not self.running:
                    break
                
                # Only process key press events (not release or hold)
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    if key_event.keystate == key_event.key_down:
                        self._handle_key(key_event.scancode)
                        
        except Exception as e:
            self.logger.error(f"Input read error: {e}")
            self.stats['errors'] += 1
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.stop()
    
    def start(self):
        """Start the IR bridge."""
        self.logger.info("=" * 60)
        self.logger.info("IR → Sony TV Bridge Starting")
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
        
        # Start status publishing thread
        status_thread = threading.Thread(target=self._status_loop)
        status_thread.daemon = True
        status_thread.start()
        
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
            time.sleep(60)  # Publish status every minute
    
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
