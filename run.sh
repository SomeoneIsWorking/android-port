#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec uv run --frozen python "$ROOT/tools/android_port.py" emulator-status
