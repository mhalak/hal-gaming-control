"""Use the existing uptime sensor to gate destructive commands."""
MAX_HEARTBEAT_AGE = 90

class UptimeLiveness:
    def __init__(self):
        self.reset()

    def reset(self):
        self.last_value = None
        self.last_progress = None

    def observe(self, value, now):
        """Require an uptime change within 90s, not just a retained initial value."""
        try:
            number = int(value)
            if number < 0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            self.reset()
            return False
        if self.last_value is None:
            self.last_value = number
            return False
        if number != self.last_value:
            self.last_value = number
            self.last_progress = now
        return self.last_progress is not None and now - self.last_progress < MAX_HEARTBEAT_AGE
