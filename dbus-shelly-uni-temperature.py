#!/usr/bin/env python3

import logging
import os
import platform
import sys
import time

import configparser
import dbus
import requests
from gi.repository import GLib

sys.path.insert(1, "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python")
from vedbus import VeDbusService

from shelly_status import (
    HostFailureTracker,
    clamp_poll_seconds,
    clamp_sign_of_life_minutes,
    group_services_by_host,
    http_auth,
    probe_connection,
    shelly_firmware,
    shelly_serial,
    status_url,
)

HTTP_TIMEOUT_SECONDS = 5
_sessions = {}


class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)


class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)


def dbusconnection():
    return SessionBus() if "DBUS_SESSION_BUS_ADDRESS" in os.environ else SystemBus()


def get_config():
    config = configparser.ConfigParser()
    config.read(os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.ini"))
    return config


def _config_bool(section, key, default=True):
    if key not in section:
        return default
    return section.get(key).strip().lower() in ("1", "true", "yes", "on")


def _session_for_host(host):
    session = _sessions.get(host)
    if session is None:
        session = requests.Session()
        _sessions[host] = session
    return session


def fetch_shelly_status(host, username="", password=""):
    url = status_url(host)
    response = _session_for_host(host).get(
        url,
        timeout=HTTP_TIMEOUT_SECONDS,
        auth=http_auth(username, password),
    )
    response.raise_for_status()
    data = response.json()
    if not data:
        raise ValueError("Empty JSON from %s" % host)
    return data


def require_on_premise(config):
    access_type = "OnPremise"
    for section in config.sections():
        value = config[section].get("AccessType")
        if value:
            access_type = value
            break
    if access_type != "OnPremise":
        raise ValueError("AccessType %s is not supported" % access_type)


class DbusShellyUniService:
    def __init__(self, config, section, productname="Shelly Uni"):
        self._config = config
        self._section = section
        self.host = config[section]["Host"].strip()
        self._probe_number = int(config[section]["ProbeNumber"])
        deviceinstance = int(config[section]["Deviceinstance"])
        customname = config[section]["CustomName"]
        temperature_type = int(config[section].get("TemperatureType", 2))

        service_name = "com.victronenergy.temperature.http_{:02d}".format(deviceinstance)
        self._dbusservice = VeDbusService(service_name, dbusconnection(), register=False)
        self._missing_probe_logged = False
        self._lastUpdate = 0

        logging.info(
            "%s instance=%s probe=%s host=%s",
            section,
            deviceinstance,
            self._probe_number,
            self.host,
        )

        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path(
            "/Mgmt/ProcessVersion",
            "Unknown version, and running on Python " + platform.python_version(),
        )
        self._dbusservice.add_path("/Mgmt/Connection", "Shelly Uni HTTP JSON service")
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        self._dbusservice.add_path("/ProductId", 0xFFFF)
        self._dbusservice.add_path("/ProductName", productname)
        self._dbusservice.add_path("/CustomName", customname, writeable=True)
        self._dbusservice.add_path("/Connected", 0)
        self._dbusservice.add_path("/FirmwareVersion", "")
        self._dbusservice.add_path("/HardwareVersion", 0)
        self._dbusservice.add_path("/Serial", "")
        self._dbusservice.add_path("/UpdateIndex", 0)
        self._dbusservice.add_path(
            "/Temperature",
            None,
            gettextcallback=lambda p, v: "" if v is None else (str(round(v, 2)) + "°C"),
            writeable=False,
        )
        self._dbusservice.add_path("/TemperatureType", temperature_type, writeable=False)
        self._dbusservice.register()

    def apply_status(self, status):
        connected, temperature = probe_connection(status, self._probe_number)
        if not connected:
            if status and not self._missing_probe_logged:
                logging.warning(
                    "%s: Shelly %s has no ext_temperature probe %s",
                    self._section,
                    self.host,
                    self._probe_number,
                )
                self._missing_probe_logged = True
            self._dbusservice["/Connected"] = 0
            self._dbusservice["/Temperature"] = None
            return

        self._missing_probe_logged = False
        serial = shelly_serial(status)
        firmware = shelly_firmware(status)
        if serial:
            self._dbusservice["/Serial"] = serial
        if firmware:
            self._dbusservice["/FirmwareVersion"] = firmware
        self._dbusservice["/Temperature"] = temperature
        self._dbusservice["/Connected"] = 1
        index = self._dbusservice["/UpdateIndex"] + 1
        if index > 255:
            index = 0
        self._dbusservice["/UpdateIndex"] = index
        self._lastUpdate = time.time()


class ShellyUniDriver:
    def __init__(self, config, services):
        self._config = config
        self._services = services
        self._username = config["ONPREMISE"].get("Username", "")
        self._password = config["ONPREMISE"].get("Password", "")
        self._failures = HostFailureTracker()

    def poll_interval_ms(self):
        raw = None
        if self._config.has_option("ONPREMISE", "PollIntervalSeconds"):
            raw = self._config["ONPREMISE"]["PollIntervalSeconds"]
        return clamp_poll_seconds(raw) * 1000

    def sign_of_life_ms(self):
        raw = None
        for service in self._services:
            raw = service._config[service._section].get("SignOfLifeLog")
            if raw:
                break
        return clamp_sign_of_life_minutes(raw) * 60 * 1000

    def tick(self):
        grouped = group_services_by_host(self._services)
        for host, host_services in grouped.items():
            try:
                status = fetch_shelly_status(host, self._username, self._password)
                outcome = self._failures.note(host, True)
                if outcome == "recovered":
                    logging.info("Shelly Uni at %s recovered", host)
            except Exception:
                outcome = self._failures.note(host, False)
                if outcome == "first":
                    logging.exception("Failed to read Shelly Uni at %s", host)
                else:
                    logging.warning("Shelly Uni at %s still unreachable", host)
                status = None
            for service in host_services:
                service.apply_status(status)
        GLib.timeout_add(self.poll_interval_ms(), self.tick)
        return False

    def sign_of_life(self):
        logging.info("--- sign of life ---")
        for service in self._services:
            logging.info(
                "%s connected=%s temperature=%s last_update=%s",
                service._section,
                service._dbusservice["/Connected"],
                service._dbusservice["/Temperature"],
                service._lastUpdate,
            )
        return True


def main():
    logging.basicConfig(
        format="%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO,
        handlers=[logging.StreamHandler()],
    )

    from dbus.mainloop.glib import DBusGMainLoop

    DBusGMainLoop(set_as_default=True)

    config = get_config()
    require_on_premise(config)

    services = []
    for section in config.sections():
        if not section.startswith("DEVICE"):
            continue
        if not _config_bool(config[section], "Enabled", True):
            logging.info("Skipping %s (Enabled=0)", section)
            continue
        services.append(DbusShellyUniService(config=config, section=section))

    if not services:
        logging.error("No enabled DEVICE sections in config.ini")
        sys.exit(1)

    driver = ShellyUniDriver(config, services)
    driver.tick()
    GLib.timeout_add(driver.sign_of_life_ms(), driver.sign_of_life)

    logging.info(
        "Connected to dbus, polling every %ss", driver.poll_interval_ms() // 1000
    )
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
