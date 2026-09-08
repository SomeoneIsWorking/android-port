# Project state

This is the factual capability inventory for the shared Android build and
package boundary. The README remains the ownership and usage guide.

## Comparison baseline

The baseline is each native game port carrying its own Android SDK/NDK setup,
dependency prefix, JNI runtime staging, archive handling, and emulator lock.
This repository centralizes those mechanics without containing a title, game
asset, or installable application.

## Current focus

Current focus: S001 — proving the asset-free native dependency and synthetic
package contract on the declared Android ABI/API floor.

## Capability inventory

| ID | Capability or outcome | State | Factual dependency | Goals |
| --- | --- | --- | --- | --- |
| S001 | Pinned Android native dependency prefix for SDL3, SDL3_image, SDL3_ttf, FreeType, fmt, bzip2, and FFmpeg | partial | — | — |
| S002 | Profile-owned ABI/API/capability validation | verified | S001 | — |
| S003 | Exact runtime library staging for a title package | verified | S001, S002 | — |
| S004 | Shared emulator lock and serial policy | partial | S002 | — |
| S005 | Installable APK build and inspection | blocked | No title application exists in this shared repository | — |
| S006 | Linux/macOS/Windows desktop product | blocked | This repository owns Android build/package plumbing, not a desktop runtime | — |

### S001 — Android dependency prefix

The pinned ExternalProject revisions and FFmpeg checksum are checked in. The
CI Android job builds arm64-v8a/API 35 without game assets. Release consumers
still need their complete title build and package gate.

Evidence: the revisions/checksum and media feature contract are tracked; an
NDK 28.2.13676358 Clang arm64-v8a/API 24 build produced the complete native prefix,
including SDL3_ttf, bzip2, and ASF/WMA alongside the existing MPEG1/ADX path.
The synthetic test checks profile, package, and capability positives/negatives.
Gap: a consumer must still complete its title build and package gate.

### S002 — Profile validation

`tests/test_android_port.py` exercises valid profiles and rejects unknown
capabilities and mismatched prefix API.

Evidence: the test passes both valid and negative profile cases.

### S003 — Runtime staging

The synthetic package test validates and stages `libmain.so`, SDL3, and the
matching NDK C++ runtime under the profile ABI.

Evidence: the test passes and checks all three staged runtime artifacts.

### S004 — Emulator policy

The synthetic test covers command validation. A real emulator install,
SAF/device run belongs to a consuming title with an Android application.

Evidence: the profile-bound serial and lock command negative cases pass.
Gap: no title APK exists here for a device run.

### S005 — APK build and inspection

Blocked because no Android application, JNI entry point, Gradle project,
package identity, title asset validator, or APK exists here. Consuming ports
own the complete package and device gate; fabricating an APK in this shared
plumbing repository would test a different product.

Blocker: the shared repository has no Android application or title package to
build and inspect.

### S006 — Desktop product

Blocked because this repository is Android packaging/build plumbing, not a
desktop runtime. Host CI only runs its asset-free Python contract tests;
native Android compilation runs on Linux with the Android NDK.

Blocker: no desktop runtime is owned by this repository.

## Host CI support

`.github/workflows/ci.yml` uses complete-history, read-only checkouts and no game
assets. The Android job builds the actual pinned native dependency prefix for
arm64-v8a/API 35; the host job exercises the synthetic profile/staging policy.
No desktop or APK-install job is claimed because this repository does not own
those products.
