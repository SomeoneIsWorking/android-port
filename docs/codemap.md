# Ownership map

| Responsibility | Owner | Public entry |
| --- | --- | --- |
| CLI, package profiles, shared emulator locking | `tools/android_port.py` | `main`, `load_android_port_profile`, `with_profile_emulator_lock` |
| Prefix ABI/API, paths, capability inventory | `tools/android_native_contract.py` | `NativeDependencyRequest`, `DEPENDENCY_CAPABILITY_FILES` |
| Native dependency builds and prefix metadata | `tools/android_native_dependencies.py`, `android_port/native_deps/` | `build_native_dependencies` |
| FFmpeg source identity, features, cross compilation, cache validity | `tools/android_media.py` | `ffmpeg_build`, `ffmpeg_contract` |
| Coherent host JDK selection | `tools/android_java.py` | `select_java_home` |
| Gradle runtime source staging, NDK ELF inspection, APK runtime inventory | `tools/android_package.py` | `stage_gradle_runtime`, `verify_native_entry`, `inspect_apk_runtime` |

Titles own application identity, Gradle project/version selection, install validation,
notification wording, native JNI entry composition, and release-performance evidence.
Lucent owns Android runtime Activity, input acquisition, and SAF import mechanics.
