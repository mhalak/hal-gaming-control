"""MQTT transport. No decisions about permission, time or schedules."""
import json
import logging
import math
import os
import queue
import re
import secrets
import threading
import time
from uuid import uuid4
import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from .core import COMMANDS
from .update_control import parse_request, installed_version, installed_build_sha
from .discovery import discovery, obsolete_discovery_topics

LOG = logging.getLogger(__name__)
UPTIME_PERIOD = 60
COMMAND_MAX_AGE = 10
STATE_ACK_TIMEOUT = 2
FOREGROUND_PERIOD = 2
FOREGROUND_MAX_AGE = 10
FOREGROUND_CLOCK_SKEW = 2
CANDIDATE_PERIOD = 2
CANDIDATE_EXPIRY = 6

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
        self._foreground_epoch = None
        self._foreground_sequence = 0
        self._foreground_context = None
        self._foreground_last = None
        self._foreground_sent = float('-inf')
        self._candidate_key = self._candidate_token = None
        self._candidate_sent = float('-inf')
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
        self.metadata['agent_build_sha'] = installed_build_sha(self.metadata['agent_version'])
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
            self._foreground_epoch = uuid4().hex
            self._foreground_sequence = 0
            self._foreground_context = None
            self._foreground_last = None
            self._foreground_sent = float('-inf')
            self._candidate_key = self._candidate_token = None
            self._candidate_sent = float('-inf')
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
            self._foreground_context = None
            self._candidate_key = self._candidate_token = None
        
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

    def _refresh_discovery(self):
        self.last.clear()
        self.last_full = float('-inf')
        for topic in obsolete_discovery_topics(self.id, self.prefix):
            self.client.publish(topic, b'', qos=1, retain=True)
        self.client.publish(self.root + '/discovery', json.dumps(self.metadata), qos=1, retain=True)
        for topic, data in self.configs.items():
            self.client.publish(topic, json.dumps(data), qos=1, retain=True)

    @staticmethod
    def _snapshot_values(game_values, uptime, full):
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
        return values

    def _publish_snapshot(self, values, generation, full, now):
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
        return True

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
            self._refresh_discovery()
        now = time.monotonic()
        full = now - self.last_full >= UPTIME_PERIOD
        values = self._snapshot_values(game_values, uptime, full)
        changed = any(self.last.get(k) != v for k, v in values.items())
        if full or changed:
            if not self._publish_snapshot(values, generation, full, now):
                return False
            if initial:
                LOG.info('MQTT initial snapshot acknowledged: game=%s in_game=%s uptime=%s',
                         game_values.get('current_game'), game_values.get('in_game'), uptime)
        return self._same_connection(generation)


    def capture_foreground_context(self):
        """Capture connection identity and clocks before examining foreground."""
        with self.lock:
            if not self.connected:
                return None
            self._foreground_context = (self.generation, time.time(), time.monotonic())
            return self._foreground_context

    def _foreground_pair(self, values):
        game, active = values.get("active_game"), values.get("gaming_active")
        if (game, active) == ("idle", "OFF"):
            return "idle", "OFF"
        if (active == "ON" and isinstance(game, str)
                and game not in ("", "idle", "unknown", "unavailable")
                and " | " not in game and game in self.metadata["games"]):
            return game, "ON"
        return "unknown", "UNKNOWN"

    def _prepare_foreground(self, values, context):
        # Caller holds the bridge lock. A capture is single-use even on failure.
        if context is None or context is not self._foreground_context:
            return None
        self._foreground_context = None
        generation, observed, captured = context
        if not self.connected or generation != self.generation or self.synced_generation != generation:
            return None
        now, wall = time.monotonic(), time.time()
        age = now - captured
        if not (0 <= age < FOREGROUND_MAX_AGE and math.isfinite(observed)
                and abs((wall - observed) - age) <= FOREGROUND_CLOCK_SKEW):
            return None
        expiry = math.floor(FOREGROUND_MAX_AGE - max(age, wall - observed))
        if expiry < 1:
            return None
        pair = self._foreground_pair(values)
        if pair == self._foreground_last and now - self._foreground_sent < FOREGROUND_PERIOD:
            return None
        self._foreground_sequence += 1
        packet = {"version": 1, "device_id": self.id, "epoch": self._foreground_epoch,
                  "sequence": self._foreground_sequence, "observed_at": observed,
                  "active_game": pair[0], "gaming_active": pair[1]}
        return packet, expiry, now

    def _send_foreground(self, packet, expiry, generation):
        if not self._same_connection(generation):
            return False
        try:
            properties = Properties(PacketTypes.PUBLISH)
            properties.MessageExpiryInterval = expiry
            info = self.client.publish(self.root + "/state/foreground_snapshot",
                                       json.dumps(packet), qos=0, retain=False,
                                       properties=properties)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except (RuntimeError, ValueError, OSError):
            return False

    def publish_foreground(self, values, context):
        """Offer live QoS 0 evidence, never retry an old sample or claim delivery."""
        with self.lock:
            prepared = self._prepare_foreground(values, context)
        if prepared is None:
            return False
        packet, expiry, now = prepared
        sent = self._send_foreground(packet, expiry, context[0])
        with self.lock:
            if not self.connected or self.generation != context[0]:
                return False
            if not sent:
                # The next polling iteration can offer a new observation immediately.
                self._foreground_last = None
                return False
            self._foreground_last = (packet["active_game"], packet["gaming_active"])
            self._foreground_sent = now
        return True


    def publish_candidate(self, candidate):
        """Publish only the basename and a rotating opaque token, never PID/path.

        A candidate is advisory, is never retained and expires from the broker.
        It cannot, by itself, authorize enrollment or an agent-side mutation.
        """
        with self.lock:
            if not self.connected or self.synced_generation != self.generation:
                self._candidate_key = self._candidate_token = None
                return False
            if (not isinstance(candidate, tuple) or len(candidate) != 4
                    or not isinstance(candidate[0], str)
                    or len(candidate[0]) > 128
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.'()+-]*\.exe",
                                        candidate[0], re.IGNORECASE)):
                self._candidate_key = self._candidate_token = None
                return False
            now = time.monotonic()
            if candidate != self._candidate_key:
                self._candidate_key = candidate
                self._candidate_token = secrets.token_hex(16)
                self._candidate_sent = float("-inf")
            if now - self._candidate_sent < CANDIDATE_PERIOD:
                return False
            generation, token = self.generation, self._candidate_token
            payload = json.dumps({
                "version": 1, "device_id": self.id, "process": candidate[0],
                "token": token, "observed_at": time.time(),
            })
        if not self._same_connection(generation):
            return False
        try:
            properties = Properties(PacketTypes.PUBLISH)
            properties.MessageExpiryInterval = CANDIDATE_EXPIRY
            info = self.client.publish(
                self.root + "/state/foreground_candidate", payload,
                qos=0, retain=False, properties=properties)
        except (RuntimeError, ValueError, OSError):
            return False
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return False
        with self.lock:
            if (not self.connected or self.generation != generation
                    or self._candidate_token != token):
                return False
            self._candidate_sent = now
        return True

    def stop(self):
        try:
            if self.client.is_connected():
                msg = self.client.publish(self.root + '/availability', 'offline', qos=1, retain=True)
                msg.wait_for_publish(timeout=2)
        finally:
            self.client.disconnect()
            self.client.loop_stop()
