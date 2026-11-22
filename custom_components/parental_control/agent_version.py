"""Independent diagnostics for installed HA and reported Windows versions."""
import json
from pathlib import Path
import re
from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory
from .const import ROOT
from .entity import GamingEntity
from .protocol import parse_discovery
from .update_protocol import version_tuple


class AgentVersionSensor(GamingEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:tag-outline"
    _attr_native_value = None
    _attr_extra_state_attributes = {"version_source": "last_reported"}

    def __init__(self, coordinator):
        super().__init__(coordinator, "agent_version", "Windows agent version")
        self.topic = f"{ROOT}/{coordinator.device_id}/discovery"
        self._attr_extra_state_attributes = {"version_source": "last_reported", "build_sha": None}

    @property
    def available(self):
        # Retained metadata describes the last reported installation, not
        # whether the PC is currently online. Keep it useful while offline.
        return True

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(await mqtt.async_subscribe(
            self.hass, self.topic, self._metadata, qos=1))

    @callback
    def _metadata(self, message):
        if message.topic != self.topic:
            return
        version = sha = None
        try:
            if not isinstance(message.payload, (str, bytes)) or len(message.payload) > 65536:
                raise ValueError("Invalid metadata")
            parse_discovery(message.topic, message.payload)
            data = json.loads(message.payload)
            version = data["agent_version"]
            version_tuple(version)
            sha = _sha(data.get("agent_build_sha"))
        except (ValueError, TypeError, KeyError):
            version = None
        self._attr_native_value = version
        self._attr_extra_state_attributes = {
            "version_source": "last_reported", "build_sha": sha if version else None}
        self.async_write_ha_state()


def _sha(value):
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) else None


def _safe_json(path):
    try:
        if path.stat().st_size > 8192:
            return None
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate metadata key")
                result[key] = value
            return result
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, TypeError, ValueError):
        return None


class IntegrationVersionSensor(GamingEntity, SensorEntity):
    """Installed manifest version, with SHA only for explicitly staged packages."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:tag-outline"

    def __init__(self, coordinator, root=None):
        super().__init__(coordinator, "integration_version", "HA integration version")
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent
        self._attr_native_value = None
        self._attr_extra_state_attributes = {"build_sha": None}

    @property
    def available(self):
        return True

    @staticmethod
    def _local_identity(root):
        manifest = _safe_json(root / "manifest.json")
        if not isinstance(manifest, dict):
            return None, None
        version = manifest.get("version")
        try:
            version_tuple(version)
        except (ValueError, TypeError):
            return None, None
        metadata = _safe_json(root / "build-info.json")
        sha = None
        if (isinstance(metadata, dict)
                and set(metadata) == {"release", "component", "version", "commit"}
                and isinstance(metadata.get("release"), str)
                and metadata["release"].strip()
                and metadata.get("component") == "home_assistant"
                and metadata.get("version") == version):
            sha = _sha(metadata.get("commit"))
        return version, sha

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        version, sha = await self.hass.async_add_executor_job(self._local_identity, self.root)
        self._attr_native_value = version
        self._attr_extra_state_attributes = {"build_sha": sha}
        self.async_write_ha_state()
