"""HA-owned confirmed gaming accounting from unified MQTT v3 only."""
import json
import logging
from time import monotonic
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from datetime import timedelta
from .const import DEFAULTS, DOMAIN, SCAN_SECONDS
from .direct_mqtt import direct_mode
from .foreground_source import ForegroundSource
from .foreground_store import ForegroundStore, ForegroundStoreError
from .foreground_cutover import async_activate_cutover
from .screen_idle_bonus import maybe_add_screen_idle_grant
from .unlimited_bonus import unlimited_credits, record_override
from .rule_engine import violations
from .targeted_action import TargetedTermination
from .popup_control import PopupControl

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
        # Manual buttons use the advertised action capabilities; no auto-enforcement.
        self.advertised = entry.data["actions"]
        self.foreground = None
        self.foreground_store = None
        self.cutover_since = None
        self.storage_healthy = False
        self._saved_segments = ()
        self._save_task = None
        self.termination = TargetedTermination(self)
        self.popup = PopupControl(self)

    @staticmethod
    def policy_snapshot(options):
        # All gaming settings are read live. Only catalog changes need a reload.
        return {"update_catalog_url": options.get("update_catalog_url", ""),
                "tracked_apps": json.dumps(options.get("tracked_apps", []), sort_keys=True)}


    async def async_start_foreground(self):
        """Activate durable HA accounting and unified v3 monitoring."""
        self.cutover_since = await async_activate_cutover(
            self.hass, self.entry.entry_id, self.device_id)
        store = ForegroundStore(self.hass, self.entry.entry_id, self.device_id)
        segments = await store.async_load(self.cutover_since)
        if self.options.get("unlimited") and not self.options.get("gaming_suspended"):
            updated = record_override(self.entry.options, self.device_id, dt_util.now(), True)
            if updated != self.entry.options and self.hass.config_entries.async_update_entry(
                    self.entry, options=updated) is False:
                raise ForegroundStoreError("Unlimited journal migration could not be saved")
        self.foreground_store = store
        self._saved_segments = segments
        self.storage_healthy = True
        self.foreground = ForegroundSource(
            self.hass, self.device_id,
            self.entry.options.get("tracked_apps", []),
            self._live_foreground_changed, intervals=segments,
            on_screen_off=self._screen_off)
        try:
            await self.foreground.async_start()
        except BaseException:
            self.foreground.close()
            self.foreground = None
            raise

    @callback
    def _screen_off(self, event, confirmed_segments):
        """Offer an idempotent daily grant only from verified measured game time."""
        if not self.storage_healthy or self.foreground is None:
            return
        try:
            updated = maybe_add_screen_idle_grant(
                self.entry.options, self.device_id, event,
                confirmed_segments, dt_util.now())
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid Screen idle bonus receipt for device %s",
                            self.device_id)
            return
        if updated is not self.entry.options:
            # Synchronous HA config-entry write: no queued overlapping OFF
            # callbacks and no separate unsynchronized local cache.
            if self.hass.config_entries.async_update_entry(
                    self.entry, options=updated) is False:
                _LOGGER.error("Screen idle bonus could not be persisted for %s",
                              self.device_id)

    @callback
    def _live_foreground_changed(self):
        """A sample may advance verified time; never persist an inferred gap."""
        if self.foreground is None:
            return
        if self._save_task is None or self._save_task.done():
            self._save_task = self.hass.async_create_task(self._async_flush_confirmed())
        # Live state must not wait for coordinator's debounced periodic refresh.
        self.async_set_updated_data(self._foreground_data(dt_util.now()))

    async def _async_flush_confirmed(self):
        if self.foreground is None or not self.storage_healthy:
            return
        current = self.foreground.export_segments()
        if current == self._saved_segments:
            return
        try:
            await self.foreground_store.async_save(self.cutover_since, current)
        except ForegroundStoreError:
            _LOGGER.error("Cannot persist verified foreground intervals for %s",
                          self.device_id)
            self.storage_healthy = False
            self.hass.async_create_task(self.async_request_refresh())
        else:
            self._saved_segments = current

    async def async_stop_foreground(self):
        """Stop incoming samples, then flush the last confirmed checkpoint."""
        if self.foreground is None:
            return
        self.foreground.close()
        if self._save_task is not None:
            await self._save_task
        await self._async_flush_confirmed()
        self.foreground = None

    def _foreground_data(self, now):
        """Production path: never consult legacy current_game/process presence."""
        alias = self.foreground.current(monotonic())
        raw = self.foreground.totals(now)
        names = {row["name"]: raw["per_game"].get(key, 0)
                 for key, row in self.foreground.ledger.apps.items()}
        totals = dict(raw, per_game=names)
        ready = self.storage_healthy and alias is not None
        try:
            credits = unlimited_credits(self.entry.options, self.device_id, now,
                                       self.foreground.export_segments())
            credits["per_game"] = {row["name"]: credits["per_game"].get(key, 0)
                                   for key, row in self.foreground.ledger.apps.items()}
            totals["unlimited_bonus"] = credits
        except ValueError:
            ready = False  # Corrupt journal cannot silently erase or fabricate allowances.
        active = [alias] if ready and alias != "idle" else []
        # Confirmed intervals are a lower bound; gaps are never known idle.
        # The restriction signal is policy-only; never publish a command here.
        reasons = violations(self.options, totals, now, active, device_id=self.device_id) if ready else None
        return {"ready": ready, "online": ready, "active_game": alias if ready else None,
                # UI-only fresh Windows observation: may remain Roblox while
                # screen OFF forces the independent accounting game to idle.
                "observed_game": self.foreground.observed_game if ready else None,
                "totals": totals if ready else {}, "recorded_totals": totals,
                "coverage_incomplete": True, "cutover_since": self.cutover_since,
                "reasons": reasons, "active": active,
                "unified_telemetry": True,
                "display_details": self.foreground.display_details,
                "uptime_seconds": self.foreground.system_uptime}

    def restriction_violation(self):
        """Reevaluate live policy and verified accounting immediately."""
        if self.foreground is None or not self.storage_healthy:
            return None, []
        data = self._foreground_data(dt_util.now())
        if not data["ready"] or not data["active"] or not data["reasons"]:
            return None, []
        return data["active_game"], data["reasons"]

    @property
    def options(self):
        return DEFAULTS | {k: v for k, v in self.entry.options.items() if k not in {"weekend_total", "weekend_daily",
                    "screen_idle_enabled", "screen_idle_acknowledged"}}

    def entity_id(self, domain, key):
        registry = er.async_get(self.hass)
        if self.direct:
            return registry.async_get_entity_id(domain, DOMAIN, f"{self.device_id}_{key}")
        return registry.async_get_entity_id(domain, "mqtt", f"smarthouse_gaming_{self.device_id}_{key}")

    async def _async_update_data(self):
        """Never replay old scalar MQTT/Recorder game or uptime observations."""
        if self.foreground is None:
            # Setup has not established a valid unified v3 reader. No backup
            # monitoring source exists after this breaking clean cut.
            return {"ready": False, "online": False}
        return self._foreground_data(dt_util.now())

    @callback
    def close(self):
        self.termination.close()
        self.popup.close()
        if self.foreground is not None:
            self.foreground.close()
