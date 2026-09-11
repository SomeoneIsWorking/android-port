#!/usr/bin/env python3
"""Shared Android SDK and single-foreground-emulator utilities."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# CLI consumers may load this module by file path rather than executing it directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from android_java import (
    select_java_home,
)
from android_media import (
    ffmpeg_archive_root,
    FFMPEG_CFLAGS,
    ffmpeg_assembly_configuration,
    ffmpeg_contract,
    ffmpeg_required_files,
)
from android_native_contract import (
    DEFAULT_ANDROID_API,
    DEPENDENCY_CAPABILITY_FILES,
    NATIVE_DEPENDENCY_FILES,
    NATIVE_DEPS_SOURCE,
    NDK_TRIPLES,
    NativeDependencyRequest,
)
from android_native_dependencies import (
    build_native_dependencies,
    native_dependency_configure_command,
    native_dependency_cxx_runtime,
    native_dependency_cxx_runtime_path,
    native_dependency_manifest,
    ndk_cxx_shared_library,
)
from android_package import (
    inspect_apk_runtime,
    stage_gradle_runtime,
    verify_native_entry,
)

__all__ = [
    "DEFAULT_ANDROID_API",
    "DEPENDENCY_CAPABILITY_FILES",
    "NATIVE_DEPENDENCY_FILES",
    "NATIVE_DEPS_SOURCE",
    "NDK_TRIPLES",
    "NativeDependencyRequest",
    "build_native_dependencies",
    "ffmpeg_archive_root",
    "FFMPEG_CFLAGS",
    "ffmpeg_assembly_configuration",
    "ffmpeg_contract",
    "ffmpeg_required_files",
    "inspect_apk_runtime",
    "native_dependency_configure_command",
    "native_dependency_cxx_runtime",
    "native_dependency_cxx_runtime_path",
    "native_dependency_manifest",
    "ndk_cxx_shared_library",
    "select_java_home",
    "stage_gradle_runtime",
    "verify_native_entry",
]

SHARED_AVD = "codex_shared_api35"


@dataclass(frozen=True)
class AndroidPortProfile:
    """Consumer-owned package inputs that are shared Android-port policy."""

    source: Path
    abi: str
    api: int
    capabilities: tuple[str, ...]
    prefix: Path
    native_library: Path
    jni_libs: Path
    emulator_lock: Path
    emulator_serial: str


def profile_relative_path(profile: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise SystemExit(f"Android profile {field} must be a non-empty relative path")
    candidate = Path(value)
    if candidate.is_absolute():
        raise SystemExit(f"Android profile {field} must be relative to {profile}")
    return (profile.parent / candidate).resolve()


def profile_object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SystemExit(f"Android profile {field} must be an object")
    return value


def profile_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SystemExit(f"Android profile {field} must be a non-empty string")
    return value


def profile_capabilities(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
    ):
        raise SystemExit(
            "Android profile nativeDependencies.capabilities must be a non-empty string list"
        )
    capabilities = tuple(value)
    unknown = sorted(set(capabilities) - DEPENDENCY_CAPABILITY_FILES.keys())
    if unknown:
        raise SystemExit(
            "Android profile declares unsupported capability: " + ", ".join(unknown)
        )
    if len(set(capabilities)) != len(capabilities):
        raise SystemExit(
            "Android profile nativeDependencies.capabilities must not repeat a capability"
        )
    if "sdl3" not in capabilities:
        raise SystemExit(
            "Android profile nativeDependencies.capabilities must include sdl3"
        )
    return capabilities


def dependency_files(capabilities: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        relative
        for capability in capabilities
        for relative in DEPENDENCY_CAPABILITY_FILES[capability]
    )


def native_dependency_request_for_profile(
    profile: AndroidPortProfile, ndk: Path
) -> NativeDependencyRequest:
    """Keep ABI/API/prefix selection in the portable title profile, not each build command."""
    return NativeDependencyRequest(
        abi=profile.abi,
        api=profile.api,
        ndk=ndk.resolve(),
        prefix=profile.prefix,
    )


def load_android_port_profile(path: Path) -> AndroidPortProfile:
    """Load the portable consumer manifest for shared package/device mechanics."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Android profile is unreadable: {path}: {error}") from error
    root = profile_object(value, "root")
    if root.get("schema") != 1:
        raise SystemExit(
            f"Android profile {path} has unsupported schema {root.get('schema')!r}"
        )
    dependencies = profile_object(root.get("nativeDependencies"), "nativeDependencies")
    package = profile_object(root.get("package"), "package")
    emulator = profile_object(root.get("sharedEmulator"), "sharedEmulator")
    abi = profile_string(dependencies.get("abi"), "nativeDependencies.abi")
    if abi not in NDK_TRIPLES:
        raise SystemExit(f"Android profile declares unsupported ABI {abi!r}")
    api = dependencies.get("api")
    if not isinstance(api, int) or api <= 0:
        raise SystemExit(
            "Android profile nativeDependencies.api must be a positive integer"
        )
    lock = profile_relative_path(path, emulator.get("lock"), "sharedEmulator.lock")
    if lock.parts[-2:] != ("coord", "android-emulator.lock"):
        raise SystemExit(
            "Android profile sharedEmulator.lock must resolve to coord/android-emulator.lock"
        )
    native_library = profile_relative_path(
        path, package.get("nativeLibrary"), "package.nativeLibrary"
    )
    if native_library.name != "libmain.so":
        raise SystemExit("Android profile package.nativeLibrary must name libmain.so")
    jni_libs = profile_relative_path(path, package.get("jniLibs"), "package.jniLibs")
    if "build" not in jni_libs.parts:
        raise SystemExit(
            "Android profile package.jniLibs must be under the title build directory"
        )
    return AndroidPortProfile(
        source=path.resolve(),
        abi=abi,
        api=api,
        capabilities=profile_capabilities(dependencies.get("capabilities")),
        prefix=profile_relative_path(
            path, dependencies.get("prefix"), "nativeDependencies.prefix"
        ),
        native_library=native_library,
        jni_libs=jni_libs,
        emulator_lock=lock,
        emulator_serial=profile_string(emulator.get("serial"), "sharedEmulator.serial"),
    )


def validate_native_dependency_prefix(profile: AndroidPortProfile) -> None:
    """Reject a prefix that was not built for the profile's ABI and API."""
    manifest = profile.prefix / "android-port-dependencies.json"
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(
            f"Android dependency manifest is unreadable: {manifest}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise SystemExit(f"Android dependency manifest must be an object: {manifest}")
    expected = {"schema": 1, "abi": profile.abi, "platform": f"android-{profile.api}"}
    disagreements = [
        f"{key}={value.get(key)!r}, expected {wanted!r}"
        for key, wanted in expected.items()
        if value.get(key) != wanted
    ]
    declared_capabilities = value.get("capabilities")
    if not isinstance(declared_capabilities, list) or not all(
        isinstance(capability, str) for capability in declared_capabilities
    ):
        disagreements.append("capabilities missing or not a string list")
        declared = set()
    else:
        declared = set(declared_capabilities)
    unavailable = sorted(set(profile.capabilities) - declared)
    if unavailable:
        disagreements.append("missing declared capabilities: " + ", ".join(unavailable))
    missing = [
        profile.prefix / relative
        for relative in dependency_files(profile.capabilities)
        if not (profile.prefix / relative).is_file()
    ]
    runtime = native_dependency_cxx_runtime_path(profile.prefix, profile.abi)
    if not runtime.is_file():
        missing.append(runtime)
    if disagreements or missing:
        details = [*disagreements, *(f"missing {item}" for item in missing)]
        raise SystemExit(
            "Android dependency prefix disagrees with profile:\n  "
            + "\n  ".join(details)
        )


def package_runtime_sources(
    profile: AndroidPortProfile,
) -> tuple[tuple[str, Path], ...]:
    """Return the exact native runtime files that every shared package must stage."""
    validate_native_dependency_prefix(profile)
    if not profile.native_library.is_file():
        raise SystemExit(
            f"Android package profile requires title runtime {profile.native_library}; "
            "a setup-only APK is not a package milestone"
        )
    cxx_runtime = native_dependency_cxx_runtime_path(profile.prefix, profile.abi)
    return (
        ("libmain.so", profile.native_library),
        ("libSDL3.so", profile.prefix / "lib/libSDL3.so"),
        ("libc++_shared.so", cxx_runtime),
    )


def stage_package_runtime(profile: AndroidPortProfile) -> int:
    """Stage title and shared runtime libraries into Gradle's JNI source directory."""
    sources = package_runtime_sources(profile)
    destination = profile.jni_libs / profile.abi
    destination.mkdir(parents=True, exist_ok=True)
    for name, source in sources:
        shutil.copy2(source, destination / name)
    print(f"Android package runtime staged: {destination}")
    return 0


def profile_adb_command(
    profile: AndroidPortProfile, command: Sequence[str]
) -> tuple[str, ...]:
    """Require the profile's exact shared-device serial before taking the lock."""
    if (
        len(command) < 4
        or Path(command[0]).name != "adb"
        or command[1:3] != ["-s", profile.emulator_serial]
    ):
        raise SystemExit(
            "profile-emulator-lock requires `adb -s "
            f"{profile.emulator_serial} ...` after --"
        )
    return tuple(command)


def with_profile_emulator_lock(
    profile: AndroidPortProfile, command: Sequence[str]
) -> int:
    return with_emulator_lock(
        profile.emulator_lock, profile_adb_command(profile, command)
    )


def executable(name: str) -> str:
    path = shutil.which(name)
    if path is not None:
        return path
    relative = {
        "emulator": ("emulator", "emulator"),
        "adb": ("platform-tools", "adb"),
    }.get(name)
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


def removable_emulator_test_directory(directory: str) -> str:
    path = PurePosixPath(directory)
    root = PurePosixPath("/sdcard/Download")
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise SystemExit(
            "emulator cleanup accepts only a child of /sdcard/Download"
        ) from error
    if len(relative.parts) != 1 or not relative.name.endswith("-emulator-test"):
        raise SystemExit(
            "emulator cleanup accepts only one /sdcard/Download/*-emulator-test directory"
        )
    return str(path)


def remove_emulator_test_directory(serial: str, directory: str) -> int:
    target = removable_emulator_test_directory(directory)
    adb = executable("adb")
    subprocess.run([adb, "-s", serial, "shell", "rm", "-rf", "--", target], check=True)
    print(f"removed Android emulator test directory: {target}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    status = commands.add_parser(
        "emulator-status", help="inspect the shared API 35 AVD"
    )
    status.add_argument("--require-running", action="store_true")
    lock = commands.add_parser(
        "with-emulator-lock", help="run one exclusive interactive Android command"
    )
    lock.add_argument("--lock", type=Path, required=True)
    lock.add_argument("invocation", nargs=argparse.REMAINDER)
    dependencies = commands.add_parser(
        "build-native-deps",
        help="build the pinned SDL3, SDL3_image, and FreeType Android prefix",
    )
    dependencies.add_argument("--ndk", type=Path, required=True)
    dependencies.add_argument("--prefix", type=Path, required=True)
    dependencies.add_argument(
        "--abi", choices=("arm64-v8a", "x86_64"), default="arm64-v8a"
    )
    dependencies.add_argument("--api", type=int, default=DEFAULT_ANDROID_API)
    dependencies.add_argument(
        "--jobs", type=int, default=max(1, min(os.cpu_count() or 1, 4))
    )
    profile_dependencies = commands.add_parser(
        "build-profile-native-deps",
        help="build the selected profile's shared Android prefix",
    )
    profile_dependencies.add_argument("--profile", type=Path, required=True)
    profile_dependencies.add_argument("--ndk", type=Path, required=True)
    profile_dependencies.add_argument(
        "--jobs", type=int, default=max(1, min(os.cpu_count() or 1, 4))
    )
    package = commands.add_parser(
        "stage-package-runtime",
        help="validate one Android profile and stage its title/SDL/C++ runtime libraries",
    )
    package.add_argument("--profile", type=Path, required=True)
    profile_lock = commands.add_parser(
        "with-profile-emulator-lock",
        help="run one profile-bound ADB command under the shared emulator lock",
    )
    profile_lock.add_argument("--profile", type=Path, required=True)
    profile_lock.add_argument("invocation", nargs=argparse.REMAINDER)
    cleanup = commands.add_parser(
        "remove-emulator-test-directory",
        help="remove one bounded Downloads test directory",
    )
    cleanup.add_argument("--serial", required=True)
    cleanup.add_argument("--path", required=True)
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
    if args.operation == "stage-package-runtime":
        return stage_package_runtime(load_android_port_profile(args.profile.resolve()))
    if args.operation == "build-profile-native-deps":
        profile = load_android_port_profile(args.profile.resolve())
        return build_native_dependencies(
            native_dependency_request_for_profile(profile, args.ndk), args.jobs
        )
    if args.operation == "with-profile-emulator-lock":
        command = args.invocation
        if command[:1] == ["--"]:
            command = command[1:]
        return with_profile_emulator_lock(
            load_android_port_profile(args.profile.resolve()), command
        )
    if args.operation == "remove-emulator-test-directory":
        return remove_emulator_test_directory(args.serial, args.path)
    raise AssertionError(f"unknown command {args.operation}")


if __name__ == "__main__":
    raise SystemExit(main())
