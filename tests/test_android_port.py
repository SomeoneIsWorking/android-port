#!/usr/bin/env python3
"""Focused checks for the shared Android device contract."""

from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEST_SCRATCH = ROOT / "scratch" / "test-android-port"
SPEC = importlib.util.spec_from_file_location(
    "android_port", ROOT / "tools/android_port.py"
)
assert SPEC is not None and SPEC.loader is not None
android_port = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = android_port
SPEC.loader.exec_module(android_port)


def temporary_directory() -> tempfile.TemporaryDirectory[str]:
    TEST_SCRATCH.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=TEST_SCRATCH)


def main() -> int:
    assert android_port.SHARED_AVD == "codex_shared_api35"
    assert android_port.DEFAULT_ANDROID_API == 21
    from android_java import java_major

    assert java_major('openjdk version "26.0.1"') == 26
    assert java_major("javac 26.0.1") == 26
    assert java_major('openjdk version "1.8.0_442"') == 8
    assert java_major("not a compiler version") is None
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
    configure = android_port.native_dependency_configure_command(
        contract, Path("/work/build")
    )
    assert configure[:4] == ["cmake", "-S", str(android_port.NATIVE_DEPS_SOURCE), "-B"]
    assert "-DANDROID_ABI=arm64-v8a" in configure
    assert "-DANDROID_PLATFORM=android-26" in configure
    assert "-DCMAKE_INSTALL_LIBDIR=lib" in configure
    assert "-DCMAKE_INSTALL_PREFIX=/work/prefix" in configure
    assert android_port.native_dependency_manifest(contract) == Path(
        "/work/prefix/android-port-dependencies.json"
    )
    assert android_port.native_dependency_cxx_runtime(contract) == Path(
        "/work/prefix/share/android-port/cxx/arm64-v8a/libc++_shared.so"
    )
    # arm64 keeps its NEON: hidden visibility, not disabled assembly, is what
    # makes the ff_tx_tab_* relocations legal in a PIE shared object.
    assert android_port.ffmpeg_assembly_configuration("arm64-v8a") == ()
    assert "-fvisibility=hidden" in android_port.FFMPEG_CFLAGS
    assert "cflags=-fPIC -fvisibility=hidden" in android_port.ffmpeg_contract(contract)
    assert android_port.ffmpeg_assembly_configuration("x86_64") == (
        "--disable-x86asm",
        "--disable-inline-asm",
    )
    assert "api=26" in android_port.ffmpeg_contract(contract)
    assert "--enable-demuxer=mpegps,asf" in android_port.ffmpeg_contract(contract)
    assert (
        "mpeg1video,adpcm_adx,wmav1,wmav2,wmapro,wmavoice"
        in android_port.ffmpeg_contract(contract)
    )
    assert "-G" in configure and configure[configure.index("-G") + 1] == "Ninja"
    assert "lib/libSDL3_ttf.a" in android_port.dependency_files(("text",))
    assert "lib/libbz2.a" in android_port.dependency_files(("bzip2",))
    assert android_port.ffmpeg_required_files(contract.prefix)[0] == Path(
        "/work/prefix/include/libavutil/avutil.h"
    )
    members = [
        tarfile.TarInfo("FFmpeg-n7.1.1"),
        tarfile.TarInfo("FFmpeg-n7.1.1/configure"),
    ]
    assert android_port.ffmpeg_archive_root(members) == "FFmpeg-n7.1.1"
    try:
        android_port.ffmpeg_archive_root([*members, tarfile.TarInfo("elsewhere/x")])
    except SystemExit as error:
        assert "exactly one top-level directory" in str(error)
    else:
        raise AssertionError("FFmpeg archive with two roots was accepted")
    with temporary_directory() as temporary:
        ndk = Path(temporary) / "ndk"
        cxx_shared = (
            ndk
            / "toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib"
            / "aarch64-linux-android/libc++_shared.so"
        )
        cxx_shared.parent.mkdir(parents=True)
        cxx_shared.touch()
        assert android_port.ndk_cxx_shared_library(ndk, "arm64-v8a") == cxx_shared
    assert (
        android_port.removable_emulator_test_directory(
            "/sdcard/Download/benefactor-emulator-test"
        )
        == "/sdcard/Download/benefactor-emulator-test"
    )
    for path in (
        "/sdcard/Download",
        "/sdcard/Download/nested/emulator-test",
        "/sdcard/Documents/test-emulator-test",
    ):
        try:
            android_port.removable_emulator_test_directory(path)
        except SystemExit:
            pass
        else:
            raise AssertionError(f"expected cleanup refusal for {path}")
    with temporary_directory() as temporary:
        workspace = Path(temporary)
        profile_path = workspace / "title/platform/android/android-port-profile.json"
        prefix = workspace / "build/deps/android/arm64-v8a"
        native_library = workspace / "title/build/android/arm64-v8a/libmain.so"
        profile_path.parent.mkdir(parents=True)
        native_library.parent.mkdir(parents=True)
        native_library.write_bytes(b"title runtime")
        for relative in android_port.NATIVE_DEPENDENCY_FILES:
            artifact = prefix / relative
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(relative.encode("utf-8"))
        cxx_runtime = prefix / "share/android-port/cxx/arm64-v8a/libc++_shared.so"
        cxx_runtime.parent.mkdir(parents=True, exist_ok=True)
        cxx_runtime.write_bytes(b"ndk runtime")
        (prefix / "android-port-dependencies.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "abi": "arm64-v8a",
                    "platform": "android-26",
                    "capabilities": list(android_port.DEPENDENCY_CAPABILITY_FILES),
                }
            ),
            encoding="utf-8",
        )
        profile_path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "nativeDependencies": {
                        "abi": "arm64-v8a",
                        "api": 26,
                        "prefix": "../../../build/deps/android/arm64-v8a",
                        "capabilities": list(android_port.DEPENDENCY_CAPABILITY_FILES),
                    },
                    "package": {
                        "nativeLibrary": "../../build/android/arm64-v8a/libmain.so",
                        "jniLibs": "../../build/android/native",
                    },
                    "sharedEmulator": {
                        "lock": "../../../coord/android-emulator.lock",
                        "serial": "emulator-5554",
                    },
                }
            ),
            encoding="utf-8",
        )
        profile = android_port.load_android_port_profile(profile_path)
        assert profile.prefix == prefix
        assert profile.emulator_lock == workspace / "coord/android-emulator.lock"
        assert android_port.native_dependency_request_for_profile(
            profile, Path("/sdk/ndk/28.2.13676358")
        ) == android_port.NativeDependencyRequest(
            abi="arm64-v8a",
            api=26,
            ndk=Path("/sdk/ndk/28.2.13676358"),
            prefix=prefix,
        )
        assert android_port.package_runtime_sources(profile) == (
            ("libmain.so", native_library),
            ("libSDL3.so", prefix / "lib/libSDL3.so"),
            ("libc++_shared.so", cxx_runtime),
        )
        assert android_port.stage_package_runtime(profile) == 0
        staged = workspace / "title/build/android/native/arm64-v8a"
        assert (staged / "libmain.so").read_bytes() == b"title runtime"
        assert (staged / "libSDL3.so").read_bytes() == b"lib/libSDL3.so"
        assert (staged / "libc++_shared.so").read_bytes() == b"ndk runtime"
        assert android_port.profile_adb_command(
            profile, ["adb", "-s", "emulator-5554", "install", "game.apk"]
        ) == ("adb", "-s", "emulator-5554", "install", "game.apk")
        try:
            android_port.profile_adb_command(
                profile, ["adb", "-s", "another-device", "install", "game.apk"]
            )
        except SystemExit as error:
            assert "emulator-5554" in str(error)
        else:
            raise AssertionError("profile lock accepted a non-profile ADB serial")
        narrow_profile = json.loads(profile_path.read_text(encoding="utf-8"))
        narrow_profile["nativeDependencies"]["capabilities"] = ["sdl3", "media"]
        profile_path.write_text(json.dumps(narrow_profile), encoding="utf-8")
        media_profile = android_port.load_android_port_profile(profile_path)
        assert media_profile.capabilities == ("sdl3", "media")
        assert android_port.package_runtime_sources(media_profile) == (
            ("libmain.so", native_library),
            ("libSDL3.so", prefix / "lib/libSDL3.so"),
            ("libc++_shared.so", cxx_runtime),
        )
        invalid_profile = json.loads(profile_path.read_text(encoding="utf-8"))
        invalid_profile["nativeDependencies"]["capabilities"] = [
            "sdl3",
            "invented-codec",
        ]
        profile_path.write_text(json.dumps(invalid_profile), encoding="utf-8")
        try:
            android_port.load_android_port_profile(profile_path)
        except SystemExit as error:
            assert "invented-codec" in str(error)
        else:
            raise AssertionError("profile accepted an unknown capability")
        profile_path.write_text(json.dumps(narrow_profile), encoding="utf-8")
        (prefix / "android-port-dependencies.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "abi": "arm64-v8a",
                    "platform": "android-34",
                    "capabilities": list(android_port.DEPENDENCY_CAPABILITY_FILES),
                }
            ),
            encoding="utf-8",
        )
        try:
            android_port.package_runtime_sources(media_profile)
        except SystemExit as error:
            assert "platform='android-34', expected 'android-26'" in str(error)
        else:
            raise AssertionError("profile accepted a prefix built for another API")
    with temporary_directory() as temporary:
        apk = Path(temporary) / "app.apk"
        entries = (
            "lib/arm64-v8a/libmain.so",
            "lib/arm64-v8a/libSDL3.so",
            "lib/arm64-v8a/libc++_shared.so",
            "resources.arsc",
        )
        with zipfile.ZipFile(apk, "w") as archive:
            for name in entries:
                archive.writestr(name, "synthetic")
        assert android_port.inspect_apk_runtime(apk, "arm64-v8a") == entries
        try:
            android_port.inspect_apk_runtime(apk, "x86_64")
        except SystemExit as error:
            assert "lib/x86_64/libmain.so" in str(error)
        else:
            raise AssertionError("APK inspection accepted the wrong ABI")
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("resources.arsc", "synthetic")
        try:
            android_port.inspect_apk_runtime(apk, "arm64-v8a")
        except SystemExit as error:
            assert "libmain.so" in str(error)
        else:
            raise AssertionError("APK inspection accepted missing native libraries")
    with temporary_directory() as temporary:
        root = Path(temporary)
        apk = root / "app.apk"
        apk.touch()
        signer = root / "sdk/build-tools/35.0.0/apksigner"
        signer.parent.mkdir(parents=True)
        signer.touch()
        digest = "A1" * 32
        with patch(
            "android_package.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout=f"Verifies\nSigner #1 certificate SHA-256 digest: {digest}\n",
                stderr="",
            ),
        ) as execution:
            assert (
                android_port.verify_apk_signature(apk, root / "sdk", "35.0.0", 21)
                == digest
            )
            command = execution.call_args.args[0]
            assert command[:4] == [str(signer), "verify", "--min-sdk-version", "21"]
            assert "--print-certs" in command
        for result in (
            SimpleNamespace(returncode=1, stdout="invalid signature", stderr=""),
            SimpleNamespace(returncode=0, stdout="Verifies\n", stderr=""),
            SimpleNamespace(
                returncode=0,
                stdout=(
                    f"Signer #1 certificate SHA-256 digest: {digest}\n"
                    f"Signer #2 certificate SHA-256 digest: {digest}\n"
                ),
                stderr="",
            ),
        ):
            with patch("android_package.subprocess.run", return_value=result):
                try:
                    android_port.verify_apk_signature(apk, root / "sdk", "35.0.0", 21)
                except SystemExit:
                    pass
                else:
                    raise AssertionError(
                        "APK signature check accepted an invalid result"
                    )
    with temporary_directory() as temporary:
        from android_package import verify_native_entry

        root = Path(temporary)
        library = root / "libmain.so"
        library.touch()
        readelf = root / "ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
        readelf.parent.mkdir(parents=True)
        readelf.touch()
        cases = (
            ("1: 00001234 32 FUNC GLOBAL DEFAULT 9 main", True),
            ("1: 00001234 32 FUNC WEAK PROTECTED 9 main", True),
            ("1: 00000000 0 NOTYPE GLOBAL DEFAULT UND main", False),
            ("1: 00001234 32 FUNC GLOBAL HIDDEN 9 main", False),
            ("1: 00001234 32 OBJECT GLOBAL DEFAULT 9 main", False),
            ("1: 00001234 32 FUNC GLOBAL DEFAULT 9 unrelated", False),
            ("no symbol table", False),
        )
        for output, accepted in cases:
            with patch(
                "android_package.subprocess.run",
                return_value=SimpleNamespace(stdout=output),
            ) as run:
                refused = False
                try:
                    verify_native_entry(library, root / "ndk")
                except SystemExit as error:
                    refused = True
                    assert "does not export a defined visible" in str(error)
                assert refused != accepted, output
                assert "--wide" in run.call_args.args[0]
    with temporary_directory() as temporary:
        root = Path(temporary)
        prefix = root / "prefix"
        project = root / "title"
        sdl = prefix / "share/android-port/sdl3-java/org/libsdl/app/SDLActivity.java"
        wrapper = prefix / "share/android-port/gradle-wrapper/gradlew"
        framework = (
            prefix
            / "share/android-port/framework-java/io/github/someoneisworking/android/AndroidActivity.java"
        )
        for source in (sdl, wrapper):
            source.parent.mkdir(parents=True)
            source.write_text(source.name, encoding="utf-8")
        try:
            android_port.stage_gradle_runtime(prefix, project)
        except SystemExit as error:
            assert "framework-java" in str(error)
        else:
            raise AssertionError(
                "staging accepted a prefix without Android framework Java"
            )
        assert not (project / "app/src/main/java").exists()
        framework.parent.mkdir(parents=True)
        framework.write_text("AndroidActivity", encoding="utf-8")
        android_port.stage_gradle_runtime(prefix, project)
        assert (
            project / "app/src/main/java/org/libsdl/app/SDLActivity.java"
        ).read_text(encoding="utf-8") == "SDLActivity.java"
        assert (
            project
            / "app/src/main/java/io/github/someoneisworking/android/AndroidActivity.java"
        ).read_text(encoding="utf-8") == "AndroidActivity"
        assert (project / "gradlew").read_text(encoding="utf-8") == "gradlew"
    print("android-port: shared prefix, package, Java and AVD contracts passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
