"""Cross-compiled shared native prefix build, metadata, and NDK runtime staging."""

import json
import shutil
import subprocess
from pathlib import Path

from android_media import (
    FFMPEG_LIBRARIES,
    FFMPEG_VERSION,
    ffmpeg_build,
    ffmpeg_contract,
)
from android_native_contract import (
    DEPENDENCY_CAPABILITY_FILES,
    NATIVE_DEPENDENCY_FILES,
    NATIVE_DEPS_SOURCE,
    NDK_TRIPLES,
    ROOT,
    NativeDependencyRequest,
)


def ndk_cxx_shared_library(ndk: Path, abi: str) -> Path:
    """Return the C++ runtime library required by an Android native package."""
    triple = NDK_TRIPLES.get(abi)
    if triple is None:
        raise SystemExit(f"Android ABI has no NDK C++ runtime mapping: {abi}")
    prebuilt = ndk / "toolchains" / "llvm" / "prebuilt"
    roots = list(prebuilt.glob("*/sysroot/usr/lib"))
    if len(roots) != 1:
        raise SystemExit(
            f"expected one NDK LLVM sysroot under {prebuilt}, found {len(roots)}"
        )
    library = roots[0] / triple / "libc++_shared.so"
    if not library.is_file():
        raise SystemExit(f"NDK C++ runtime is missing: {library}")
    return library


def native_dependency_manifest(request: NativeDependencyRequest) -> Path:
    return request.prefix / "android-port-dependencies.json"


def native_dependency_cxx_runtime_path(prefix: Path, abi: str) -> Path:
    return prefix / "share/android-port/cxx" / abi / "libc++_shared.so"


def native_dependency_cxx_runtime(request: NativeDependencyRequest) -> Path:
    return native_dependency_cxx_runtime_path(request.prefix, request.abi)


def publish_dependency_manifest(request: NativeDependencyRequest) -> None:
    manifest = native_dependency_manifest(request)
    try:
        content = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(
            f"Android dependency manifest is unreadable: {manifest}: {error}"
        ) from error
    content["ffmpeg"] = {
        "version": FFMPEG_VERSION,
        "contract": ffmpeg_contract(request).splitlines(),
        "libraries": list(FFMPEG_LIBRARIES),
    }
    content["capabilities"] = list(DEPENDENCY_CAPABILITY_FILES)
    manifest.write_text(
        json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def native_dependency_configure_command(
    request: NativeDependencyRequest, build_directory: Path
) -> list[str]:
    return [
        "cmake",
        "-S",
        str(NATIVE_DEPS_SOURCE),
        "-B",
        str(build_directory),
        "-G",
        "Ninja",
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
    java_source = (
        build_directory
        / "sources"
        / "sdl3"
        / "android-project"
        / "app"
        / "src"
        / "main"
        / "java"
    )
    if not java_source.is_dir():
        raise SystemExit(
            f"Android dependency build omitted SDL3 Java sources: {java_source}"
        )
    request.prefix.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest, native_dependency_manifest(request))
    shutil.copytree(
        java_source,
        request.prefix / "share" / "android-port" / "sdl3-java",
        dirs_exist_ok=True,
    )
    android_project = java_source.parents[3]
    wrapper = request.prefix / "share/android-port/gradle-wrapper"
    for relative in ("gradlew", "gradlew.bat", "gradle/wrapper/gradle-wrapper.jar"):
        source = android_project / relative
        if not source.is_file():
            raise SystemExit(
                f"SDL Android project omitted Gradle wrapper input: {source}"
            )
        destination = wrapper / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
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
    cache = build_directory / "CMakeCache.txt"
    if cache.is_file() and "CMAKE_GENERATOR:INTERNAL=Ninja" not in cache.read_text():
        shutil.rmtree(build_directory)
    subprocess.run(
        native_dependency_configure_command(request, build_directory), check=True
    )
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
            "Android dependency install omitted required artifacts:\n"
            + "\n".join(str(path) for path in missing)
        )
    print(f"Android dependency prefix: {request.prefix}")
    return 0
