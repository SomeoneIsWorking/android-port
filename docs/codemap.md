# Ownership map

| Responsibility | Owner | Public entry |
| --- | --- | --- |
| CLI, package profiles, shared emulator locking | `tools/android_port.py` | `main`, `load_android_port_profile`, `with_profile_emulator_lock` |
| Cross-architecture Cuttlefish container lifetime and scoped device access | `tools/android_emulator.py` | `main`; [provisioning contract](android-emulator.md) |
| Prefix ABI/API, paths, capability inventory | `tools/android_native_contract.py` | `NativeDependencyRequest`, `DEPENDENCY_CAPABILITY_FILES` |
| Native dependency builds and prefix metadata | `tools/android_native_dependencies.py`, `android_port/native_deps/` | `build_native_dependencies` |
| FFmpeg source identity, features, cross compilation, cache validity | `tools/android_media.py` | `ffmpeg_build`, `ffmpeg_contract` |
| Coherent host JDK selection | `tools/android_java.py` | `select_java_home` |
| Gradle runtime source staging, NDK ELF inspection, APK runtime inventory and signer verification | `tools/android_package.py` | `stage_gradle_runtime`, `verify_native_entry`, `inspect_apk_runtime`, `verify_apk_signature` |
| Android application framework: Activity shell, SAF import, verified resume prefix, notification and contact lifetimes | `android_port/java/io/github/someoneisworking/android/` | `AndroidActivity`, `AndroidDocumentImport`, `AndroidImportResume`, `AndroidTouchContacts` |
| Platform-free Android framework contract tests | `tests/java/io/github/someoneisworking/android/`, `tests/test_android_java.py` | `test_android_java.py` |

Titles own application identity, Gradle project/version selection, install validation,
notification wording, native JNI entry composition, and release-performance evidence.
Lucent remains a utility library for logging, configuration, and title-neutral helpers;
it does not own the Android application framework.
