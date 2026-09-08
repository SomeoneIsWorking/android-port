#!/usr/bin/env python3
"""Run a provisioned ARM64 Cuttlefish guest on an x86-64 Linux host.

Provisioning inputs and the container contract are documented in
docs/android-emulator.md. This owner deliberately contains no title policy.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import platform
import shutil
import subprocess
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
CONTAINER_NAME = "codex-arm64-android"
ADB_SERIAL = "127.0.0.1:6520"


def allow_vsock(profile: dict) -> dict:
    """Permit only the AF_VSOCK socket denied by Podman's default profile."""
    result = json.loads(json.dumps(profile))
    matches = []
    for rule in result.get("syscalls", []):
        if (
            rule.get("names") == ["socket"]
            and rule.get("action") == "SCMP_ACT_ERRNO"
            and rule.get("args") == [{"index": 0, "value": 40, "valueTwo": 0, "op": "SCMP_CMP_EQ"}]
        ):
            matches.append(rule)
    if len(matches) != 1:
        raise ValueError(
            f"Expected one AF_VSOCK socket refusal, found {len(matches)}; "
            "review the installed Podman seccomp policy"
        )
    matches[0]["action"] = "SCMP_ACT_ALLOW"
    matches[0].pop("errnoRet", None)
    matches[0].pop("errno", None)
    return result


def command(build: Path, scratch: Path, image: str) -> list[str]:
    return [
        "podman",
        "--root",
        str(REPOSITORY / "build/containers"),
        "--runroot",
        str(scratch / "podman"),
        "run",
        "--rm",
        "--name",
        CONTAINER_NAME,
        "--memory-reservation",
        "5g",
        "--security-opt",
        f"seccomp={build / 'seccomp-vsock.json'}",
        "--security-opt",
        "label=disable",
        "--device",
        "/dev/vhost-vsock",
        "--device",
        "/dev/kvm",
        "--volume",
        f"{build}:/cf",
        "--volume",
        f"{scratch}:/tmp",
        "--mount",
        "type=tmpfs,destination=/cf/runtime/instances/cvd-1/internal,tmpfs-size=4608m",
        "--publish",
        f"{ADB_SERIAL}:6520",
        "--env",
        "ANDROID_HOST_OUT=/cf/host",
        "--env",
        "ANDROID_PRODUCT_OUT=/cf/images",
        "--workdir",
        "/cf",
        "--entrypoint",
        "/cf/host/bin/launch_cvd",
        image,
        "--report_anonymous_usage_stats=n",
        "--vm_manager=qemu_cli",
        "--gpu_mode=guest_swiftshader",
        "--device_external_network=tap",
        "--enable_tap_devices=false",
        "--start_webrtc=false",
        "--enable_host_bluetooth=false",
        "--enable_modem_simulator=false",
        "--start_gnss_proxy=false",
        "--console=true",
        "--daemon=false",
        "--restart_subprocesses=false",
        "--memory_mb=4096",
        "--cpus=4",
        "--use_sdcard=false",
        "--system_image_dir=/cf/images",
        "--instance_dir=/cf/runtime",
        "--assembly_dir=/cf/assembly-link",
        "--early_tmp_dir=/cf/runtime",
        "--enable_wifi=false",
    ]


def run(args: argparse.Namespace) -> int:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("This Cuttlefish TCG contract requires x86-64 Linux")
    if shutil.which("podman") is None:
        raise ValueError("Missing podman; on Fedora run: sudo dnf install podman")
    build = args.build.resolve()
    scratch = args.scratch.resolve()
    required = [
        Path("/dev/vhost-vsock"),
        Path("/dev/kvm"),
        build / "host/bin/launch_cvd",
        build / "host/bin/x86_64-linux-gnu/qemu/qemu-system-aarch64",
        build / "images/boot.img",
        build / "images/super.img",
        build / "images/android-info.txt",
        args.seccomp,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError("Missing Cuttlefish inputs: " + ", ".join(missing))
    if not (args.image.startswith("sha256:") or "@sha256:" in args.image):
        raise ValueError("Container image must be an immutable sha256 ID or digest")
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(f"Shared Android device is owned: {args.lock}") from error
        scratch.mkdir(parents=True, exist_ok=True)
        policy = allow_vsock(json.loads(args.seccomp.read_text()))
        (build / "seccomp-vsock.json").write_text(json.dumps(policy, indent=2) + "\n")
        argv = command(build, scratch, args.image)
        with (scratch / "launcher.log").open("w") as output:
            process = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT)
            (scratch / "launch.json").write_text(
                json.dumps({"pid": process.pid, "argv": argv}, indent=2) + "\n"
            )
            print(f"Cuttlefish PID {process.pid}; ADB {ADB_SERIAL}; log {output.name}", flush=True)
            try:
                return process.wait()
            except KeyboardInterrupt:
                # Stop only this named container while retaining the device lock.
                subprocess.run([*argv[:5], "stop", "--time", "10", CONTAINER_NAME], check=True)
                return process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image", required=True, help="Provisioned immutable Podman image ID/digest"
    )
    parser.add_argument("--build", type=Path, default=REPOSITORY / "build/cuttlefish")
    parser.add_argument("--scratch", type=Path, default=REPOSITORY / "scratch/cf")
    parser.add_argument("--lock", type=Path, default=REPOSITORY / "coord/android-emulator.lock")
    parser.add_argument("--seccomp", type=Path, default=Path("/usr/share/containers/seccomp.json"))
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Cuttlefish refused: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
