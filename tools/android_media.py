"""Pinned FFmpeg Android build; all media consumers share one feature contract."""

import hashlib
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

from android_native_contract import NDK_TRIPLES, ROOT, NativeDependencyRequest

FFMPEG_VERSION = "n7.1.1"
FFMPEG_URL = (
    f"https://github.com/FFmpeg/FFmpeg/archive/refs/tags/{FFMPEG_VERSION}.tar.gz"
)
FFMPEG_SHA256 = "f117507dc501f2a6c11f9241d8d0c3213846cfad91764361af37befd6b6c523d"
FFMPEG_LIBRARIES = ("avformat", "avcodec", "swscale", "swresample", "avutil")

FFMPEG_FEATURES = (
    "--enable-demuxer=mpegps,asf",
    "--enable-decoder=mpeg1video,adpcm_adx,wmav1,wmav2,wmapro,wmavoice",
    "--enable-parser=mpegvideo",
)


def ffmpeg_assembly_configuration(abi: str) -> tuple[str, ...]:
    """Keep emulator FFmpeg independent of a host NASM installation."""
    return ("--disable-x86asm", "--disable-inline-asm") if abi == "x86_64" else ()


def ffmpeg_contract(request: NativeDependencyRequest) -> str:
    """The installed FFmpeg archive set is valid only for this ABI/API pair."""
    return "\n".join(
        (
            f"ffmpeg={FFMPEG_VERSION}",
            f"abi={request.abi}",
            f"api={request.api}",
            *ffmpeg_assembly_configuration(request.abi),
            *FFMPEG_FEATURES,
            "",
        )
    )


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
    roots = {
        PurePosixPath(member.name).parts[0]
        for member in members
        if member.name.strip("./")
    }
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
                raise SystemExit(
                    f"Refusing linked FFmpeg archive member: {member.name}"
                )
            target = (cache / member.name).resolve()
            if target != destination and destination not in target.parents:
                raise SystemExit(
                    f"Refusing unsafe FFmpeg archive member: {member.name}"
                )
            bundle.extract(member, cache)
    if not (source / "configure").is_file():
        raise SystemExit(f"FFmpeg archive did not unpack a source tree at {source}")
    return source


def ffmpeg_build(request: NativeDependencyRequest, jobs: int) -> None:
    marker = request.prefix / ".android-port-ffmpeg-contract"
    required = ffmpeg_required_files(request.prefix)
    contract = ffmpeg_contract(request)
    if (
        marker.is_file()
        and marker.read_text(encoding="utf-8") == contract
        and all(path.is_file() for path in required)
    ):
        return

    source = ffmpeg_source_tree(ROOT / "build" / "source-cache")
    build_directory = ROOT / "build" / "ffmpeg" / f"{request.abi}-api{request.api}"
    if build_directory.exists():
        shutil.rmtree(build_directory)
    for file in (*required, marker):
        if file.exists():
            file.unlink()
    for directory in (
        request.prefix / "include/libavcodec",
        request.prefix / "include/libavformat",
        request.prefix / "include/libavutil",
        request.prefix / "include/libswresample",
        request.prefix / "include/libswscale",
    ):
        if directory.exists():
            shutil.rmtree(directory)
    build_directory.mkdir(parents=True, exist_ok=True)

    prebuilts = list((request.ndk / "toolchains/llvm/prebuilt").glob("*/bin"))
    if len(prebuilts) != 1:
        raise SystemExit(f"expected one Android NDK toolchain, found {len(prebuilts)}")
    toolchain = prebuilts[0]
    triple = NDK_TRIPLES[request.abi]
    compiler = toolchain / f"{triple}{request.api}-clang"
    compiler_cpp = toolchain / f"{triple}{request.api}-clang++"
    for program in (
        compiler,
        compiler_cpp,
        toolchain / "llvm-ar",
        toolchain / "llvm-ranlib",
    ):
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
        *FFMPEG_FEATURES,
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
        raise SystemExit(
            "FFmpeg install completed without required files: "
            + ", ".join(str(path) for path in required if not path.is_file())
        )
    marker.write_text(contract, encoding="utf-8")
