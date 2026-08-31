#!/usr/bin/env python3
"""Focused checks for the shared Android device contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tarfile
import tempfile


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
    assert android_port.native_dependency_cxx_runtime(contract) == Path(
        "/work/prefix/share/android-port/cxx/arm64-v8a/libc++_shared.so"
    )
    assert android_port.ffmpeg_assembly_configuration("arm64-v8a") == ()
    assert android_port.ffmpeg_assembly_configuration("x86_64") == (
        "--disable-x86asm", "--disable-inline-asm"
    )
    assert "api=26" in android_port.ffmpeg_contract(contract)
    assert android_port.ffmpeg_contract(contract).splitlines()[-1] == "api=26"
    assert android_port.ffmpeg_required_files(contract.prefix)[0] == Path(
        "/work/prefix/include/libavutil/avutil.h"
    )
    members = [tarfile.TarInfo("FFmpeg-n7.1.1"), tarfile.TarInfo("FFmpeg-n7.1.1/configure")]
    assert android_port.ffmpeg_archive_root(members) == "FFmpeg-n7.1.1"
    try:
        android_port.ffmpeg_archive_root([*members, tarfile.TarInfo("elsewhere/x")])
    except SystemExit as error:
        assert "exactly one top-level directory" in str(error)
    else:
        raise AssertionError("FFmpeg archive with two roots was accepted")
    with tempfile.TemporaryDirectory() as temporary:
        ndk = Path(temporary) / "ndk"
        cxx_shared = (
            ndk
            / "toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib"
            / "aarch64-linux-android/libc++_shared.so"
        )
        cxx_shared.parent.mkdir(parents=True)
        cxx_shared.touch()
        assert android_port.ndk_cxx_shared_library(ndk, "arm64-v8a") == cxx_shared
    assert android_port.removable_emulator_test_directory(
        "/sdcard/Download/benefactor-emulator-test"
    ) == "/sdcard/Download/benefactor-emulator-test"
    for path in ("/sdcard/Download", "/sdcard/Download/nested/emulator-test", "/sdcard/Documents/test-emulator-test"):
        try:
            android_port.removable_emulator_test_directory(path)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"expected cleanup refusal for {path}")
    print("android-port: shared AVD contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
