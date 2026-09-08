"""Shared Gradle runtime sources, ELF entry validation, and APK runtime inspection."""

import shutil
import subprocess
import zipfile
from pathlib import Path


def ndk_tool(ndk: Path, name: str) -> Path:
    candidates = list((ndk / "toolchains/llvm/prebuilt").glob("*/bin/" + name))
    if len(candidates) != 1:
        raise SystemExit(
            f"expected one NDK {name}, found {len(candidates)} under {ndk}"
        )
    return candidates[0]


def verify_native_entry(library: Path, ndk: Path, entry: str = "main") -> None:
    if not library.is_file():
        raise SystemExit(f"native library is missing: {library}")
    result = subprocess.run(
        [str(ndk_tool(ndk, "llvm-readelf")), "--dyn-syms", "--wide", str(library)],
        text=True,
        capture_output=True,
        check=True,
    )
    symbols = [
        fields
        for line in result.stdout.splitlines()
        if len(fields := line.split()) >= 8 and fields[0].rstrip(":").isdigit()
    ]
    if not any(
        fields[7] == entry
        and fields[3] == "FUNC"
        and fields[4] in ("GLOBAL", "WEAK")
        and fields[5] in ("DEFAULT", "PROTECTED")
        and fields[6].isdigit()
        for fields in symbols
    ):
        raise SystemExit(
            f"{library} does not export a defined visible Android function {entry}; "
            f"inspected {len(symbols)} dynamic symbols"
        )


def stage_gradle_runtime(prefix: Path, project: Path, lucent_java: Path) -> None:
    sources = (
        (prefix / "share/android-port/sdl3-java", project / "app/src/main/java"),
        (lucent_java, project / "app/src/main/java"),
        (prefix / "share/android-port/gradle-wrapper", project),
    )
    for source, destination in sources:
        if not source.is_dir():
            raise SystemExit(f"Android runtime source directory is missing: {source}")
        shutil.copytree(source, destination, dirs_exist_ok=True)


def inspect_apk_runtime(apk: Path, abi: str) -> tuple[str, ...]:
    with zipfile.ZipFile(apk) as archive:
        entries = tuple(archive.namelist())
    if len(entries) != len(set(entries)):
        raise SystemExit(f"APK contains duplicate archive entries: {apk}")
    required = (
        f"lib/{abi}/libmain.so",
        f"lib/{abi}/libSDL3.so",
        f"lib/{abi}/libc++_shared.so",
        "resources.arsc",
    )
    missing = [entry for entry in required if entry not in entries]
    if missing:
        raise SystemExit("APK is missing runtime artifacts: " + ", ".join(missing))
    return entries
