"""MQTT transport. No decisions about permission, time or schedules."""
import json
import logging
import os
import queue
import re
import threading
import time
import paho.mqtt.client as mqtt
from .core import COMMANDS
from .update_control import parse_request, installed_version
from .discovery import discovery, obsolete_discovery_topics

LOG = logging.getLogger(__name__)
UPTIME_PERIOD = 60
COMMAND_MAX_AGE = 10
STATE_ACK_TIMEOUT = 2

class Bridge:
    def __init__(self, config):
        dev, cfg = config['device'], config['mqtt']
        self.id = dev['id']
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', self.id):
            raise ValueError('Invalid device id')
        self.root = f'SmartHouse/Gaming/{self.id}'
        self.prefix = cfg.get('discovery_prefix', 'homeassistant')
        self.config = cfg
        self.commands = queue.Queue(maxsize=32)
        self.lock = threading.Lock()
        self.generation = 0
        self.connected = False
        self.synced_generation = None
        self.refresh_requested = True
        self.last = {}
        self.last_full = float('-inf')
        # MQTT 5 preserves the retain flag even on live deliveries.
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f'gaming-{self.id}',
                                  protocol=mqtt.MQTTv5)
        password = cfg.get('password')
        if cfg.get('password_env'):
            password = os.environ[cfg['password_env']]
        if cfg.get('username'):
            self.client.username_pw_set(cfg['username'], password)
        if cfg.get('tls', False):
            self.client.tls_set(ca_certs=cfg.get('ca_certs'))
        self.client.will_set(self.root + '/availability', 'offline', qos=1, retain=True)
        self.client.reconnect_delay_set(1, 60)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.configs = discovery(self.id, dev['name'], self.prefix)
        self.metadata = {'protocol_version': 1, 'device_id': self.id,
                         'name': dev['name'], 'games': sorted({r['name'] for r in config.get('games', [])}),
                         'actions': list(COMMANDS)}
        self.command_topics = {self.root + '/command/' + key: key for key in COMMANDS}
        self.updates_enabled = config.get('update', {}).get('enabled') is True
        self.metadata['agent_version'] = installed_version()
        self.metadata['remote_update'] = self.updates_enabled
        self.metadata['focus_protocol'] = 1
        if self.updates_enabled:
            self.command_topics[self.root + '/command/update'] = 'update'

    def start(self):
        # Clean session, no offline command queue on broker.
        self.client.connect_async(self.config['host'], int(self.config.get('port', 1883)),
                                  30, clean_start=True)
        self.client.loop_start()

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.error('MQTT connect rejected: %s', reason_code)
            return
        with self.lock:
            self.generation += 1
            self.connected = True
            self.synced_generation = None
            self.refresh_requested = True
        # Do not receive stored retained actions; reject any live retained action as well.
        options = mqtt.SubscribeOptions(qos=0, retainAsPublished=True, retainHandling=2)
        for topic in self.command_topics:
            client.subscribe(topic, options=options)
        client.subscribe(self.prefix + '/status', qos=0)

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        with self.lock:
            self.connected = False
            self.synced_generation = None
            self.generation += 1
            self.refresh_requested = True

    def on_message(self, client, userdata, msg):
        with self.lock:
            if msg.topic == self.prefix + '/status':
                if msg.payload == b'online':
                    self.refresh_requested = True
                return
            command = self.command_topics.get(msg.topic)
            if not self.connected or not command or msg.retain:
                return
            if command == 'update':
                try:
                    command = ('update', parse_request(msg.payload))
                except (ValueError, TypeError):
                    LOG.warning('Invalid update request rejected')
                    return
            elif msg.payload != b'PRESS':
                return
            try:
                self.commands.put_nowait((self.generation, time.monotonic(), command))
            except queue.Full:
                LOG.warning('Command queue full; action dropped')

    def drain_commands(self):
        # Drain a bounded number of actions, checking connection generation and age.
        for _ in range(32):
            try:
                generation, received, command = self.commands.get_nowait()
            except queue.Empty:
                return
            with self.lock:
                valid = (self.connected and generation == self.generation and
                         time.monotonic() - received <= COMMAND_MAX_AGE)
            if valid:
                yield command

    def _same_connection(self, generation):
        with self.lock:
            return self.connected and self.generation == generation

    def _retained(self, topic, value, generation):
        """Only commit telemetry after broker acknowledgement in this connection."""
        if not self._same_connection(generation):
            return False
        try:
            info = self.client.publish(topic, str(value), qos=1, retain=True)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                return False
            info.wait_for_publish(timeout=STATE_ACK_TIMEOUT)
            return info.is_published() and self._same_connection(generation)
        except (RuntimeError, ValueError, OSError):
            return False

    def _invalidate(self, generation):
        with self.lock:
            if self.generation != generation:
                return
            self.synced_generation = None
            self.refresh_requested = True
        self._retained(self.root + '/availability', 'offline', generation)
        LOG.warning('MQTT telemetry sync incomplete; retrying full snapshot')

    def publish(self, game_values, uptime):
        """Return True only while current telemetry is synchronized.

        On a fresh connection hide any retained previous state before publishing
        a complete, acknowledged live snapshot. Never announce availability
        after merely queueing unacknowledged sensor messages.
        """
        with self.lock:
            if not self.connected:
                return False
            generation = self.generation
            initial = self.synced_generation != generation
            refresh = self.refresh_requested
            self.refresh_requested = False
        if initial:
            if not self._retained(self.root + '/availability', 'offline', generation):
                self._invalidate(generation)
                return False
        if refresh or initial:
            self.last.clear()
            self.last_full = float('-inf')
            for topic in obsolete_discovery_topics(self.id, self.prefix):
                self.client.publish(topic, b'', qos=1, retain=True)
            self.client.publish(self.root + '/discovery', json.dumps(self.metadata), qos=1, retain=True)
            for topic, data in self.configs.items():
                self.client.publish(topic, json.dumps(data), qos=1, retain=True)
        now = time.monotonic()
        full = now - self.last_full >= UPTIME_PERIOD
        values = dict(game_values)
        if full:
            values['uptime'] = str(uptime)
        # Publish the pair together on a game change, even if one field is
        # unchanged. Partial delivery triggers an offline/full-snapshot retry.
        if 'gaming_active' in values:
            values['focus_availability'] = 'online' if values['gaming_active'] in ('ON', 'OFF') else 'offline'
            if values['focus_availability'] == 'offline':
                # Hide a previously ON native binary sensor before unknown data.
                values = {'focus_availability': 'offline'} | values
        changed = any(self.last.get(k) != v for k, v in values.items())
        if full or changed:
            for key, value in values.items():
                if not self._retained(self.root + '/state/' + key, value, generation):
                    self._invalidate(generation)
                    return False
            if full and not self._retained(self.root + '/availability', 'online', generation):
                self._invalidate(generation)
                return False
            with self.lock:
                if not self.connected or self.generation != generation:
                    return False
                self.last.update(values)
                if full:
                    self.synced_generation = generation
                    self.last_full = now
            if initial:
                LOG.info('MQTT initial snapshot acknowledged: game=%s in_game=%s uptime=%s',
                         game_values.get('current_game'), game_values.get('in_game'), uptime)
        return self._same_connection(generation)

    def stop(self):
        try:
            if self.client.is_connected():
                msg = self.client.publish(self.root + '/availability', 'offline', qos=1, retain=True)
                msg.wait_for_publish(timeout=2)
        finally:
            self.client.disconnect()
            self.client.loop_stop()
