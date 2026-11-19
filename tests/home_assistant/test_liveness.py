from custom_components.smarthouse_gaming.liveness import UptimeLiveness

def test_retained_value_not_fresh():
    live = UptimeLiveness()
    assert not live.observe("100", 0)
    assert not live.observe("100", 5)
    assert live.observe("160", 60)
    assert live.observe("160", 149)
    assert not live.observe("160", 150)
    assert live.observe("280", 180)

def test_unavailable_reconnect_and_reboot():
    live = UptimeLiveness()
    assert not live.observe("100", 0)
    assert live.observe("160", 60)
    assert not live.observe("unavailable", 61)
    assert not live.observe("160", 62)
    assert live.observe("220", 120)
    assert live.observe("5", 125)
    assert not live.observe(None, 126)
