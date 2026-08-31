#!/usr/bin/env python3
"""Focused checks for the shared Android device contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "android_port", ROOT / "tools/android_port.py"
)
assert SPEC is not None and SPEC.loader is not None
android_port = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(android_port)


def main() -> int:
    assert android_port.SHARED_AVD == "codex_shared_api35"
    assert android_port.adb_devices_from_output(
        "List of devices attached\nemulator-5554\tdevice\nphone\toffline\n"
    ) == ("emulator-5554",)
    assert android_port.adb_devices_from_output("List of devices attached\n") == ()
    print("android-port: shared AVD contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
