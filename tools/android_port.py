#!/usr/bin/env python3
"""Shared Android SDK and single-foreground-emulator utilities."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
from collections.abc import Sequence


SHARED_AVD = "codex_shared_api35"
ROOT = Path(__file__).resolve().parents[1]
NATIVE_DEPS_SOURCE = ROOT / "android_port" / "native_deps"
NATIVE_DEPENDENCY_FILES = (
    "lib/libSDL3.so",
    "lib/libSDL3_image.a",
    "lib/libfreetype.a",
    "lib/libfmt.a",
    "lib/cmake/SDL3/SDL3Config.cmake",
    "lib/cmake/SDL3_image/SDL3_imageConfig.cmake",
    "lib/cmake/freetype/freetype-config.cmake",
    "lib/cmake/fmt/fmt-config.cmake",
    "share/android-port/sdl3-java/org/libsdl/app/SDLActivity.java",
)


@dataclass(frozen=True)
class NativeDependencyRequest:
    abi: str
    api: int
    ndk: Path
    prefix: Path


def native_dependency_manifest(request: NativeDependencyRequest) -> Path:
    return request.prefix / "android-port-dependencies.json"


def native_dependency_configure_command(
    request: NativeDependencyRequest, build_directory: Path
) -> list[str]:
    return [
        "cmake",
        "-S",
        str(NATIVE_DEPS_SOURCE),
        "-B",
        str(build_directory),
        f"-DCMAKE_TOOLCHAIN_FILE={request.ndk / 'build/cmake/android.toolchain.cmake'}",
        f"-DANDROID_ABI={request.abi}",
        f"-DANDROID_PLATFORM=android-{request.api}",
        "-DANDROID_STL=c++_shared",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_INSTALL_LIBDIR=lib",
        f"-DCMAKE_INSTALL_PREFIX={request.prefix}",
    ]


def stage_native_dependency_metadata(
    request: NativeDependencyRequest, build_directory: Path
) -> None:
    manifest = build_directory / "android-port-dependencies.json"
    if not manifest.is_file():
        raise SystemExit(f"Android dependency build omitted its manifest: {manifest}")
    java_source = build_directory / "sources" / "sdl3" / "android-project" / "app" / "src" / "main" / "java"
    if not java_source.is_dir():
        raise SystemExit(f"Android dependency build omitted SDL3 Java sources: {java_source}")
    request.prefix.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest, native_dependency_manifest(request))
    shutil.copytree(
        java_source,
        request.prefix / "share" / "android-port" / "sdl3-java",
        dirs_exist_ok=True,
    )


def build_native_dependencies(request: NativeDependencyRequest, jobs: int) -> int:
    toolchain = request.ndk / "build" / "cmake" / "android.toolchain.cmake"
    if not toolchain.is_file():
        raise SystemExit(f"Android NDK toolchain is missing: {toolchain}")
    if jobs <= 0:
        raise SystemExit("build-native-deps --jobs must be positive")
    build_directory = ROOT / "build" / "native-deps" / f"{request.abi}-api{request.api}"
    subprocess.run(native_dependency_configure_command(request, build_directory), check=True)
    subprocess.run(
        [
            "cmake",
            "--build",
            str(build_directory),
            "--target",
            "android_port_native_dependencies",
            "--parallel",
            str(jobs),
        ],
        check=True,
    )
    stage_native_dependency_metadata(request, build_directory)
    missing = [
        request.prefix / relative
        for relative in ("android-port-dependencies.json", *NATIVE_DEPENDENCY_FILES)
        if not (request.prefix / relative).is_file()
    ]
    if missing:
        raise SystemExit(
            "Android dependency install omitted required artifacts:\\n"
            + "\\n".join(str(path) for path in missing)
        )
    print(f"Android dependency prefix: {request.prefix}")
    return 0


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
    dependencies = commands.add_parser(
        "build-native-deps", help="build the pinned SDL3, SDL3_image, and FreeType Android prefix"
    )
    dependencies.add_argument("--ndk", type=Path, required=True)
    dependencies.add_argument("--prefix", type=Path, required=True)
    dependencies.add_argument("--abi", choices=("arm64-v8a", "x86_64"), default="arm64-v8a")
    dependencies.add_argument("--api", type=int, default=26)
    dependencies.add_argument("--jobs", type=int, default=max(1, min(os.cpu_count() or 1, 4)))
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
    if args.operation == "build-native-deps":
        return build_native_dependencies(
            NativeDependencyRequest(
                abi=args.abi,
                api=args.api,
                ndk=args.ndk.resolve(),
                prefix=args.prefix.resolve(),
            ),
            args.jobs,
        )
    raise AssertionError(f"unknown command {args.operation}")


if __name__ == "__main__":
    raise SystemExit(main())
