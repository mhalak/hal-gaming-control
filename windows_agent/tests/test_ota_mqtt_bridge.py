"""Issue #166: agent MQTT staging adapter must be opt-in and never install."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import paho.mqtt.client as mqtt
import pytest

from gaming_control.mqtt_bridge import Bridge
from gaming_control.ota_staging import encode_chunk

DEVICE = "pc_1"
ROOT = f"SmartHouse/Gaming/{DEVICE}"
DATA = b"ota-package" * 9000
TID = "b" * 32
CONFIG = {"device": {"id": DEVICE, "name": "Windows PC"},
          "mqtt": {"host": "localhost"}, "games": [],
          "update": {"enabled": True, "mqtt_staging_enabled": True}}


def connected(root, config=CONFIG):
    b = Bridge(config, ota_root=root)
    b.client = Mock()
    b.client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    return b


def offer(data=DATA, transfer_id=TID):
    import time
    return json.dumps({
        "protocol": 1, "device_id": DEVICE, "transfer_id": transfer_id,
        "version": "0.2.10", "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "chunk_size": 65536,
        "expires_at": int(time.time()) + 90,
    })


def packet(b, suffix, data, retain=False):
    b.on_message(b.client, None, SimpleNamespace(
        topic=b.root + "/ota/" + suffix, payload=data, retain=retain))


def responses(b):
    return [json.loads(x.args[1]) for x in b.client.publish.call_args_list
            if x.args[0] == ROOT + "/ota/ack"]


def test_ota_transport_is_disabled_by_default(tmp_path):
    c = {k: v for k, v in CONFIG.items() if k != "update"}
    b = connected(tmp_path, c)
    assert b.ota is None
    assert not any("/ota/" in x.args[0] for x in b.client.subscribe.call_args_list)
    packet(b, "start", offer())
    assert not list(tmp_path.iterdir())
    assert responses(b) == []


def test_enable_requires_provisioned_updater_and_protected_dir(tmp_path):
    with pytest.raises(ValueError, match="updater"):
        Bridge(CONFIG | {"update": {"enabled": False, "mqtt_staging_enabled": True}},
               ota_root=tmp_path)
    with pytest.raises(ValueError, match="staging"):
        Bridge(CONFIG, ota_root=tmp_path / "does_not_exist")
    with pytest.raises(ValueError, match="staging"):
        Bridge(CONFIG)


def test_opted_receiver_subscribes_exact_topics_and_advertises_capability(tmp_path):
    b = connected(tmp_path)
    assert b.metadata["mqtt_ota_protocol"] == 1
    topics = {c.args[0] for c in b.client.subscribe.call_args_list}
    assert {ROOT + "/ota/" + name for name in ("start", "chunk", "finish")} <= topics
    for c in b.client.subscribe.call_args_list:
        if "/ota/" in c.args[0]:
            assert c.kwargs["options"].retainAsPublished is True
            assert c.kwargs["options"].retainHandling == 2
            assert c.kwargs["options"].qos == 1
    assert ROOT + "/command/update" in b.command_topics


def test_actual_mqtt_stream_only_stages_and_acks(tmp_path):
    b = connected(tmp_path)
    packet(b, "start", offer())
    assert responses(b)[-1]["status"] == "receiving"
    chunks = [DATA[:65536], DATA[65536:]]
    for index, chunk in enumerate(chunks):
        packet(b, "chunk", encode_chunk(TID, index, chunk))
        assert responses(b)[-1]["next_index"] == index + 1
        assert responses(b)[-1]["status"] == "receiving"
    packet(b, "chunk", encode_chunk(TID, 1, chunks[1]))  # QoS 1 duplicate
    assert responses(b)[-1]["next_index"] == 2
    packet(b, "finish", json.dumps({"protocol": 1, "device_id": DEVICE,
                                    "transfer_id": TID}).encode())
    assert responses(b)[-1]["status"] == "staged"
    assert (tmp_path / f"ota-{TID}.staged").read_bytes() == DATA
    assert not list(b.drain_commands())  # no auto-install command
    for c in b.client.publish.call_args_list:
        if c.args[0].endswith("/ota/ack"):
            assert c.kwargs["qos"] == 1 and c.kwargs["retain"] is False


def test_retained_wrong_device_and_bad_payload_never_stage(tmp_path):
    b = connected(tmp_path)
    packet(b, "start", offer(), retain=True)
    packet(b, "start", offer().replace(DEVICE, "pc_2"))
    packet(b, "chunk", encode_chunk(TID, 0, DATA[:65536]))
    assert not list(tmp_path.glob("*.staged"))
    assert not list(tmp_path.glob("*.part"))
    packet(b, "start", offer())
    packet(b, "chunk", encode_chunk("c"*32, 0, DATA[:65536]))
    assert responses(b)[-1]["status"] == "receiving"
    assert responses(b)[-1]["next_index"] == 0
    packet(b, "chunk", encode_chunk(TID, 0, DATA[:65536]), retain=True)
    assert responses(b)[-1]["next_index"] == 0


def test_connection_loss_cancels_partial_upload_without_replay(tmp_path):
    b = connected(tmp_path)
    packet(b, "start", offer())
    packet(b, "chunk", encode_chunk(TID, 0, DATA[:65536]))
    assert list(tmp_path.glob("*.part"))
    b.on_disconnect(b.client, None, None, None, None)
    assert not list(tmp_path.glob("*.part"))
    packet(b, "chunk", encode_chunk(TID, 1, DATA[65536:]))
    assert not list(tmp_path.glob("*.staged"))
    b.on_connect(b.client, None, None, SimpleNamespace(is_failure=False), None)
    packet(b, "chunk", encode_chunk(TID, 1, DATA[65536:]))
    assert not list(tmp_path.glob("*.staged"))


def test_no_status_contains_local_paths_secrets_or_archive_bytes(tmp_path):
    b = connected(tmp_path)
    packet(b, "start", offer())
    raw = [x.args[1] for x in b.client.publish.call_args_list
           if x.args[0].endswith("/ota/ack")]
    assert raw
    for item in raw:
        assert "path" not in item and "password" not in item
        assert str(tmp_path) not in item and "ota-package" not in item
