#!/usr/bin/env python3
"""Shared Android SDK and single-foreground-emulator utilities."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import urllib.request
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
    "include/libavutil/avutil.h",
    "lib/libavformat.a",
    "lib/libavcodec.a",
    "lib/libswscale.a",
    "lib/libswresample.a",
    "lib/libavutil.a",
)
NDK_TRIPLES = {
    "arm64-v8a": "aarch64-linux-android",
    "x86_64": "x86_64-linux-android",
}
FFMPEG_VERSION = "n7.1.1"
FFMPEG_URL = (
    "https://github.com/FFmpeg/FFmpeg/archive/refs/tags/"
    f"{FFMPEG_VERSION}.tar.gz"
)
FFMPEG_SHA256 = "f117507dc501f2a6c11f9241d8d0c3213846cfad91764361af37befd6b6c523d"
FFMPEG_LIBRARIES = ("avformat", "avcodec", "swscale", "swresample", "avutil")


@dataclass(frozen=True)
class NativeDependencyRequest:
    abi: str
    api: int
    ndk: Path
    prefix: Path


def ndk_cxx_shared_library(ndk: Path, abi: str) -> Path:
    """Return the C++ runtime library required by an Android native package."""
    triple = NDK_TRIPLES.get(abi)
    if triple is None:
        raise SystemExit(f"Android ABI has no NDK C++ runtime mapping: {abi}")
    prebuilt = ndk / "toolchains" / "llvm" / "prebuilt"
    roots = list(prebuilt.glob("*/sysroot/usr/lib"))
    if len(roots) != 1:
        raise SystemExit(f"expected one NDK LLVM sysroot under {prebuilt}, found {len(roots)}")
    library = roots[0] / triple / "libc++_shared.so"
    if not library.is_file():
        raise SystemExit(f"NDK C++ runtime is missing: {library}")
    return library


def native_dependency_manifest(request: NativeDependencyRequest) -> Path:
    return request.prefix / "android-port-dependencies.json"


def native_dependency_cxx_runtime(request: NativeDependencyRequest) -> Path:
    return request.prefix / "share/android-port/cxx" / request.abi / "libc++_shared.so"


def ffmpeg_assembly_configuration(abi: str) -> tuple[str, ...]:
    """Keep emulator FFmpeg independent of a host NASM installation."""
    return ("--disable-x86asm", "--disable-inline-asm") if abi == "x86_64" else ()


def ffmpeg_contract(request: NativeDependencyRequest) -> str:
    """The installed FFmpeg archive set is valid only for this ABI/API pair."""
    return "\n".join((
        f"ffmpeg={FFMPEG_VERSION}",
        f"abi={request.abi}",
        f"api={request.api}",
        *ffmpeg_assembly_configuration(request.abi),
        "",
    ))


def ffmpeg_required_files(prefix: Path) -> tuple[Path, ...]:
    return (
        prefix / "include/libavutil/avutil.h",
        *(prefix / "lib" / f"lib{library}.a" for library in FFMPEG_LIBRARIES),
    )


def ffmpeg_archive(cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    downloaded = cache / f"ffmpeg-{FFMPEG_VERSION}.tar.gz"
    if not downloaded.exists():
        print(f"Downloading FFmpeg {FFMPEG_VERSION} into {downloaded}")
        urllib.request.urlretrieve(FFMPEG_URL, downloaded)
    digest = hashlib.sha256(downloaded.read_bytes()).hexdigest()
    if digest != FFMPEG_SHA256:
        raise SystemExit(
            f"FFmpeg archive checksum mismatch: expected {FFMPEG_SHA256}, got {digest}"
        )
    return downloaded


def ffmpeg_archive_root(members: list[tarfile.TarInfo]) -> str:
    roots = {PurePosixPath(member.name).parts[0] for member in members if member.name.strip("./")}
    if len(roots) != 1:
        raise SystemExit(
            f"FFmpeg archive must hold exactly one top-level directory, found {sorted(roots)}"
        )
    return roots.pop()


def ffmpeg_source_tree(cache: Path) -> Path:
    downloaded = ffmpeg_archive(cache)
    with tarfile.open(downloaded, "r:gz") as bundle:
        members = bundle.getmembers()
        source = cache / ffmpeg_archive_root(members)
        if source.is_dir() and (source / "configure").is_file():
            return source
        print(f"Extracting {downloaded} into {cache}")
        destination = cache.resolve()
        for member in members:
            if member.issym() or member.islnk():
                raise SystemExit(f"Refusing linked FFmpeg archive member: {member.name}")
            target = (cache / member.name).resolve()
            if target != destination and destination not in target.parents:
                raise SystemExit(f"Refusing unsafe FFmpeg archive member: {member.name}")
            bundle.extract(member, cache)
    if not (source / "configure").is_file():
        raise SystemExit(f"FFmpeg archive did not unpack a source tree at {source}")
    return source


def ffmpeg_build(request: NativeDependencyRequest, jobs: int) -> None:
    marker = request.prefix / ".android-port-ffmpeg-contract"
    required = ffmpeg_required_files(request.prefix)
    contract = ffmpeg_contract(request)
    if marker.is_file() and marker.read_text(encoding="utf-8") == contract and all(
        path.is_file() for path in required
    ):
        return

    source = ffmpeg_source_tree(ROOT / "build" / "source-cache")
    build_directory = ROOT / "build" / "ffmpeg" / f"{request.abi}-api{request.api}"
    if build_directory.exists():
        shutil.rmtree(build_directory)
    for file in (*required, marker):
        if file.exists():
            file.unlink()
    for directory in (request.prefix / "include/libavcodec", request.prefix / "include/libavformat",
                      request.prefix / "include/libavutil", request.prefix / "include/libswresample",
                      request.prefix / "include/libswscale"):
        if directory.exists():
            shutil.rmtree(directory)
    build_directory.mkdir(parents=True, exist_ok=True)

    toolchain = request.ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
    triple = NDK_TRIPLES[request.abi]
    compiler = toolchain / f"{triple}{request.api}-clang"
    compiler_cpp = toolchain / f"{triple}{request.api}-clang++"
    for program in (compiler, compiler_cpp, toolchain / "llvm-ar", toolchain / "llvm-ranlib"):
        if not program.is_file():
            raise SystemExit(f"Android FFmpeg tool is missing: {program}")

    configure = [
        str(source / "configure"),
        f"--prefix={request.prefix}",
        "--target-os=android",
        "--arch=aarch64" if request.abi == "arm64-v8a" else "--arch=x86_64",
        "--cpu=armv8-a" if request.abi == "arm64-v8a" else "--cpu=x86-64",
        "--enable-cross-compile",
        f"--cc={compiler}",
        f"--cxx={compiler_cpp}",
        f"--strip={toolchain / 'llvm-strip'}",
        f"--nm={toolchain / 'llvm-nm'}",
        f"--ar={toolchain / 'llvm-ar'}",
        f"--ranlib={toolchain / 'llvm-ranlib'}",
        f"--sysroot={toolchain / '../sysroot'}",
        "--enable-pic",
        "--enable-static",
        "--disable-shared",
        "--disable-programs",
        "--disable-doc",
        "--disable-debug",
        "--disable-network",
        "--disable-postproc",
        "--disable-avdevice",
        "--disable-avfilter",
        "--disable-everything",
        "--enable-demuxer=mpegps",
        "--enable-decoder=mpeg1video",
        "--enable-decoder=adpcm_adx",
        "--enable-parser=mpegvideo",
        "--enable-protocol=file",
        "--enable-swscale",
        "--enable-swresample",
        "--enable-avformat",
        "--enable-avcodec",
        "--enable-avutil",
        "--disable-autodetect",
        "--disable-iconv",
        "--disable-zlib",
        "--disable-bzlib",
        "--disable-lzma",
        "--disable-sdl2",
        "--disable-vulkan",
        "--disable-vaapi",
        "--disable-vdpau",
        "--disable-videotoolbox",
        "--disable-audiotoolbox",
        "--disable-libdrm",
        "--disable-appkit",
        "--pkg-config=/bin/false",
        "--extra-cflags=-fPIC",
        "--extra-ldflags=-fPIC",
        "--extra-version=android-port",
        *ffmpeg_assembly_configuration(request.abi),
    ]
    subprocess.run(configure, cwd=build_directory, check=True)
    subprocess.run(["make", f"-j{jobs}"], cwd=build_directory, check=True)
    subprocess.run(["make", "install"], cwd=build_directory, check=True)
    if not all(path.is_file() for path in required):
        raise SystemExit("FFmpeg install completed without required files: " + ", ".join(
            str(path) for path in required if not path.is_file()
        ))
    marker.write_text(contract, encoding="utf-8")


def publish_dependency_manifest(request: NativeDependencyRequest) -> None:
    manifest = native_dependency_manifest(request)
    try:
        content = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Android dependency manifest is unreadable: {manifest}: {error}") from error
    content["ffmpeg"] = {
        "version": FFMPEG_VERSION,
        "contract": ffmpeg_contract(request).splitlines(),
        "libraries": list(FFMPEG_LIBRARIES),
    }
    manifest.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    runtime = native_dependency_cxx_runtime(request)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ndk_cxx_shared_library(request.ndk, request.abi), runtime)


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
    ffmpeg_build(request, jobs)
    publish_dependency_manifest(request)
    missing = [
        request.prefix / relative
        for relative in ("android-port-dependencies.json", *NATIVE_DEPENDENCY_FILES)
        if not (request.prefix / relative).is_file()
    ]
    if not native_dependency_cxx_runtime(request).is_file():
        missing.append(native_dependency_cxx_runtime(request))
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
    cleanup = commands.add_parser(
        "remove-emulator-test-directory", help="remove one bounded Downloads test directory"
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
    if args.operation == "remove-emulator-test-directory":
        return remove_emulator_test_directory(args.serial, args.path)
    raise AssertionError(f"unknown command {args.operation}")


if __name__ == "__main__":
    raise SystemExit(main())
