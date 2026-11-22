"""Exact, gated retirement of obsolete activity entities after v2 cutover.

This module has no startup side effects. A coordinator migration must verify
a complete v2 source, de-advertised old Windows topics and rollback safety
before calling async_retire. Shared Recorder history is not touched here.
"""
import re

from homeassistant.components import mqtt
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_RETIRED = (("sensor", "current_game"),
            ("binary_sensor", "in_game"),
            ("binary_sensor", "gaming_active"))
# MQTT previously owned an additional Active game discovery entry. The new HA
# integration owns that sensor; NEVER include it in scoped registry removals.
_NATIVE_RETIRED = _RETIRED + (("sensor", "active_game"),)


class RetirementBlocked(RuntimeError):
    """No destructive activity-entity cleanup without complete cutover."""


def exact_legacy_topics(device_id, discovery_prefix="homeassistant"):
    """Only exact, recognized agent-owned MQTT discovery config topics."""
    if (not isinstance(device_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", device_id) is None
            or not isinstance(discovery_prefix, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}(?:/[A-Za-z0-9_-]{1,64})*",
                            discovery_prefix) is None):
        raise RetirementBlocked("Untrusted discovery scope")
    return tuple(
        f"{discovery_prefix}/{component}/smarthouse_gaming_{device_id}_{key}/config"
        for component, key in _NATIVE_RETIRED)


def owned_direct_entities(entries, entry_id, device_id):
    """Resolve only exact registered entities owned by THIS HA config entry."""
    owned = []
    for entity in entries:
        if entity.config_entry_id != entry_id or entity.platform != DOMAIN:
            continue
        for component, key in _RETIRED:
            if (entity.unique_id == f"{device_id}_{key}"
                    and entity.entity_id.startswith(component + ".")):
                owned.append(entity.entity_id)
    return tuple(owned)


async def async_retire(hass, entry, *, v2_cutover_verified,
                       legacy_discovery_stopped, discovery_prefix="homeassistant"):
    """Retire known owned entries only after both independent gates are met.

    Do not call until production no longer reads the retired activity sensors.
    A v1 Windows agent which republishes legacy topics blocks this cleanup.
    """
    if not (v2_cutover_verified is True and legacy_discovery_stopped is True):
        raise RetirementBlocked("Foreground cutover or old agent not verified")
    if not mqtt.is_connected(hass):
        raise RetirementBlocked("Cannot retire discovery while broker offline")
    topics = exact_legacy_topics(entry.data["device_id"], discovery_prefix)
    registry = er.async_get(hass)
    scoped = owned_direct_entities(
        er.async_entries_for_config_entry(registry, entry.entry_id),
        entry.entry_id, entry.data["device_id"])
    # Native MQTT registry entries are owned by MQTT, not this integration.
    # Their lifecycle is triggered by exact retained discovery tombstones.
    for topic in topics:
        await mqtt.async_publish(hass, topic, "", qos=1, retain=True)
    for entity_id in scoped:
        registry.async_remove(entity_id)
    return {"retired_topics": topics, "retired_scoped": scoped}
