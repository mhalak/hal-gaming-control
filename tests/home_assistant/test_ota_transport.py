"""HA side of staged-only OTA: ACK/backpressure/retry, no service update."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.hal_gaming_control.ota_transport import (
    HaOtaTransport, OtaTransferError, parse_ack,
)


TID = "d" * 32
PC = "pc1"
ROOT = f"SmartHouse/Gaming/{PC}"


class DummyHass:
    def __init__(self):
        self.executor_calls = 0

    async def async_add_executor_job(self, fn, *args):
        self.executor_calls += 1
        return fn(*args)


class Broker:
    def __init__(self, *, drop_once=None, reject=False, no_finish_ack=False):
        self.callback = None
        self.messages = []
        self.unsubscribe_count = 0
        self.drop_once = drop_once
        self.dropped = False
        self.reject = reject
        self.no_finish_ack = no_finish_ack
        self.next_index = 0
        self.transfer_id = None
        self.inject_retained = False
        self.payloads = []

    async def subscribe(self, hass, topic, callback, *, qos):
        assert qos == 1 and topic == ROOT + "/ota/ack"
        self.callback = callback
        def unsub():
            self.unsubscribe_count += 1
            self.callback = None
        return unsub

    def ack(self, status):
        return json.dumps({"protocol": 1, "device_id": PC,
                           "transfer_id": self.transfer_id,
                           "next_index": self.next_index,
                           "status": status})

    async def publish(self, hass, topic, payload, *, qos, retain):
        assert qos == 1 and retain is False and topic.startswith(ROOT + "/ota/")
        self.messages.append((topic, payload))
        step = topic.rsplit("/", 1)[-1]
        if step == "start":
            obj = json.loads(payload)
            self.transfer_id = obj["transfer_id"]
            status = "receiving"
        elif step == "chunk":
            idx = int.from_bytes(payload[16:20], "big")
            if idx == self.next_index:
                self.payloads.append(payload[20:])
                self.next_index += 1
            assert idx == self.next_index - 1
            status = "receiving"
        else:
            assert step == "finish"
            status = "staged"
        if self.reject and step == "start":
            status = "rejected"
        if self.no_finish_ack and step == "finish":
            return
        if self.drop_once == step and not self.dropped:
            self.dropped = True
            return
        if self.inject_retained:
            self.callback(SimpleNamespace(payload=self.ack(status), retain=True))
        self.callback(SimpleNamespace(payload=self.ack(status), retain=False))


def setup(monkeypatch, broker):
    import custom_components.hal_gaming_control.ota_transport as transport
    monkeypatch.setattr(transport.mqtt, "async_subscribe", broker.subscribe)
    monkeypatch.setattr(transport.mqtt, "async_publish", broker.publish)


@pytest.fixture
def archive(tmp_path):
    target = tmp_path / "agent.zip"
    target.write_bytes(b"A" * 65536 + b"B" * 65536 + b"C" * 23)
    return target


@pytest.mark.asyncio
async def test_ha_streams_to_correct_device_waiting_for_all_ack(monkeypatch, archive):
    broker = Broker()
    setup(monkeypatch, broker)
    hass = DummyHass()
    progress = []
    result = await HaOtaTransport(hass).async_stage_package(
        archive, device_id=PC, version="0.2.10", transfer_id=TID,
        ack_timeout=0.03, retries=2, on_progress=lambda n, total: progress.append((n, total)))
    assert result == {"transfer_id": TID, "version": "0.2.10", "chunks": 3,
                      "status": "staged_unverified"}
    assert [v[0].rsplit("/", 1)[-1] for v in broker.messages] == [
        "start", "chunk", "chunk", "chunk", "finish"]
    assert broker.messages[0][1].find(TID) != -1
    assert b"".join(broker.payloads) == archive.read_bytes()
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert hass.executor_calls >= 4
    assert broker.unsubscribe_count == 1


@pytest.mark.asyncio
async def test_retransmit_byte_identical_unacked_chunk(monkeypatch, archive):
    broker = Broker(drop_once="chunk")
    setup(monkeypatch, broker)
    result = await HaOtaTransport(DummyHass()).async_stage_package(
        archive, device_id=PC, version="0.2.10", transfer_id=TID,
        ack_timeout=0.01, retries=2)
    assert result["status"] == "staged_unverified"
    frames = [payload for topic, payload in broker.messages if topic.endswith("/chunk")]
    assert len(frames) == 4
    assert frames[0] == frames[1]
    assert b"".join(broker.payloads) == archive.read_bytes()


@pytest.mark.asyncio
async def test_retry_idempotent_start(monkeypatch, archive):
    broker = Broker(drop_once="start")
    setup(monkeypatch, broker)
    result = await HaOtaTransport(DummyHass()).async_stage_package(
        archive, device_id=PC, version="0.2.10", transfer_id=TID,
        ack_timeout=0.01, retries=2)
    assert result["status"] == "staged_unverified"
    starts = [p for topic, p in broker.messages if topic.endswith("/start")]
    assert len(starts) == 2 and starts[0] == starts[1]


@pytest.mark.asyncio
async def test_finish_is_not_republished_when_ack_lost(monkeypatch, archive):
    broker = Broker(no_finish_ack=True)
    setup(monkeypatch, broker)
    with pytest.raises(OtaTransferError, match="unconfirmed"):
        await HaOtaTransport(DummyHass()).async_stage_package(
            archive, device_id=PC, version="0.2.10", transfer_id=TID,
            ack_timeout=0.01, retries=3)
    assert len([t for t, _ in broker.messages if t.endswith("/finish")]) == 1
    assert broker.unsubscribe_count == 1


@pytest.mark.asyncio
async def test_agent_rejects_offer_fail_closed(monkeypatch, archive):
    broker = Broker(reject=True)
    setup(monkeypatch, broker)
    with pytest.raises(OtaTransferError, match="rejected"):
        await HaOtaTransport(DummyHass()).async_stage_package(
            archive, device_id=PC, version="0.2.10", transfer_id=TID, ack_timeout=0.01)
    assert not [t for t, _ in broker.messages if t.endswith("/chunk")]
    assert broker.unsubscribe_count == 1


@pytest.mark.asyncio
async def test_unresponsive_pc_is_bounded_and_unsubscribes(monkeypatch, archive):
    broker = Broker(drop_once="start")
    async def ignore(*args, **kwargs):
        return await broker.publish(*args, **kwargs)
    setup(monkeypatch, broker)
    # Disconnect all ACKs from the listener without blocking publish.
    original = broker.publish
    async def no_ack(*args, **kwargs):
        callback = broker.callback
        broker.callback = lambda _: None
        try:
            await original(*args, **kwargs)
        finally:
            broker.callback = callback
    import custom_components.hal_gaming_control.ota_transport as transport
    monkeypatch.setattr(transport.mqtt, "async_publish", no_ack)
    with pytest.raises(OtaTransferError, match="timeout"):
        await HaOtaTransport(DummyHass()).async_stage_package(
            archive, device_id=PC, version="0.2.10", transfer_id=TID,
            ack_timeout=0.01, retries=1)
    assert len([t for t, _ in broker.messages if t.endswith("/start")]) == 2
    assert broker.unsubscribe_count == 1


@pytest.mark.asyncio
async def test_retained_ack_is_never_accepted(monkeypatch, archive):
    broker = Broker()
    broker.inject_retained = True
    setup(monkeypatch, broker)
    assert (await HaOtaTransport(DummyHass()).async_stage_package(
        archive, device_id=PC, version="0.2.10", transfer_id=TID,
        ack_timeout=0.01))["status"] == "staged_unverified"


@pytest.mark.parametrize("bad", [
    {}, [], None, {"protocol": True}, {"protocol": 2},
    {"device_id": "pc2"}, {"transfer_id": "e" * 32},
    {"transfer_id": "D" * 32}, {"next_index": True},
    {"next_index": -1}, {"next_index": 4},
    {"status": "success"}, {"status": 1}, {"extra": "run"},
])
def test_strict_ack_rejects_wrong_fields_types_and_identity(bad):
    good = {"protocol": 1, "device_id": PC, "transfer_id": TID,
            "next_index": 0, "status": "receiving"}
    payload = json.dumps(good | bad) if isinstance(bad, dict) else json.dumps(bad)
    if bad == {}:
        payload = "{}"
    with pytest.raises(ValueError):
        parse_ack(payload, PC, TID, 3)


@pytest.mark.parametrize("raw", [
    '{"protocol":1,"protocol":1}', "{", "a" * 1025, b"\xff",
])
def test_ack_rejects_duplicate_keys_garbage_and_oversized(raw):
    with pytest.raises(ValueError):
        parse_ack(raw, PC, TID, 3)


def test_parse_matching_terminal_and_intermediate_acks():
    obj = {"protocol": 1, "device_id": PC, "transfer_id": TID,
           "next_index": 3, "status": "staged"}
    assert parse_ack(json.dumps(obj), PC, TID, 3) == obj
    obj["status"] = "rejected"
    assert parse_ack(json.dumps(obj), PC, TID, 3)["status"] == "rejected"


@pytest.mark.asyncio
async def test_progress_failure_and_locks_release(monkeypatch, archive):
    broker = Broker()
    setup(monkeypatch, broker)
    sender = HaOtaTransport(DummyHass())
    def fail(*args):
        raise RuntimeError("bad progress callback")
    with pytest.raises(RuntimeError, match="bad progress"):
        await sender.async_stage_package(archive, device_id=PC, version="0.2.10",
                                         transfer_id=TID, on_progress=fail)
    assert broker.unsubscribe_count == 1
    assert (await sender.async_stage_package(archive, device_id=PC, version="0.2.10",
                                              transfer_id="a" * 32))["status"] == "staged_unverified"


@pytest.mark.asyncio
async def test_second_same_device_concurrent_transfer_denied(monkeypatch, archive):
    broker = Broker()
    setup(monkeypatch, broker)
    sender = HaOtaTransport(DummyHass())
    ready = asyncio.Event()
    go = asyncio.Event()
    original = broker.publish
    async def slow(*args, **kwargs):
        if args[2].endswith("/ota/start"):
            ready.set()
            await go.wait()
        await original(*args, **kwargs)
    import custom_components.hal_gaming_control.ota_transport as transport
    monkeypatch.setattr(transport.mqtt, "async_publish", slow)
    task = asyncio.create_task(sender.async_stage_package(
        archive, device_id=PC, version="0.2.10", transfer_id=TID))
    await asyncio.wait_for(ready.wait(), 1)
    with pytest.raises(OtaTransferError, match="already"):
        await sender.async_stage_package(archive, device_id=PC, version="0.2.10",
                                         transfer_id="f" * 32)
    go.set()
    assert (await task)["status"] == "staged_unverified"
