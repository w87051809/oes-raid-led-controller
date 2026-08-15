#!/usr/bin/env python3
"""OES md RAID LED controller.

Normal state: all configured disk LEDs breathe together.
Failure state: the failed slot flashes rapidly and the red power LED stays on.
"""

from __future__ import annotations

import argparse
import math
import os
import signal
import time
from pathlib import Path
from typing import Iterable


INVALID_ARRAY_STATES = {"inactive", "clear", "broken"}


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError:
        return default


def write_text(path: Path, value: object) -> bool:
    try:
        path.write_text(str(value), encoding="ascii")
        return True
    except OSError:
        return False


class RaidLedController:
    def __init__(
        self,
        md_sys: Path,
        leds: list[Path],
        ata_triggers: list[str],
        green_power: Path,
        red_power: Path,
        breath_seconds: float = 4.0,
        frame_hz: float = 50.0,
        health_interval: float = 0.20,
        failure_on_ms: int = 80,
        failure_off_ms: int = 80,
    ) -> None:
        self.md_sys = md_sys
        self.leds = leds
        self.ata_triggers = ata_triggers
        self.green_power = green_power
        self.red_power = red_power
        self.breath_seconds = breath_seconds
        self.frame_period = 1.0 / frame_hz
        self.health_interval = health_interval
        self.failure_on_ms = failure_on_ms
        self.failure_off_ms = failure_off_ms

        self.running = True
        self.last_values: dict[Path, int] = {}
        self.fds: dict[Path, int] = {}
        self.max_values: dict[Path, int] = {}

    def led_value(self, led: Path, on: bool) -> int:
        if not on:
            return 0
        if led not in self.max_values:
            raw = read_text(led / "max_brightness", "1")
            try:
                self.max_values[led] = max(1, int(raw))
            except ValueError:
                self.max_values[led] = 1
        return self.max_values[led]

    def set_trigger(self, led: Path, trigger: str) -> None:
        write_text(led / "trigger", trigger)
        self.last_values.pop(led, None)

    def set_led(self, led: Path, on: bool) -> None:
        value = self.led_value(led, on)
        if self.last_values.get(led) == value:
            return
        try:
            fd = self.fds[led]
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, str(value).encode("ascii"))
            self.last_values[led] = value
        except (KeyError, OSError):
            if write_text(led / "brightness", value):
                self.last_values[led] = value

    def set_all_disks(self, on: bool) -> None:
        for led in self.leds:
            self.set_led(led, on)

    def set_normal_power(self) -> None:
        self.set_trigger(self.red_power, "none")
        self.set_led(self.red_power, False)
        self.set_trigger(self.green_power, "none")
        self.set_led(self.green_power, True)

    def raid_slots(self) -> int:
        try:
            return max(1, int(read_text(self.md_sys / "raid_disks", str(len(self.leds)))))
        except ValueError:
            return len(self.leds)

    def member_states(self) -> list[tuple[str, str]]:
        states: list[tuple[str, str]] = []
        for slot in range(min(self.raid_slots(), len(self.leds))):
            link = self.md_sys / f"rd{slot}"
            state = "missing"
            member = f"slot{slot + 1}"
            try:
                target = link.resolve(strict=True)
                member = target.name.removeprefix("dev-")
                state = read_text(target / "state", "missing")
            except OSError:
                pass
            states.append((member, state))
        while len(states) < len(self.leds):
            states.append((f"slot{len(states) + 1}", "missing"))
        return states

    def raid_status(self) -> tuple[bool, str, list[tuple[str, str]]]:
        try:
            degraded = int(read_text(self.md_sys / "degraded"))
        except ValueError:
            degraded = -1
        array_state = read_text(self.md_sys / "array_state", "missing")
        states = self.member_states()
        valid_state = array_state not in INVALID_ARRAY_STATES and array_state != "missing"
        members_ok = bool(states) and all("in_sync" in state for _, state in states)
        return degraded == 0 and valid_state and members_ok, array_state, states

    def enter_breathing(self) -> None:
        for led in self.leds:
            self.set_trigger(led, "none")
            self.set_led(led, False)
        self.set_normal_power()

    def enter_failure(self, array_state: str, states: list[tuple[str, str]]) -> None:
        failed: list[str] = []
        for led in self.leds:
            self.set_trigger(led, "none")
            self.set_led(led, False)
        for slot, (member, state) in enumerate(states):
            if "in_sync" not in state:
                led = self.leds[slot]
                self.set_trigger(led, "timer")
                time.sleep(0.03)
                write_text(led / "delay_on", self.failure_on_ms)
                write_text(led / "delay_off", self.failure_off_ms)
                failed.append(f"slot{slot + 1}:{member}:{state}")
        self.set_trigger(self.green_power, "none")
        self.set_led(self.green_power, False)
        self.set_trigger(self.red_power, "none")
        self.set_led(self.red_power, True)
        detail = ",".join(failed) or "unknown"
        print(f"RAID FAILURE state={array_state} failed={detail}", flush=True)

    def restore_kernel_triggers(self) -> None:
        self.set_normal_power()
        for led, trigger in zip(self.leds, self.ata_triggers):
            self.set_trigger(led, trigger)

    def initialize(self) -> None:
        for led in self.leds + [self.green_power, self.red_power]:
            self.set_trigger(led, "none")
            try:
                self.fds[led] = os.open(led / "brightness", os.O_WRONLY)
            except OSError:
                pass

    def stop(self, _signum: int, _frame: object) -> None:
        self.running = False

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.initialize()

        mode = "startup"
        start = time.monotonic()
        last_health_check = 0.0
        healthy = False
        array_state = "unknown"
        states: list[tuple[str, str]] = []
        failure_signature: tuple[str, tuple[tuple[str, str], ...]] | None = None

        try:
            while self.running:
                frame_start = time.monotonic()
                if frame_start - last_health_check >= self.health_interval:
                    healthy, array_state, states = self.raid_status()
                    last_health_check = frame_start

                if not healthy:
                    signature = (array_state, tuple(states))
                    if mode != "failure" or signature != failure_signature:
                        self.enter_failure(array_state, states)
                        mode = "failure"
                        failure_signature = signature
                    time.sleep(self.health_interval)
                    continue

                failure_signature = None
                if mode != "breathing":
                    self.enter_breathing()
                    print(f"RAID LED mode: breathing state={array_state}", flush=True)
                    mode = "breathing"
                    start = time.monotonic()

                phase = ((frame_start - start) % self.breath_seconds) / self.breath_seconds
                envelope = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)
                duty = envelope * envelope

                if duty <= 0.01:
                    self.set_all_disks(False)
                    time.sleep(self.frame_period)
                elif duty >= 0.99:
                    self.set_all_disks(True)
                    time.sleep(self.frame_period)
                else:
                    on_time = self.frame_period * duty
                    self.set_all_disks(True)
                    time.sleep(on_time)
                    self.set_all_disks(False)
                    remaining = self.frame_period - (time.monotonic() - frame_start)
                    if remaining > 0:
                        time.sleep(remaining)
        finally:
            self.restore_kernel_triggers()
            for fd in self.fds.values():
                try:
                    os.close(fd)
                except OSError:
                    pass


def led_paths(names: Iterable[str], sys_root: Path) -> list[Path]:
    return [Path(name) if name.startswith("/") else sys_root / "class/leds" / name for name in names]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OES md RAID disk LED controller")
    parser.add_argument("--md", default="md0", help="md device name, default: md0")
    parser.add_argument("--led", action="append", dest="leds", help="disk LED sysfs name or path")
    parser.add_argument("--ata-trigger", action="append", dest="ata_triggers", help="trigger restored on exit")
    parser.add_argument("--green-power", default="green:power")
    parser.add_argument("--red-power", default="red:power")
    parser.add_argument("--breath-seconds", type=float, default=4.0)
    parser.add_argument("--frame-hz", type=float, default=50.0)
    parser.add_argument("--health-interval", type=float, default=0.20)
    parser.add_argument("--failure-on-ms", type=int, default=80)
    parser.add_argument("--failure-off-ms", type=int, default=80)
    parser.add_argument("--sys-root", type=Path, default=Path("/sys"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.leds = args.leds or ["green:disk", "green:disk_1", "green:disk_2"]
    args.ata_triggers = args.ata_triggers or ["ata1", "ata2", "ata3"]
    if len(args.ata_triggers) != len(args.leds):
        parser.error("--ata-trigger count must match --led count")
    if args.breath_seconds <= 0 or args.frame_hz <= 0 or args.health_interval <= 0:
        parser.error("timing values must be greater than zero")
    return args


def main() -> None:
    args = parse_args()
    leds = led_paths(args.leds, args.sys_root)
    green_power, red_power = led_paths([args.green_power, args.red_power], args.sys_root)
    controller = RaidLedController(
        md_sys=args.sys_root / "block" / args.md / "md",
        leds=leds,
        ata_triggers=args.ata_triggers,
        green_power=green_power,
        red_power=red_power,
        breath_seconds=args.breath_seconds,
        frame_hz=args.frame_hz,
        health_interval=args.health_interval,
        failure_on_ms=args.failure_on_ms,
        failure_off_ms=args.failure_off_ms,
    )
    controller.run()


if __name__ == "__main__":
    main()
