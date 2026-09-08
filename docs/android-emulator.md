# ARM64 Cuttlefish on x86-64 Linux

`tools/android_emulator.py` owns the optional cross-architecture device launcher.
It holds the same `coord/android-emulator.lock` as the shared SDK AVD throughout
the foreground container lifetime. It exposes ADB only on `127.0.0.1:6520`, runs
QEMU TCG with guest SwiftShader, and uses a silent audio device. This is a
correctness-test device; software CPU and graphics emulation cannot establish
Android device performance.

The launcher consumes an already provisioned Cuttlefish bundle in
`build/cuttlefish/host` and ARM64 system images in `build/cuttlefish/images`.
The host package must come from an **x86-64 target** at the same build ID as the
ARM64 image. The host archive published under the ARM64 target contains ARM64
host executables and cannot run directly on x86-64 Linux.

The official acquisition instructions are in
[Cuttlefish getting started](https://source.android.com/docs/devices/cuttlefish/get-started)
and the [host container documentation](https://github.com/google/android-cuttlefish/tree/main/container).
Android CI now serves artifact URLs through the public Build API v4 at
`androidbuild-pa.googleapis.com/v4`; retired `/android/internal/build/v3` calls
return a migration refusal. Artifact URLs expire; retain the build ID, artifact
name, and checksum rather than a signed URL.

The examined build 16102939 has these immutable inputs:

| Input | SHA-256 |
| --- | --- |
| `aosp_cf_arm64_only_phone-userdebug` / `aosp_cf_arm64_only_phone-img-16102939.zip` | `4363ec412b7f92a242310b6e4fe75477f8721dca7d48f4f961baf93e89a3dac6` |
| `aosp_cf_x86_64_only_phone-userdebug` / `cvd-host_package.tar.gz` | `73e3443191a34c7168072071c2cb54180880b637dd2e3c2864be5551a2e77765` |

Its guest identifies as Android 17 with fingerprint
`generic/aosp_cf_arm64_only_phone/vsoc_arm64_only:17/CP2A.260605.016/16102939:userdebug/test-keys`.
QEMU 10.2.90 stays live and ADB becomes available, but the first boot encountered
an upstream `WebViewZygote.getProcess` null `ChildZygoteProcess` after a WebView
preload socket timeout. Android automatically restarted its framework and then
reported `sys.boot_completed=1`; first boot took approximately 25 minutes under
TCG. The host VM did not restart. User-storage unlock follows system boot, so
wait for the storage path as well before transferring an import fixture. This
does not establish app compatibility or clean-boot reliability.

The prepared Android 16 fallback is build 14654133, API 36.1, fingerprint
`generic/aosp_cf_arm64_only_phone/vsoc_arm64_only:16/BP4A.251205.006/14654133:userdebug/test-keys`.
Its two archives passed the Build API's MD5 checks and have these SHA-256 values;
preparation alone is not guest boot evidence:

| Input | SHA-256 |
| --- | --- |
| `aosp_cf_arm64_only_phone-userdebug` / `aosp_cf_arm64_only_phone-img-14654133.zip` | `a5cd16d8f4a0f56ae5a18224ad4c95c678d4931e9c8526507d29d03083b1dd99` |
| `aosp_cf_x86_64_only_phone-userdebug` / `cvd-host_package.tar.gz` | `3f5696fa7efe5d3b49fba61de8dda95f7106af21f438642b868f0bdd75e09da5` |

Use the official orchestration container as the host environment. The examined
base digest is
`us-docker.pkg.dev/android-cuttlefish-artifacts/cuttlefish-orchestration/cuttlefish-orchestration@sha256:ecdb337615c719ed62e12593f7931a313d7c15a99a919e69fd87510e14a249e6`.
Its QEMU also requires Debian `libasound2t64` and `libpulse0`; include them in a
derived container, and pass the resulting immutable image ID. These are
container dependencies, not host package-manager substitutions. The launcher
refuses mutable image tags.

On Fedora the container needs `/dev/vhost-vsock` and `/dev/kvm`, rootless Podman,
and access to those device nodes. QEMU uses TCG for an ARM64 guest on x86; KVM
exposure satisfies the host tools' capability check and does not accelerate the
foreign architecture. The launcher's seccomp derivative changes exactly one
AF_VSOCK socket refusal from Podman's installed policy, preserving every other
rule. It refuses a missing or ambiguous match. SELinux labeling is disabled for
this emulator container so the vsock host services can bind their ports.

```sh
uv run --frozen python tools/android_emulator.py --image sha256:<provisioned-image-id>
```

Compiler and image inputs, VM disks, and container storage remain under `build/`.
Logs and transient socket paths remain under `scratch/cf/`; the container `/tmp`
is bound to that disk-backed directory. `--early_tmp_dir` points into the runtime
mount because the launcher hardlinks its early log to the final log. Separate
mounts would fail with `EXDEV`. The legacy assembly symlink must be outside the
actual runtime assembly directory, or it becomes a self-reference.

The instance's `internal` runtime directory is a bounded 4.5 GiB container tmpfs.
Upstream QEMU places its 4 GiB guest RAM backing file there. A regular disk-backed
directory caused approximately 100 GiB of writes during initial boot and put all
four TCG threads into disk wait as the host reclaimed those file-cache pages.
Guest RAM and internal IPC state are volatile; Android userdata, image inputs,
and logs remain on disk. This mount does not change guest memory size or Android
checks. It avoids treating continuously modified guest RAM as persistent data.
The container also requests a 5 GiB soft memory reservation for guest RAM and
QEMU overhead. This is a reclamation preference, not a hard memory cap or an
allocation guarantee. On a busy host, verify the emulator's resident/swap usage;
an almost entirely swapped guest cannot provide useful interactive evidence.

The guest intentionally has no external networking: `tap` mode with TAP devices
disabled is sufficient for local ADB/package tests. The examined upstream
`ConfigureNetworkSettings` overwrites its no-TAP fallback with an empty network
configuration; selecting `slirp` then produces QEMU's invalid `net=/255` argument.
Do not claim network coverage from this configuration.

Before installing an APK, require `adb -s 127.0.0.1:6520 shell getprop
sys.boot_completed` to return `1`. Read live guest logcat at
`build/cuttlefish/runtime/instances/cvd-1/logs/logcat` to distinguish advancing
first-boot work from a framework crash. Container liveness and an Android boot
logo are insufficient. Under the already-held lock, use serial-qualified ADB
commands for installation, input, screenshots, and title-local import tests.
The launcher owns no game files or title-specific commands.
