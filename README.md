# android-port

Shared Android packaging and device-verification plumbing for native game ports.

The shared Android framework owns the reusable Android runtime shell (SDL Activity, persistent package
storage, SAF ZIP staging, resumable copies, notifications, and raw touch contacts). A game owns its package identity, native entry point, game-file validation, touch
actions/layout, UI art, and release evidence. This repository owns the build/packaging seam between
them: pinned Gradle/NDK contract validation, the common cross-compiled native
dependency prefix, native-artifact staging, APK inspection, and the common Android
Virtual Device policy. The prefix holds the pinned SDL3, SDL3_image, SDL3_ttf, FreeType,
fmt, bzip2, and minimal static FFmpeg set required by native ports; its manifest records
the ABI/API and FFmpeg configuration so a title never combines host libraries with
Android artifacts. FFmpeg retains MPEG-PS/MPEG-1/ADX and includes ASF with
WMA1/WMA2/WMA Pro/WMA Voice; this feature list participates in the cache contract.
`text` selects SDL3_ttf and `bzip2` selects the bounded-installer dependency.

Native-prefix mechanics live in `tools/android_native_dependencies.py`, shared
input contracts in `android_native_contract.py`, media builds in `android_media.py`,
JDK selection in `android_java.py`, and Gradle/runtime staging and APK inspection in
`android_package.py`. The CLI remains the public package/profile/device interface.
The prefix also publishes SDL's pinned Gradle wrapper launcher/JAR; consuming titles
retain their version/checksum properties and Gradle project policy.

Every package with native C++ code stages the prefix's
`share/android-port/cxx/<abi>/libc++_shared.so` as
`jniLibs/<abi>/libc++_shared.so` and requires that same path in its APK
inspection. The prefix copies it from `ndk_cxx_shared_library(ndk, abi)`, so
title Gradle files never recreate NDK architecture lookup.

## Shared emulator

For an ARM64 guest on an x86-64 Linux host, the optional
[Cuttlefish launcher](docs/android-emulator.md) holds this same device lock.
It requires a provisioned host bundle, system images, and immutable container;
its current image qualification limitations are recorded in that contract.

`codex_shared_api35` is the workspace's persistent API 35 Pixel 7 AVD. It is one foreground device:
builds may run concurrently, but an APK install, launch, input, screenshot, logcat capture, or other
interactive device operation must hold the shared lock. Do not create a second AVD merely to avoid a
short wait. Add an isolated AVD only when two active tasks demonstrably need simultaneous interactive
device work.

```sh
./run.sh
uv run --frozen python tools/android_port.py emulator-status --require-running
uv run --frozen python tools/android_port.py with-emulator-lock \
  --lock <workspace>/coord/android-emulator.lock -- adb -s emulator-5554 install -r game.apk
```

The lock path is deliberately supplied by the workspace, rather than hidden in a user home, so every
participating project contends for the same resource. A device command must name its ADB serial.

When testing with user-supplied files in a Downloads directory, name the one-off directory
`*-emulator-test` and remove it through the bounded cleanup command, under the same lock:

```sh
uv run --frozen python tools/android_port.py with-emulator-lock \
  --lock <workspace>/coord/android-emulator.lock -- \
  uv run --frozen python tools/android_port.py remove-emulator-test-directory \
  --serial emulator-5554 --path /sdcard/Download/benefactor-emulator-test
```

## Consumer contract

A consumer invokes this tool to build the configured SDK/NDK native prefix before
its own CMake and Gradle build:

```sh
uv run --frozen python tools/android_port.py build-native-deps \
  --ndk "$ANDROID_HOME/ndk/$ANDROID_NDK_VERSION" \
  --abi arm64-v8a --api 21 --prefix /path/to/build/deps/android/android-21/arm64-v8a
```

It supplies title-specific Gradle source, assets, package ID, version and signing
credentials. Release signing is never synthesized here; the consuming title must
provide its maintainer key and validate the assembled artifact.

## Package profile

A title puts one portable `platform/android/android-port-profile.json` beside its Gradle project.
It declares only the shared build/package inputs; title identity, JNI, SAF wording, touch layout and
Gradle task selection stay in the title.

```json
{
  "schema": 1,
  "nativeDependencies": {
    "abi": "arm64-v8a",
    "api": 21,
    "prefix": "../../build/deps/android/android-21/arm64-v8a",
    "capabilities": ["sdl3", "image", "font", "format", "media"]
  },
  "package": {
    "nativeLibrary": "../../build/android/arm64-v8a/libmain.so",
    "jniLibs": "../../build/android/native"
  },
  "sharedEmulator": {
    "lock": "../../../coord/android-emulator.lock",
    "serial": "emulator-5554"
  }
}
```

All paths are relative to the profile, so the file has no machine-specific path. `jniLibs` is a
title build output, not a source-tree directory. The title supplies its host NDK path once; ABI, API and
prefix then come only from the profile:

```sh
uv run --frozen python tools/android_port.py build-profile-native-deps \
  --profile platform/android/android-port-profile.json \
  --ndk "$ANDROID_HOME/ndk/$ANDROID_NDK_VERSION"
```

After the title builds `libmain.so`, stage the exact runtime set that its Gradle source set consumes:

```sh
uv run --frozen python tools/android_port.py stage-package-runtime \
  --profile platform/android/android-port-profile.json
```

The bounded capabilities are `sdl3`, `image`, `font`, `format`, and `media`. `sdl3` is required because
every package stages its SDL runtime; the other entries name the title's actual image, font/FreeType,
fmt, and FFmpeg needs. This refuses unknown or duplicate selections, a prefix whose manifest ABI/API or
declared capabilities do not match the profile, an incomplete selected capability, or a setup-only
package without `libmain.so`. It stages exactly `libmain.so`, `libSDL3.so`, and the matching NDK
`libc++_shared.so` below `jniLibs/<abi>/`; the title's package inspection then verifies the resulting APK
and its own signing/asset policy.

Interactive shared-emulator work always goes through the same profile instead of spelling a second
lock path or serial:

```sh
uv run --frozen python tools/android_port.py with-profile-emulator-lock \
  --profile platform/android/android-port-profile.json -- \
  adb -s emulator-5554 install -r build/android/project/app.apk
```

The command rejects a different ADB serial before it acquires the lock.

## Android application framework

`android_port/java/io/github/someoneisworking/android` is the shared Android
application framework. It owns Activity lifecycle helpers, SAF ZIP import,
persistent OBB-backed staging, resumable copies, and determinate import
notifications. Consumers provide title identity validation, package identity,
and their UI wording. Lucent may be pinned for logging, configuration, or focused
helpers; it does not own the Android application framework.

A resumed document copy compares its staged prefix with the reopened SAF source
before appending. If the provider changed the document at the same URI, the
framework discards that partial copy and refuses the attempt; the next selection
starts clean.
Android removes package-specific OBB storage on uninstall. Consumers that need
files across uninstall must use a separate user-selected shared-storage contract.

Run the platform-free Java contracts with a JDK capable of targeting Java 17:

```sh
uv run --frozen python tests/test_android_java.py
```

This compiles and runs touch, import lifetime, publication, and picker-request
tests in `build/java-tests/`; it needs no Android SDK. CI is configured to run
the same command on Linux, macOS, and Windows with Java 17. Android-dependent
Activity and SAF behavior is verified through consuming APKs.
