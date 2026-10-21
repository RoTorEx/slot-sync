#!/bin/sh
# Stage units only; cutover is an explicit operator step.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test "$(id -u)" -eq 0 || { echo 'Run as root' >&2; exit 1; }
# The service must be able to create its SQLite state and private audit logs.
install -d -o gallendar -g gallendar -m 0700 \
  /srv/gallendar/slot-sync /srv/gallendar/slot-sync/logs
install -m 0644 "$root/deploy/slot-sync.service" /etc/systemd/system/slot-sync.service
install -m 0644 "$root/deploy/slot-sync.timer" /etc/systemd/system/slot-sync.timer
systemctl daemon-reload
echo 'Units staged; stop the old writer before enabling the timer.'
