# android-port

Shared Android packaging and device-verification plumbing for native game ports.

Lucent owns the reusable Android runtime shell (SDL Activity, app-private data, SAF staging, and raw
touch contacts). A game owns its package identity, native entry point, game-file validation, touch
actions/layout, UI art, and release evidence. This repository owns the build/packaging seam between
them: pinned Gradle/NDK contract validation, native-artifact staging, APK inspection, and the common
Android Virtual Device policy.

Every package with native C++ code must stage the library returned by
`ndk_cxx_shared_library(ndk, abi)` as `jniLibs/<abi>/libc++_shared.so` and require that same path
in its APK inspection. This is title-neutral NDK runtime plumbing; it belongs here rather than in
each game's build script.

## Shared emulator

`codex_shared_api35` is the workspace's persistent API 35 Pixel 7 AVD. It is one foreground device:
builds may run concurrently, but an APK install, launch, input, screenshot, logcat capture, or other
interactive device operation must hold the shared lock. Do not create a second AVD merely to avoid a
short wait. Add an isolated AVD only when two active tasks demonstrably need simultaneous interactive
device work.

```sh
./run.sh
uv run --frozen python tools/android_port.py emulator-status --require-running
uv run --frozen python tools/android_port.py with-emulator-lock \
  --lock /home/bhamil/repo/psx/coord/android-emulator.lock -- adb -s emulator-5554 install -r game.apk
```

The lock path is deliberately supplied by the workspace, rather than hidden in a user home, so every
participating project contends for the same resource. A device command must name its ADB serial.

When testing with user-supplied files in a Downloads directory, name the one-off directory
`*-emulator-test` and remove it through the bounded cleanup command, under the same lock:

```sh
uv run --frozen python tools/android_port.py with-emulator-lock \
  --lock /home/bhamil/repo/benefactor/coord/android-emulator.lock -- \
  uv run --frozen python tools/android_port.py remove-emulator-test-directory \
  --serial emulator-5554 --path /sdcard/Download/benefactor-emulator-test
```

## Consumer contract

A consumer invokes this tool to check the configured SDK, NDK and coherent JDK before its own CMake
and Gradle build. It supplies title-specific Gradle source, assets, package ID, version and signing
credentials. Release signing is never synthesized here; the consuming title must provide its
maintainer key and validate the assembled artifact.
