"""Compile and exercise the Android framework's platform-free Java contracts."""

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "io.github.someoneisworking.android"
SOURCE = ROOT / "android_port" / "java" / Path(*PACKAGE.split("."))
TESTS = ROOT / "tests" / "java" / Path(*PACKAGE.split("."))
BUILD = ROOT / "build" / "java-tests"
SCENARIOS = ("TouchContacts", "ImportLifetime", "ImportPromotion", "ImportRequest")


def main() -> None:
    classes = BUILD / "classes"
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(parents=True)

    sources = [SOURCE / f"Android{name}.java" for name in SCENARIOS]
    tests = [TESTS / f"Android{name}Test.java" for name in SCENARIOS]
    for path in (*sources, *tests):
        if not path.is_file():
            raise FileNotFoundError(f"Android Java contract source is missing: {path}")

    subprocess.run(
        ["javac", "--release", "17", "-d", str(classes), *(str(path) for path in (*sources, *tests))],
        check=True,
        cwd=ROOT,
    )
    for name in SCENARIOS:
        arguments = [str(BUILD / "promotion")] if name == "ImportPromotion" else []
        subprocess.run(
            ["java", "-cp", str(classes), f"{PACKAGE}.Android{name}Test", *arguments],
            check=True,
            cwd=ROOT,
        )


if __name__ == "__main__":
    main()
