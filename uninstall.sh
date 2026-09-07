#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SERVICE_NAME=$(basename $SCRIPT_DIR)

sed -i "\|$SCRIPT_DIR/install.sh|d" /data/rc.local
if command -v svc >/dev/null 2>&1; then
    svc -d /service/$SERVICE_NAME 2>/dev/null || true
else
    pids=$(pgrep -f "python.*$SCRIPT_DIR/dbus-shelly-uni-temperature.py" || true)
    [ -n "$pids" ] && kill $pids
fi
rm -f /service/$SERVICE_NAME
