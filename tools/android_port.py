#!/usr/bin/env python3
"""Shared Android SDK and single-foreground-emulator utilities."""

from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
from collections.abc import Sequence


SHARED_AVD = "codex_shared_api35"


def executable(name: str) -> str:
    path = shutil.which(name)
    if path is not None:
        return path
    relative = {"emulator": ("emulator", "emulator"), "adb": ("platform-tools", "adb")}.get(name)
    if relative is not None:
        for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            root = os.environ.get(variable)
            if root is None:
                continue
            candidate = Path(root).joinpath(*relative)
            if candidate.is_file():
                return str(candidate)
    raise SystemExit(
        f"Android {name} is unavailable. Put it on PATH or set ANDROID_HOME to a complete SDK."
    )


def listed_avds(emulator: str) -> set[str]:
    completed = subprocess.run(
        [emulator, "-list-avds"], check=True, capture_output=True, text=True
    )
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def adb_devices(adb: str) -> tuple[str, ...]:
    completed = subprocess.run(
        [adb, "devices"], check=True, capture_output=True, text=True
    )
    return adb_devices_from_output(completed.stdout)


def adb_devices_from_output(output: str) -> tuple[str, ...]:
    rows = output.splitlines()[1:]
    return tuple(
        fields[0]
        for row in rows
        if (fields := row.split()) and len(fields) == 2 and fields[1] == "device"
    )


def avd_name(adb: str, serial: str) -> str:
    completed = subprocess.run(
        [adb, "-s", serial, "shell", "getprop", "ro.boot.qemu.avd_name"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def shared_emulator_serials(adb: str) -> tuple[str, ...]:
    return tuple(
        serial
        for serial in adb_devices(adb)
        if serial.startswith("emulator-") and avd_name(adb, serial) == SHARED_AVD
    )


def emulator_status(require_running: bool) -> int:
    emulator = executable("emulator")
    avds = listed_avds(emulator)
    if SHARED_AVD not in avds:
        raise SystemExit(
            f"Shared Android AVD {SHARED_AVD!r} is absent; available AVDs: "
            f"{', '.join(sorted(avds)) or 'none'}."
        )
    adb = executable("adb")
    running = shared_emulator_serials(adb)
    if running:
        print(f"shared Android emulator: {SHARED_AVD} ({', '.join(running)})")
        return 0
    message = f"shared Android emulator: {SHARED_AVD} is installed but not running"
    if require_running:
        raise SystemExit(message)
    print(message)
    return 0


def with_emulator_lock(lock_path: Path, command: Sequence[str]) -> int:
    if not command:
        raise SystemExit("with-emulator-lock requires an ADB command after --")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        print(f"shared Android emulator lock acquired: {lock_path}")
        try:
            return subprocess.run(command, check=False).returncode
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    status = commands.add_parser("emulator-status", help="inspect the shared API 35 AVD")
    status.add_argument("--require-running", action="store_true")
    lock = commands.add_parser(
        "with-emulator-lock", help="run one exclusive interactive Android command"
    )
    lock.add_argument("--lock", type=Path, required=True)
    lock.add_argument("invocation", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.operation == "emulator-status":
        return emulator_status(args.require_running)
    if args.operation == "with-emulator-lock":
        command = args.invocation
        if command[:1] == ["--"]:
            command = command[1:]
        return with_emulator_lock(args.lock, command)
    raise AssertionError(f"unknown command {args.operation}")


if __name__ == "__main__":
    raise SystemExit(main())
