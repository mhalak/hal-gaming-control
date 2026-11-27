"""Per-device dispatch state for verified restriction violations."""

RETRY_INTERVAL = 5.0


class RestrictionDispatch:
    """Rearm on observed recovery; rate-limit retries with new offers only."""

    def __init__(self):
        self._sent = {}

    def should_fire(self, device_id, game, token, now):
        if game is None:
            self._sent.pop(device_id, None)
            return False
        if token is None:
            return False
        previous = self._sent.get(device_id)
        if previous is not None:
            old_game, old_token, sent_at = previous
            if token == old_token:
                return False
            if game == old_game and now - sent_at < RETRY_INTERVAL:
                return False
        self._sent[device_id] = (game, token, now)
        return True

    def prune(self, devices):
        for device_id in self._sent.keys() - devices:
            del self._sent[device_id]
