#!/bin/sh
set -eu

systemctl disable --now oes-raid-leds.service 2>/dev/null || true
rm -f /etc/systemd/system/oes-raid-leds.service
rm -f /usr/local/sbin/oes-raid-leds.py
systemctl daemon-reload

printf '%s\n' '配置文件 /etc/default/oes-raid-leds 已保留。'
