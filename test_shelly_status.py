#!/usr/bin/env python3
import unittest

from shelly_status import (
    group_services_by_host,
    probe_temperature_c,
    shelly_firmware,
    shelly_serial,
    status_url,
)


SAMPLE = {
    "mac": "08F9E0446965",
    "update": {"old_version": "1.11.8"},
    "ext_temperature": {
        "0": {"hwID": "aaa", "tC": 43.75, "tF": 110.75},
        "1": {"hwID": "bbb", "tC": 41.0, "tF": 105.8},
    },
}


class ProbeTests(unittest.TestCase):
    def test_reads_probe_0(self):
        self.assertAlmostEqual(probe_temperature_c(SAMPLE, 0), 43.75)

    def test_missing_probe_returns_none(self):
        self.assertIsNone(probe_temperature_c(SAMPLE, 2))

    def test_missing_ext_temperature(self):
        self.assertIsNone(probe_temperature_c({"mac": "x"}, 0))


class MetaTests(unittest.TestCase):
    def test_serial_and_firmware(self):
        self.assertEqual(shelly_serial(SAMPLE), "08F9E0446965")
        self.assertEqual(shelly_firmware(SAMPLE), "1.11.8")

    def test_status_url_without_auth(self):
        self.assertEqual(status_url("192.168.42.11"), "http://192.168.42.11/status")

    def test_status_url_with_auth(self):
        self.assertEqual(
            status_url("192.168.42.11", "user", "pass"),
            "http://user:pass@192.168.42.11/status",
        )


class HostGroupTests(unittest.TestCase):
    def test_groups_devices_on_same_host(self):
        class S:
            def __init__(self, host):
                self.host = host

        grouped = group_services_by_host(
            [S("192.168.42.11"), S("192.168.42.11"), S("192.168.42.12")]
        )
        self.assertEqual(len(grouped["192.168.42.11"]), 2)
        self.assertEqual(len(grouped["192.168.42.12"]), 1)


if __name__ == "__main__":
    unittest.main()
