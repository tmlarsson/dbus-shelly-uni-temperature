"""Parse Shelly Uni /status JSON without D-Bus."""

DEFAULT_POLL_SECONDS = 15
MIN_POLL_SECONDS = 5
DEFAULT_SIGN_OF_LIFE_MINUTES = 5


def probe_temperature_c(status, probe_number):
    """Return tC for a probe, or None if that sensor is missing."""
    if not isinstance(status, dict):
        return None
    ext = status.get("ext_temperature") or {}
    probe = ext.get(str(probe_number))
    if not isinstance(probe, dict) or "tC" not in probe:
        return None
    try:
        return float(probe["tC"])
    except (TypeError, ValueError):
        return None


def probe_connection(status, probe_number):
    """Return (connected, temperature). Disconnected always has temperature None."""
    if not status:
        return 0, None
    temperature = probe_temperature_c(status, probe_number)
    if temperature is None:
        return 0, None
    return 1, temperature


def shelly_serial(status):
    if not isinstance(status, dict):
        return None
    mac = status.get("mac")
    return mac or None


def shelly_firmware(status):
    if not isinstance(status, dict):
        return None
    update = status.get("update") or {}
    return update.get("old_version") or None


def status_url(host):
    host = (host or "").strip()
    if not host:
        raise ValueError("Host is empty")
    return "http://%s/status" % host


def http_auth(username="", password=""):
    """Return a requests-compatible (user, password) tuple, or None."""
    if not (username or password):
        return None
    return (username, password)


def clamp_poll_seconds(raw, default=DEFAULT_POLL_SECONDS, minimum=MIN_POLL_SECONDS):
    try:
        seconds = int(raw) if raw else default
    except (TypeError, ValueError):
        seconds = default
    return max(minimum, seconds)


def clamp_sign_of_life_minutes(raw, default=DEFAULT_SIGN_OF_LIFE_MINUTES):
    try:
        minutes = int(raw) if raw else default
    except (TypeError, ValueError):
        minutes = default
    return max(1, minutes)


def group_services_by_host(services):
    grouped = {}
    for service in services:
        grouped.setdefault(service.host, []).append(service)
    return grouped


class HostFailureTracker:
    """Log a traceback on first host failure, one-liners after that."""

    def __init__(self):
        self._failed = set()

    def note(self, host, ok):
        if ok:
            recovered = host in self._failed
            self._failed.discard(host)
            return "recovered" if recovered else "ok"
        if host in self._failed:
            return "repeat"
        self._failed.add(host)
        return "first"
