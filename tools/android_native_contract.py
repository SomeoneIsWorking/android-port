"""Pinned Android prefix capabilities and build inputs shared by every consumer."""

from dataclasses import dataclass
from pathlib import Path

DEFAULT_ANDROID_API = 21
ROOT = Path(__file__).resolve().parents[1]
NATIVE_DEPS_SOURCE = ROOT / "android_port" / "native_deps"
DEPENDENCY_CAPABILITY_FILES = {
    "sdl3": (
        "lib/libSDL3.so",
        "lib/cmake/SDL3/SDL3Config.cmake",
        "share/android-port/sdl3-java/org/libsdl/app/SDLActivity.java",
        "share/android-port/gradle-wrapper/gradle/wrapper/gradle-wrapper.jar",
    ),
    "image": (
        "lib/libSDL3_image.a",
        "lib/cmake/SDL3_image/SDL3_imageConfig.cmake",
    ),
    "font": (
        "lib/libfreetype.a",
        "lib/cmake/freetype/freetype-config.cmake",
    ),
    "format": (
        "lib/libfmt.a",
        "lib/cmake/fmt/fmt-config.cmake",
    ),
    "text": (
        "lib/libSDL3_ttf.a",
        "lib/cmake/SDL3_ttf/SDL3_ttfConfig.cmake",
    ),
    "bzip2": ("include/bzlib.h", "lib/libbz2.a"),
    "media": (
        "include/libavutil/avutil.h",
        "lib/libavformat.a",
        "lib/libavcodec.a",
        "lib/libswscale.a",
        "lib/libswresample.a",
        "lib/libavutil.a",
    ),
}
NATIVE_DEPENDENCY_FILES = tuple(
    relative
    for capability in DEPENDENCY_CAPABILITY_FILES.values()
    for relative in capability
)
NDK_TRIPLES = {
    "arm64-v8a": "aarch64-linux-android",
    "x86_64": "x86_64-linux-android",
}


@dataclass(frozen=True)
class NativeDependencyRequest:
    abi: str
    api: int
    ndk: Path
    prefix: Path
