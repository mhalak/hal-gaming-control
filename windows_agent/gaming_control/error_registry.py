"""Small Windows-side fault registry; caller holds the MQTT bridge lock."""
CODES = frozenset({
    "WIN_CLOCK_DISCONTINUITY", "WIN_INVALID_SYSTEM_METADATA",
    "WIN_INVALID_SNAPSHOT", "WIN_TELEMETRY_PUBLISH_FAILED",
})


class AgentErrors:
    def __init__(self):
        self.active = {}
        self.last_resolved = None

    def report(self, code):
        if code not in CODES:
            raise ValueError("Unknown diagnostic code")
        self.active[code] = min(2**31 - 1, self.active.get(code, 0) + 1)

    def resolve(self, code):
        count = self.active.pop(code, None)
        if count is not None:
            self.last_resolved = {"code": code, "occurrences": count}

    def snapshot(self):
        return {"active": [{"code": code, "occurrences": count}
                           for code, count in sorted(self.active.items())],
                "last_resolved": self.last_resolved}
