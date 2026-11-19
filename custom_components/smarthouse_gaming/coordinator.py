"""HA-side enforcement and Recorder-based historical accounting."""
import logging
from time import monotonic
from homeassistant.components import mqtt
from homeassistant.components.recorder import get_instance, history
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from datetime import timedelta
from .const import DEFAULTS, DOMAIN, ROOT, SCAN_SECONDS, RETRY_SECONDS
from .action_registry import ACTION_REGISTRY, selected_actions
from .protocol import games_from_state
from .liveness import UptimeLiveness, MAX_HEARTBEAT_AGE
from .coverage import heartbeat_intervals, covered_transitions
from .direct_mqtt import direct_mode
from .rule_engine import calculate, violations, windows

_LOGGER = logging.getLogger(__name__)

class GamingCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_{entry.data['device_id']}",
                         config_entry=entry, update_interval=timedelta(seconds=SCAN_SECONDS))
        self.entry = entry
        self.policy_options = self.policy_snapshot(entry.options)
        self.policy_data = dict(entry.data)
        self.device_id = entry.data["device_id"]
        self.direct = direct_mode(hass)
        self.games = entry.data["games"]
        self.advertised = entry.data["actions"]
        self.source = None
        self.uptime_source = None
        self.heartbeats = []
        self.pending_heartbeats = []
        self.unsubscribe = None
        self.transitions = []
        self.pending = []
        self.loaded = False
        self.coverage_start = None
        self.last_action = float("-inf")
        self.last_signature = None
        self.liveness = UptimeLiveness()

    @staticmethod
    def policy_snapshot(options):
        # All gaming settings are read live. Only catalog changes need a reload.
        return {"update_catalog_url": options.get("update_catalog_url", "")}

    @property
    def options(self):
        return DEFAULTS | {k: v for k, v in self.entry.options.items() if k != "weekend_total"}

    def entity_id(self, domain, key):
        registry = er.async_get(self.hass)
        if self.direct:
            return registry.async_get_entity_id(domain, DOMAIN, f"{self.device_id}_{key}")
        return registry.async_get_entity_id(domain, "mqtt", f"smarthouse_gaming_{self.device_id}_{key}")

    @callback
    def _changed(self, event):
        state = event.data.get("new_state")
        value = state.state if state else STATE_UNAVAILABLE
        ts = state.last_changed.timestamp() if state else event.time_fired.timestamp()
        destination = self.pending_heartbeats if event.data.get('entity_id') == self.uptime_source else self.pending
        destination.append((ts, value))
        self.hass.async_create_task(self.async_request_refresh())

    def _read_history(self, source, start, end, anchor=True):
        items = history.state_changes_during_period(self.hass, start, end, source,
            include_start_time_state=anchor, no_attributes=True).get(source, [])
        return [(item.last_changed.timestamp(), item.state) for item in items]

    async def _prepare_source(self, source, uptime_source, now):
        if (self.source, self.uptime_source) != (source, uptime_source):
            if self.unsubscribe:
                self.unsubscribe()
            self.source = source
            self.uptime_source = uptime_source
            self.heartbeats = []
            self.pending_heartbeats = []
            self.liveness.reset()
            self.pending = []
            self.transitions = []
            self.loaded = False
            self.coverage_start = None
            self.unsubscribe = async_track_state_change_event(self.hass, [source, uptime_source], self._changed)
        start = windows(now)["weekly"]
        if self.loaded and self.coverage_start == start:
            return
        # Await the recorder executor rather than querying the database in the event loop.
        snapshot = self.hass.states.get(source)
        uptime_snapshot = self.hass.states.get(uptime_source)
        # Read only actual uptime events, including a heartbeat just before Monday.
        heartbeat_start = start - timedelta(seconds=MAX_HEARTBEAT_AGE)
        recorder = get_instance(self.hass)
        initial = await recorder.async_add_executor_job(self._read_history, source, heartbeat_start, now)
        beats = await recorder.async_add_executor_job(self._read_history, uptime_source, heartbeat_start, now, False)
        if uptime_snapshot and uptime_snapshot.last_changed >= heartbeat_start:
            beats.append((uptime_snapshot.last_changed.timestamp(), uptime_snapshot.state))
        self.heartbeats = sorted(dict(beats + [item for item in self.heartbeats if item[0] >= heartbeat_start.timestamp()]).items())
        if snapshot:
            initial.append((snapshot.last_changed.timestamp(), snapshot.state))
        # Do not extrapolate the previous HA run across a known unavailable snapshot.
        if snapshot is None or snapshot.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            initial.append((now.timestamp(), STATE_UNAVAILABLE))
        # Preserve live transitions across a week boundary: Recorder may not have
        # committed the latest events yet. A live event wins on equal timestamp.
        anchor = heartbeat_start.timestamp()
        combined = initial + self.transitions
        older = [item for item in combined if item[0] <= anchor]
        recent = [item for item in combined if item[0] > anchor]
        if older:
            recent.insert(0, max(older, key=lambda item: item[0]))
        self.transitions = sorted(dict(recent).items())
        self.coverage_start = start
        self.loaded = True

    async def _async_update_data(self):
        now = dt_util.now()
        source = self.entity_id("sensor", "current_game")
        uptime_id = self.entity_id("sensor", "uptime")
        if not source or not uptime_id:
            self.liveness.reset()
            self.last_signature = None
            return {"ready": False, "online": False}
        try:
            await self._prepare_source(source, uptime_id, now)
        except Exception as err:
            raise UpdateFailed("Cannot load Recorder history") from err
        if self.pending:
            # Stable chronological order; preserve the anchor state before the week.
            self.transitions.extend(self.pending)
            self.pending.clear()
            self.transitions.sort(key=lambda x: x[0])
        if self.pending_heartbeats:
            self.heartbeats = sorted(dict(self.heartbeats + self.pending_heartbeats).items())
            self.pending_heartbeats.clear()
        now = dt_util.now()
        current = self.hass.states.get(source)
        in_game_id = self.entity_id("binary_sensor", "in_game")
        in_game = self.hass.states.get(in_game_id) if in_game_id else None
        online = bool(current and current.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
                      and in_game and in_game.state in ("on", "off"))
        active = games_from_state(current.state) if online else frozenset()
        uptime = self.hass.states.get(uptime_id)
        # A retained first observation is not evidence of a live PC. Require
        # a changed uptime value after startup or an unavailable observation.
        fresh = self.liveness.observe(uptime.state if uptime and online else None, monotonic())
        if online and (bool(active) != (in_game.state == "on")):
            # During two separate MQTT state publications, do not enforce inconsistent data.
            online = False
        intervals = heartbeat_intervals(self.heartbeats)
        totals = calculate(covered_transitions(self.transitions, intervals), now, set(self.games) | active)
        reason = violations(self.options, totals, now, active)
        actions = selected_actions(self.advertised, self.options["actions"])
        signature = (tuple(sorted(active)), tuple(reason), tuple(actions))
        if online and fresh and active and reason and actions:
            timestamp = monotonic()
            if signature != self.last_signature or timestamp - self.last_action >= RETRY_SECONDS:
                self.last_signature, self.last_action = signature, timestamp
                for key in actions:
                    # Re-evaluate live settings before each publish; a bonus, slider
                    # or action change may have arrived while awaiting the last publish.
                    latest = self.options
                    if (not violations(latest, totals, now, active)
                            or selected_actions(self.advertised, latest["actions"]) != actions):
                        self.last_signature = None
                        break
                    try:
                        await mqtt.async_publish(self.hass,
                            f"{ROOT}/{self.device_id}/command/{ACTION_REGISTRY[key].topic}",
                            "PRESS", qos=0, retain=False)
                    except Exception:
                        _LOGGER.exception("Action %s failed for %s", key, self.device_id)
        else:
            self.last_signature = None
        return {"ready": True, "online": online and fresh, "totals": totals, "reasons": reason,
                "active": sorted(active)}

    @callback
    def close(self):
        if self.unsubscribe:
            self.unsubscribe()
            self.unsubscribe = None
