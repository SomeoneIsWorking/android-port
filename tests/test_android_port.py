#!/usr/bin/env python3
"""Focused checks for the shared Android device contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "android_port", ROOT / "tools/android_port.py"
)
assert SPEC is not None and SPEC.loader is not None
android_port = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = android_port
SPEC.loader.exec_module(android_port)


def main() -> int:
    assert android_port.SHARED_AVD == "codex_shared_api35"
    assert android_port.adb_devices_from_output(
        "List of devices attached\nemulator-5554\tdevice\nphone\toffline\n"
    ) == ("emulator-5554",)
    assert android_port.adb_devices_from_output("List of devices attached\n") == ()
    contract = android_port.NativeDependencyRequest(
        abi="arm64-v8a",
        api=26,
        ndk=Path("/sdk/ndk/28.2.13676358"),
        prefix=Path("/work/prefix"),
    )
    configure = android_port.native_dependency_configure_command(contract, Path("/work/build"))
    assert configure[:4] == ["cmake", "-S", str(android_port.NATIVE_DEPS_SOURCE), "-B"]
    assert "-DANDROID_ABI=arm64-v8a" in configure
    assert "-DANDROID_PLATFORM=android-26" in configure
    assert "-DCMAKE_INSTALL_LIBDIR=lib" in configure
    assert "-DCMAKE_INSTALL_PREFIX=/work/prefix" in configure
    assert android_port.native_dependency_manifest(contract) == Path("/work/prefix/android-port-dependencies.json")
    print("android-port: shared AVD contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
