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

sys.path.insert(
    1,
    os.path.join(
        os.path.dirname(__file__),
        "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python",
    ),
)
from vedbus import VeDbusService

from shelly_status import (
    group_services_by_host,
    probe_temperature_c,
    shelly_firmware,
    shelly_serial,
    status_url,
)

DEFAULT_POLL_SECONDS = 15
HTTP_TIMEOUT_SECONDS = 5


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


def fetch_shelly_status(host, username="", password=""):
    url = status_url(host, username, password)
    response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    if not data:
        raise ValueError("Empty JSON from %s" % host)
    return data


class DbusShellyUniService:
    def __init__(self, config, section, paths, productname="Shelly Uni"):
        self._config = config
        self._section = section
        self.host = config[section]["Host"].strip()
        self._probe_number = int(config[section]["ProbeNumber"])
        deviceinstance = int(config[section]["Deviceinstance"])
        customname = config[section]["CustomName"]
        temperature_type = int(config[section].get("TemperatureType", 2))

        service_name = "com.victronenergy.temperature.http_{:02d}".format(deviceinstance)
        self._dbusservice = VeDbusService(service_name, dbusconnection(), register=False)
        self._paths = paths
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
        self._dbusservice.add_path("/CustomName", customname)
        self._dbusservice.add_path("/Connected", 0)
        self._dbusservice.add_path("/FirmwareVersion", "")
        self._dbusservice.add_path("/HardwareVersion", 0)
        self._dbusservice.add_path("/Serial", "")
        self._dbusservice.add_path("/UpdateIndex", 0)

        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path,
                settings["initial"],
                gettextcallback=settings["textformat"],
                writeable=True,
                onchangecallback=self._handlechangedvalue,
            )
        self._dbusservice["/TemperatureType"] = temperature_type
        self._dbusservice.register()

    def apply_status(self, status):
        if not status:
            self._dbusservice["/Connected"] = 0
            return

        serial = shelly_serial(status)
        firmware = shelly_firmware(status)
        if serial:
            self._dbusservice["/Serial"] = serial
        if firmware:
            self._dbusservice["/FirmwareVersion"] = firmware

        temperature = probe_temperature_c(status, self._probe_number)
        if temperature is None:
            if not self._missing_probe_logged:
                logging.warning(
                    "%s: Shelly %s has no ext_temperature probe %s",
                    self._section,
                    self.host,
                    self._probe_number,
                )
                self._missing_probe_logged = True
            self._dbusservice["/Connected"] = 0
            return

        self._missing_probe_logged = False
        self._dbusservice["/Temperature"] = temperature
        self._dbusservice["/Connected"] = 1
        index = self._dbusservice["/UpdateIndex"] + 1
        if index > 255:
            index = 0
        self._dbusservice["/UpdateIndex"] = index
        self._lastUpdate = time.time()

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s", path, value)
        return True


class ShellyUniDriver:
    def __init__(self, config, services):
        self._config = config
        self._services = services
        self._username = config["ONPREMISE"].get("Username", "")
        self._password = config["ONPREMISE"].get("Password", "")

    def poll_interval_ms(self):
        raw = None
        if self._config.has_option("ONPREMISE", "PollIntervalSeconds"):
            raw = self._config["ONPREMISE"]["PollIntervalSeconds"]
        try:
            seconds = int(raw) if raw else DEFAULT_POLL_SECONDS
        except ValueError:
            seconds = DEFAULT_POLL_SECONDS
        return max(5, seconds) * 1000

    def sign_of_life_ms(self):
        minutes = 5
        for service in self._services:
            value = service._config[service._section].get("SignOfLifeLog")
            if value:
                minutes = int(value)
                break
        return max(1, minutes) * 60 * 1000

    def tick(self):
        grouped = group_services_by_host(self._services)
        statuses = {}
        for host, host_services in grouped.items():
            try:
                statuses[host] = fetch_shelly_status(
                    host, self._username, self._password
                )
            except Exception:
                logging.exception("Failed to read Shelly Uni at %s", host)
                statuses[host] = None
            for service in host_services:
                service.apply_status(statuses[host])
        return True

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
    _c = lambda p, v: "" if v is None else (str(round(v, 2)) + "°C")

    services = []
    for section in config.sections():
        if not section.startswith("DEVICE"):
            continue
        if not _config_bool(config[section], "Enabled", True):
            logging.info("Skipping %s (Enabled=0)", section)
            continue
        services.append(
            DbusShellyUniService(
                config=config,
                section=section,
                paths={
                    "/Temperature": {"initial": None, "textformat": _c},
                    "/TemperatureType": {"initial": 2, "textformat": str},
                },
            )
        )

    if not services:
        logging.error("No enabled DEVICE sections in config.ini")
        sys.exit(1)

    driver = ShellyUniDriver(config, services)
    driver.tick()
    GLib.timeout_add(driver.poll_interval_ms(), driver.tick)
    GLib.timeout_add(driver.sign_of_life_ms(), driver.sign_of_life)

    logging.info(
        "Connected to dbus, polling every %ss", driver.poll_interval_ms() // 1000
    )
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
