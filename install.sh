#!/bin/sh
set -eu

base_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

install -D -m 755 "$base_dir/src/oes-raid-leds.py" /usr/local/sbin/oes-raid-leds.py
install -D -m 644 "$base_dir/systemd/oes-raid-leds.service" /etc/systemd/system/oes-raid-leds.service

if [ ! -e /etc/default/oes-raid-leds ]; then
    install -D -m 644 "$base_dir/config/oes-raid-leds" /etc/default/oes-raid-leds
fi

systemctl daemon-reload
systemctl enable --now oes-raid-leds.service
systemctl --no-pager --full status oes-raid-leds.service
