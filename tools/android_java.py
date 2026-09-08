"""Select one coherent Android Gradle JDK; consumers supply their supported major range."""

import os
import re
import shutil
import subprocess
from pathlib import Path


def java_major(output: str) -> int | None:
    match = re.search(r'(?:version\s+"|javac\s+)(\d+)(?:\.(\d+))?', output)
    if not match:
        return None
    return int(match[2]) if match[1] == "1" and match[2] else int(match[1])


def select_java_home(minimum: int = 17, maximum: int = 26) -> Path:
    configured = os.environ.get("JAVA_HOME")
    candidates = [Path(configured)] if configured else []
    java = shutil.which("java")
    if java:
        candidates.append(Path(java).resolve().parent.parent)
    candidates.extend(
        path.parent.parent for path in Path("/usr/lib/jvm").glob("*/bin/java")
    )
    seen = set()
    for candidate in candidates:
        home = candidate.resolve()
        if home in seen:
            continue
        seen.add(home)
        suffix = ".exe" if os.name == "nt" else ""
        tools = [home / "bin" / (name + suffix) for name in ("java", "javac")]
        if not all(tool.is_file() for tool in tools):
            continue
        versions = []
        for tool in tools:
            result = subprocess.run(
                [str(tool), "-version"], capture_output=True, text=True, check=True
            )
            versions.append(java_major(result.stdout + result.stderr))
        if (
            versions[0] == versions[1]
            and versions[0] is not None
            and minimum <= versions[0] <= maximum
        ):
            return home
    raise SystemExit(
        f"Android Gradle needs matching java/javac majors {minimum} through {maximum}; "
        "select one coherent installed JDK using JAVA_HOME"
    )
