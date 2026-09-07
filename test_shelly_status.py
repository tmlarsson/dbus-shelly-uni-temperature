#!/usr/bin/env python3
import unittest

from shelly_status import (
    HostFailureTracker,
    clamp_poll_seconds,
    clamp_sign_of_life_minutes,
    group_services_by_host,
    http_auth,
    probe_connection,
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

    def test_disconnect_clears_temperature(self):
        connected, temperature = probe_connection(None, 0)
        self.assertEqual(connected, 0)
        self.assertIsNone(temperature)

    def test_missing_probe_clears_temperature(self):
        connected, temperature = probe_connection(SAMPLE, 2)
        self.assertEqual(connected, 0)
        self.assertIsNone(temperature)

    def test_probe_then_attached(self):
        connected, temperature = probe_connection(SAMPLE, 0)
        self.assertEqual(connected, 1)
        self.assertAlmostEqual(temperature, 43.75)


class MetaTests(unittest.TestCase):
    def test_serial_and_firmware(self):
        self.assertEqual(shelly_serial(SAMPLE), "08F9E0446965")
        self.assertEqual(shelly_firmware(SAMPLE), "1.11.8")

    def test_status_url_never_contains_credentials(self):
        url = status_url("192.168.42.11")
        self.assertEqual(url, "http://192.168.42.11/status")
        self.assertNotIn("user", url)
        self.assertNotIn("p@ss:word", url)
        auth = http_auth("user", "p@ss:word")
        self.assertEqual(auth, ("user", "p@ss:word"))

    def test_status_url_rejects_empty_host(self):
        with self.assertRaises(ValueError):
            status_url("  ")


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


class ClampTests(unittest.TestCase):
    def test_poll_interval(self):
        self.assertEqual(clamp_poll_seconds(""), 15)
        self.assertEqual(clamp_poll_seconds("nope"), 15)
        self.assertEqual(clamp_poll_seconds("0"), 5)
        self.assertEqual(clamp_poll_seconds("3"), 5)
        self.assertEqual(clamp_poll_seconds("60"), 60)

    def test_sign_of_life(self):
        self.assertEqual(clamp_sign_of_life_minutes("bogus"), 5)
        self.assertEqual(clamp_sign_of_life_minutes(""), 5)
        self.assertEqual(clamp_sign_of_life_minutes("10"), 10)


class FailureLogTests(unittest.TestCase):
    def test_first_then_repeat_then_recover(self):
        tracker = HostFailureTracker()
        self.assertEqual(tracker.note("u1", False), "first")
        self.assertEqual(tracker.note("u1", False), "repeat")
        self.assertEqual(tracker.note("u1", True), "recovered")
        self.assertEqual(tracker.note("u1", True), "ok")
        self.assertEqual(tracker.note("u1", False), "first")


if __name__ == "__main__":
    unittest.main()
