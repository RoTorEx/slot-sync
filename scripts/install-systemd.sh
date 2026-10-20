#!/bin/sh
# Stage units only; cutover is an explicit operator step.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test "$(id -u)" -eq 0 || { echo 'Run as root' >&2; exit 1; }
install -m 0644 "$root/deploy/callendars-syncer.service" /etc/systemd/system/callendars-syncer.service
install -m 0644 "$root/deploy/callendars-syncer.timer" /etc/systemd/system/callendars-syncer.timer
systemctl daemon-reload
echo 'Units staged; stop the old writer before enabling the timer.'
