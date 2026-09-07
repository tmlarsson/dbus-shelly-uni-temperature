"""Parse Shelly Uni /status JSON without D-Bus or HTTP."""


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


def status_url(host, username="", password=""):
    host = (host or "").strip()
    if not host:
        raise ValueError("Host is empty")
    if username or password:
        return "http://%s:%s@%s/status" % (username, password, host)
    return "http://%s/status" % host


def group_services_by_host(services):
    grouped = {}
    for service in services:
        grouped.setdefault(service.host, []).append(service)
    return grouped
