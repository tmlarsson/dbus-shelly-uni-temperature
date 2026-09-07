# dbus-shelly-uni-temperature

Publish Shelly Uni DS18B20 probes as Victron Venus OS temperature devices.

## What it does

The driver is a daemontools service. It reads `http://<host>/status` once per Uni (not once per probe), then publishes each enabled `[DEVICE*]` section as:

```
com.victronenergy.temperature.http_<Deviceinstance>
```

with `/Temperature` in °C and `/Connected` 0/1.

## Config

Copy values in `config.ini` on the GX (`/data/dbus-shelly-uni-temperature/config.ini`).

| Section | Key | Meaning |
|---|---|---|
| `DEVICEn` | `Enabled` | `1` to publish this probe, `0` to skip |
| `DEVICEn` | `Host` | Shelly Uni IP/hostname |
| `DEVICEn` | `ProbeNumber` | Index in `ext_temperature` (`0`, `1`, `2`) |
| `DEVICEn` | `Deviceinstance` | Unique Venus instance (becomes `http_66`, etc.) |
| `DEVICEn` | `CustomName` | Name in Remote Console |
| `DEVICEn` | `TemperatureType` | Victron type (default `2` = generic) |
| `DEVICEn` | `SignOfLifeLog` | Minutes between info log lines |
| `ONPREMISE` | `Username` / `Password` | Optional HTTP basic auth |
| `ONPREMISE` | `PollIntervalSeconds` | How often to poll (default 15, minimum 5) |

Several DEVICE sections may share one `Host`. Missing probes are logged once and show as disconnected instead of spamming the log.

## Install

On the GX (root SSH):

```bash
wget -O /tmp/shelly-uni.zip https://github.com/tmlarsson/dbus-shelly-uni-temperature/archive/refs/heads/main.zip
unzip /tmp/shelly-uni.zip -d /tmp
# Keep live settings if this is an update
if [ -f /data/dbus-shelly-uni-temperature/config.ini ]; then
  cp /data/dbus-shelly-uni-temperature/config.ini /tmp/shelly-uni-config.ini
fi
mkdir -p /data/dbus-shelly-uni-temperature
cp -R /tmp/dbus-shelly-uni-temperature-main/. /data/dbus-shelly-uni-temperature/
if [ -f /tmp/shelly-uni-config.ini ]; then
  cp /tmp/shelly-uni-config.ini /data/dbus-shelly-uni-temperature/config.ini
fi
chmod a+x /data/dbus-shelly-uni-temperature/install.sh
/data/dbus-shelly-uni-temperature/install.sh
```

Edit `config.ini` after a first install, then restart. Updates keep the existing `config.ini`.

## Restart / uninstall / logs

```bash
/data/dbus-shelly-uni-temperature/restart.sh
/data/dbus-shelly-uni-temperature/uninstall.sh
tail -n 100 -f /var/log/dbus-shelly-uni-temperature/current | tai64nlocal
```

On some Venus images `/var/log` is the same as `/data/log`.

## Docs

- [Venus D-Bus temperature](https://github.com/victronenergy/venus/wiki/dbus#temperature)
- [Shelly Gen1 status](https://shelly-api-docs.shelly.cloud/gen1/#shelly-uni)
- [GX root access](https://www.victronenergy.com/live/ccgx:root_access)
