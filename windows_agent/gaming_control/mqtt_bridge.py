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
from .targeted_terminate import TARGET_TTL, parse_target_request
from .ota_mqtt import OtaMqttReceiver
from .update_control import parse_request, installed_version, installed_build_sha
from .discovery import discovery, obsolete_discovery_topics, terminate_discovery_topic

LOG = logging.getLogger(__name__)
UPTIME_PERIOD = 60
COMMAND_MAX_AGE = 10
STATE_ACK_TIMEOUT = 2
FOREGROUND_PERIOD = 2
FOREGROUND_MAX_AGE = 10
FOREGROUND_CLOCK_SKEW = 2
CANDIDATE_PERIOD = 2
CANDIDATE_EXPIRY = 6
RAW_FOREGROUND_PERIOD = 2

def _candidate_process(candidate):
    return (isinstance(candidate, tuple) and len(candidate) == 5
            and isinstance(candidate[0], str) and len(candidate[0]) <= 128
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.'()+-]*\.exe",
                             candidate[0], re.IGNORECASE) is not None)


def _candidate_signature(process, signature):
    if signature is None:
        return True
    if (process.casefold() not in ("java.exe", "javaw.exe")
            or not isinstance(signature, dict)
            or set(signature) != {"kind", "value"}):
        return False
    kind, value = signature["kind"], signature["value"]
    if not isinstance(kind, str) or not isinstance(value, str) or len(value) > 128:
        return False
    patterns = {
        "java_class": r"[a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*)+",
        "java_jar": r"[a-zA-Z0-9][a-zA-Z0-9_.+-]{0,95}\.jar",
        "java_module": r"[a-zA-Z_][a-zA-Z_0-9.]*(?:/[a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*)*)?",
    }
    return kind in patterns and re.fullmatch(
        patterns[kind], value, re.ASCII | (re.IGNORECASE if kind == "java_jar" else 0)
    ) is not None



def _raw_identity_parts(state, candidate):
    """Return safe public identity or reject a malformed foreground state."""
    if state == "foreground":
        if not _candidate_process(candidate) or not _candidate_signature(
                candidate[0], candidate[4]):
            return None
        return candidate[0], candidate[4]
    if state in ("idle", "unknown") and candidate is None:
        return None, None
    return None


def _valid_target_sample(sample_time, now, captured_at):
    return (type(sample_time) in (int, float) and math.isfinite(sample_time)
            and 0 <= now - sample_time <= 1.5
            and 0 <= now - captured_at < TARGET_TTL)

class Bridge:
    def __init__(self, config, *, ota_root=None):
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
        self._raw_sequence = 0
        self._raw_last = None
        self._raw_sent = float('-inf')
        self._raw_candidate = self._raw_receipt = self._target_offer = None
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
        # Until HA->Windows termination is migrated, a rule-free PC must not
        # accept the legacy fixed PRESS command (which targets local rules).
        self._termination_enabled = bool(config.get('games', []))
        self._target_enabled = not self._termination_enabled
        self.advertised_commands = (list(COMMANDS) if self._termination_enabled
                                    else ['lock_pc'])
        self.configs = discovery(self.id, dev['name'], self.prefix,
                                 terminate_enabled=self._termination_enabled)
        self.metadata = {'protocol_version': 1, 'device_id': self.id,
                         'name': dev['name'], 'games': sorted({r['name'] for r in config.get('games', [])}),
                         'actions': list(self.advertised_commands)}
        self.command_topics = {self.root + '/command/' + key: key
                               for key in self.advertised_commands}
        if self._target_enabled:
            self.command_topics[self.root + '/command/terminate_target'] = 'terminate_target'
            self.metadata['targeted_terminate_protocol'] = 1
        self.updates_enabled = config.get('update', {}).get('enabled') is True
        ota_requested = config.get('update', {}).get('mqtt_staging_enabled') is True
        if ota_requested and not self.updates_enabled:
            raise ValueError('MQTT OTA staging requires provisioned updater')
        if ota_requested and ota_root is None:
            raise ValueError('MQTT OTA staging requires protected staging directory')
        self.ota = (OtaMqttReceiver(self.root, self.id, ota_root)
                    if ota_requested else None)
        self.metadata['agent_version'] = installed_version()
        self.metadata['agent_build_sha'] = installed_build_sha(self.metadata['agent_version'])
        self.metadata['remote_update'] = self.updates_enabled
        if self.ota is not None:
            self.metadata['mqtt_ota_protocol'] = 1
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
            self._raw_sequence = 0
            self._raw_last = None
            self._raw_sent = float('-inf')
            self._raw_candidate = self._raw_receipt = self._target_offer = None
        # Do not receive stored retained actions; reject any live retained action as well.
        options = mqtt.SubscribeOptions(qos=0, retainAsPublished=True, retainHandling=2)
        for topic in self.command_topics:
            client.subscribe(topic, options=options)
        if self.ota is not None:
            ota_options = mqtt.SubscribeOptions(
                qos=1, retainAsPublished=True, retainHandling=2)
            for topic in self.ota.topics:
                client.subscribe(topic, options=ota_options)
        client.subscribe(self.prefix + '/status', qos=0)

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        with self.lock:
            self.connected = False
            self.synced_generation = None
            self.generation += 1
            self.refresh_requested = True
            self._foreground_context = None
            self._candidate_key = self._candidate_token = None
            self._raw_last = None
            self._raw_sent = float('-inf')
            self._raw_candidate = self._raw_receipt = self._target_offer = None
            if self.ota is not None:
                self.ota.reset()
        
    def on_message(self, client, userdata, msg):
        with self.lock:
            if msg.topic == self.prefix + '/status':
                if msg.payload == b'online':
                    self.refresh_requested = True
                return
            if self.ota is not None and msg.topic in self.ota.topics:
                if not self.connected or msg.retain:
                    return
                reply = self.ota.handle(msg.topic, msg.payload)
                if reply is not None:
                    client.publish(self.root + '/ota/ack', reply,
                                   qos=1, retain=False)
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
            elif command == 'terminate_target':
                try:
                    request = parse_target_request(msg.payload, self.id, self._foreground_epoch)
                except (ValueError, TypeError):
                    LOG.warning('Invalid targeted terminate request rejected')
                    return
                offer = self._target_offer
                now = time.monotonic()
                if (offer is None or offer['generation'] != self.generation
                        or not 0 <= now - offer['offered_at'] < TARGET_TTL
                        or not secrets.compare_digest(offer['token'], request['token'])):
                    return
                # Consume BEFORE queuing; replay, duplicated requests and queue
                # overflow never give a second chance to kill a process.
                self._target_offer = None
                command = ('terminate_target', {
                    'candidate': offer['candidate'],
                    'sample_time': offer['sample_time'],
                    'offered_at': offer['offered_at'],
                    'received_at': now,
                }, request['request_id'])
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
        if not self._termination_enabled:
            # Retire only our exact previously advertised native MQTT button.
            # Never wildcard-delete discovery or another PC's entities.
            topic = terminate_discovery_topic(self.id, self.prefix)
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



    def publish_raw_foreground(self, state, candidate, context):
        """New HA-owned identity transport; never expose PID or full argv.

        Source v2 intentionally coexists with legacy v1 until HA safely
        migrates its accounting and entities. No Windows game list is used.
        """
        with self.lock:
            if context is None or context is not self._foreground_context:
                return False
            generation, observed, captured = context
            if (not self.connected or self.synced_generation != generation
                    or generation != self.generation):
                return False
            now, wall = time.monotonic(), time.time()
            age = now - captured
            if not (0 <= age < FOREGROUND_MAX_AGE and math.isfinite(observed)
                    and abs((wall - observed) - age) <= FOREGROUND_CLOCK_SKEW):
                return False
            parts = _raw_identity_parts(state, candidate)
            if parts is None:
                return False
            process, signature = parts
            identity = (state, process, json.dumps(signature, sort_keys=True))
            if candidate != self._raw_candidate:
                # A foreground switch to another PID with the same .exe must
                # invalidate the prior process capability immediately.
                self._target_offer = self._raw_receipt = None
            if (identity == self._raw_last and candidate == self._raw_candidate
                    and now - self._raw_sent < RAW_FOREGROUND_PERIOD):
                return False
            self._target_offer = self._raw_receipt = None
            expiry = math.floor(FOREGROUND_MAX_AGE - max(age, wall - observed))
            if expiry < 1:
                return False
            self._raw_sequence += 1
            packet_epoch, packet_seq = self._foreground_epoch, self._raw_sequence
            payload = json.dumps({
                "version": 2, "device_id": self.id,
                "epoch": packet_epoch, "sequence": packet_seq,
                "observed_at": observed, "state": state,
                "process": process, "signature": signature,
            })
        if not self._same_connection(generation):
            return False
        try:
            properties = Properties(PacketTypes.PUBLISH)
            properties.MessageExpiryInterval = expiry
            info = self.client.publish(
                self.root + "/state/foreground_identity", payload,
                qos=0, retain=False, properties=properties)
        except (RuntimeError, ValueError, OSError):
            return False
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return False
        with self.lock:
            if not self.connected or self.generation != generation:
                return False
            self._raw_last = identity
            self._raw_sent = now
            self._raw_candidate = candidate
            self._raw_receipt = {
                'candidate': candidate, 'generation': generation,
                'epoch': packet_epoch, 'sequence': packet_seq,
                'observed_at': observed, 'captured_at': captured,
            }
        return True

    def publish_target_offer(self, candidate, context, *, sample_time):
        """Offer one short-lived capability for the privately verified foreground.

        Only a rules-free agent issues it. No PID, path, session, command line,
        credentials or other local process details cross the MQTT broker.
        """
        if not self._target_enabled:
            return False
        with self.lock:
            receipt = self._raw_receipt
            if (not self.connected or self.synced_generation != self.generation
                    or context is not self._foreground_context or receipt is None
                    or candidate is None or candidate != receipt['candidate']
                    or receipt['generation'] != self.generation):
                self._target_offer = None
                return False
            now = time.monotonic()
            if not _valid_target_sample(sample_time, now, receipt['captured_at']):
                self._target_offer = None
                return False
            if (self._target_offer is not None
                    and self._target_offer['sequence'] == receipt['sequence']):
                return False
            generation, token = self.generation, secrets.token_hex(16)
            offer = {
                'token': token, 'candidate': candidate,
                'sample_time': sample_time, 'offered_at': now,
                'sequence': receipt['sequence'], 'generation': generation,
            }
            payload = json.dumps({
                'version': 1, 'device_id': self.id, 'epoch': receipt['epoch'],
                'sequence': receipt['sequence'],
                'observed_at': receipt['observed_at'],
                'process': candidate[0], 'signature': candidate[4],
                'token': token,
            })
        if not self._same_connection(generation):
            return False
        try:
            props = Properties(PacketTypes.PUBLISH)
            props.MessageExpiryInterval = math.ceil(TARGET_TTL)
            info = self.client.publish(self.root + '/state/terminate_offer',
                                       payload, qos=0, retain=False,
                                       properties=props)
        except (RuntimeError, ValueError, OSError):
            return False
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return False
        with self.lock:
            if (not self.connected or self.generation != generation
                    or self._raw_receipt is not receipt):
                return False
            self._target_offer = offer
        return True

    def publish_target_result(self, request_id, success):
        """An expiring, non-sensitive command outcome, never retained."""
        if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{32}', request_id):
            return False
        with self.lock:
            if not self.connected or self.synced_generation != self.generation:
                return False
            generation = self.generation
        payload = json.dumps({'version': 1, 'device_id': self.id,
                              'request_id': request_id,
                              'outcome': 'terminated' if success else 'rejected'})
        if not self._same_connection(generation):
            return False
        try:
            props = Properties(PacketTypes.PUBLISH)
            props.MessageExpiryInterval = 5
            return self.client.publish(
                self.root + '/state/terminate_result', payload, qos=0,
                retain=False, properties=props).rc == mqtt.MQTT_ERR_SUCCESS
        except (RuntimeError, ValueError, OSError):
            return False

    def publish_candidate(self, candidate):
        """Publish basename, safe signature and opaque token, never PID/path.

        A candidate is advisory, is never retained and expires from the broker.
        It cannot, by itself, authorize enrollment or an agent-side mutation.
        """
        with self.lock:
            if not self.connected or self.synced_generation != self.generation:
                self._candidate_key = self._candidate_token = None
                return False
            if not _candidate_process(candidate) or not _candidate_signature(
                    candidate[0], candidate[4]):
                self._candidate_key = self._candidate_token = None
                return False
            signature = candidate[4]
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
                "signature": signature,
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
