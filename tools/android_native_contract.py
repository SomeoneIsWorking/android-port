"""Pinned Android prefix capabilities and build inputs shared by every consumer."""

import re
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
    "png": (
        "include/png.h",
        "lib/libpng16.a",
        "lib/pkgconfig/libpng.pc",
        "lib/pkgconfig/zlib.pc",
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
    "shaping": (
        "include/harfbuzz/hb.h",
        "lib/libharfbuzz.a",
        "lib/pkgconfig/harfbuzz.pc",
    ),
    "sqlite": (
        "include/sqlite3.h",
        "lib/libsqlite3.a",
        "lib/pkgconfig/sqlite3.pc",
    ),
    "json": (
        "include/nlohmann/json.hpp",
        "share/cmake/nlohmann_json/nlohmann_jsonConfig.cmake",
    ),
    "svg": ("include/nanosvg/nanosvg.h", "include/nanosvg/nanosvgrast.h"),
    "bzip2": ("include/bzlib.h", "lib/libbz2.a"),
    "tls": (
        "include/openssl/ssl.h",
        "lib/libssl.a",
        "lib/libcrypto.a",
    ),
    "http": (
        "include/curl/curl.h",
        "lib/libcurl.a",
        "lib/cmake/CURL/CURLConfig.cmake",
    ),
    "webp": (
        "include/webp/decode.h",
        "lib/libwebp.a",
        "lib/libsharpyuv.a",
        "share/WebP/cmake/WebPConfig.cmake",
    ),
    # SDL3_image built with its WebP decoder over the prefix's libwebp.
    "image_webp": (
        # Installed only when SDL3_image found the prefix's libwebp and decodes WebP with it.
        "lib/cmake/SDL3_image/Findwebp.cmake",
        "lib/libwebp.a",
        "lib/libwebpdemux.a",
    ),
    "vorbis": (
        "include/vorbis/vorbisfile.h",
        "lib/libogg.a",
        "lib/libvorbis.a",
        "lib/libvorbisfile.a",
    ),
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


def pinned_dependency_revisions() -> dict[str, str]:
    """The manifest key and value of each revision or version `native_deps` pins."""
    pins = dict(
        re.findall(
            r'^set\((ANDROID_PORT_\w+) "([^"]*)"\)',
            (NATIVE_DEPS_SOURCE / "CMakeLists.txt").read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    template = (NATIVE_DEPS_SOURCE / "android-port-dependencies.json.in").read_text(
        encoding="utf-8"
    )
    return {
        key: pins[variable]
        for key, variable in re.findall(r'"(\w+)": "@(ANDROID_PORT_\w+)@"', template)
    }
