"""Parse Shelly Uni /status JSON without D-Bus."""

DEFAULT_POLL_SECONDS = 15
MIN_POLL_SECONDS = 5
DEFAULT_SIGN_OF_LIFE_MINUTES = 5


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def probe_temperature_c(status, probe_number):
    """Return tC for a Uni probe index, or None if that sensor is missing."""
    if not isinstance(status, dict):
        return None
    ext = status.get("ext_temperature") or {}
    probe = ext.get(str(probe_number))
    if not isinstance(probe, dict) or "tC" not in probe:
        return None
    return _as_float(probe.get("tC"))


def probes_from_uni(status):
    """Map Uni probe index and DS18B20 hwID to tC. Missing readings are omitted."""
    probes = {}
    if not isinstance(status, dict):
        return probes
    ext = status.get("ext_temperature") or {}
    if not isinstance(ext, dict):
        return probes
    for key, probe in ext.items():
        if not isinstance(probe, dict) or "tC" not in probe:
            continue
        temperature = _as_float(probe.get("tC"))
        if temperature is None:
            continue
        probes[str(key)] = temperature
        hw_id = probe.get("hwID")
        if hw_id:
            probes[str(hw_id)] = temperature
    return probes


def _component_list(payload):
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("components"), list):
        return payload["components"]
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("components"), list):
        return result["components"]
    return []


def probes_from_pill(payload):
    """Map Pill temperature component ids to tC.

    A present component with no reading (null tC or errors) is stored as None
    so the driver can show it disconnected. Names are not used as ids.
    """
    probes = {}
    for component in _component_list(payload):
        if not isinstance(component, dict):
            continue
        key = str(component.get("key") or "")
        if not key.startswith("temperature:"):
            continue
        status = component.get("status") if isinstance(component.get("status"), dict) else {}
        config = component.get("config") if isinstance(component.get("config"), dict) else {}
        component_id = status.get("id", config.get("id"))
        if component_id is None:
            continue
        if status.get("errors") or status.get("tC") is None:
            temperature = None
        else:
            temperature = _as_float(status.get("tC"))
        probes[str(component_id)] = temperature
        for field in ("addr", "address", "hwID", "hwid", "rom"):
            for source in (config, status):
                value = source.get(field)
                if value:
                    probes[str(value)] = temperature
    return probes


def lookup_probe(probes, probe_id):
    """Return (connected, temperature). Disconnected always has temperature None."""
    if not isinstance(probes, dict):
        return 0, None
    key = str(probe_id)
    if key not in probes or probes[key] is None:
        return 0, None
    return 1, probes[key]


def probe_connection(status, probe_number):
    """Uni /status lookup by probe index."""
    if not status:
        return 0, None
    return lookup_probe(probes_from_uni(status), probe_number)


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


def pill_serial(info):
    if not isinstance(info, dict):
        return None
    return info.get("mac") or None


def pill_firmware(info):
    if not isinstance(info, dict):
        return None
    return info.get("ver") or None


def _http_host(host):
    host = (host or "").strip()
    if not host:
        raise ValueError("Host is empty")
    return host


def status_url(host):
    return "http://%s/status" % _http_host(host)


def pill_components_url(host):
    return "http://%s/rpc/Shelly.GetComponents?dynamic_only=true" % _http_host(host)


def pill_info_url(host):
    return "http://%s/rpc/Shelly.GetDeviceInfo" % _http_host(host)


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
