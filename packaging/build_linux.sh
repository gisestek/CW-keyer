#!/usr/bin/env bash
# Build CW Station for Linux (Ubuntu 22.04 or newer, x86-64 or ARM64).
#   bash packaging/build_linux.sh [--skip-tests]
# Result: dist/CWStation-<version>-linux-<arch>.tar.gz  (unpack anywhere, run CWStation/CWStation)
#
# Needs: python3 (3.10+) with venv, curl, and the libraries the program uses at run time:
#   sudo apt install python3-venv libportaudio2 libxcb-cursor0
# Build on the OLDEST Linux you want to support: the result runs on that and newer, not older.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SKIP_TESTS=0
[ "${1:-}" = "--skip-tests" ] && SKIP_TESTS=1
PY="${PYTHON:-python3}"
VENV=".venv-build-linux"       # separate from the Windows .venv-build in the same folder

case "$(uname -m)" in
    x86_64|amd64) ARCH=x64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *) ARCH="$(uname -m)" ;;
esac

if [ ! -f third_party/deepcw-engine/model.onnx ]; then
    echo "Downloading DeepCW model..."
    mkdir -p third_party/deepcw-engine
    for f in model.onnx model.onnx.json LICENSE; do
        curl -fsSL "https://raw.githubusercontent.com/e04/deepcw-engine/main/$f" -o "third_party/deepcw-engine/$f"
    done
fi

if ! ldconfig -p 2>/dev/null | grep -q libportaudio.so.2; then
    echo "WARNING: libportaudio2 is not installed (sudo apt install libportaudio2): audio input will not work." >&2
fi

[ -d "$VENV" ] || "$PY" -m venv "$VENV"
VPY="$ROOT/$VENV/bin/python"
"$VPY" -m pip install --upgrade pip
"$VPY" -m pip install -r requirements-dev.txt

if [ "$SKIP_TESTS" = 0 ]; then
    QT_QPA_PLATFORM=offscreen "$VPY" -m pytest -q tests
fi

"$VPY" -m PyInstaller --noconfirm --clean packaging/cwstation.spec
cp packaging/linux/install-menu-entry.sh dist/CWStation/
chmod +x dist/CWStation/install-menu-entry.sh dist/CWStation/CWStation

echo "Self-test of the built program (about 20 s)..."
RESULT="${XDG_CONFIG_HOME:-$HOME/.config}/CWStation/selftest-result.txt"
rm -f "$RESULT"
if ! QT_QPA_PLATFORM=offscreen dist/CWStation/CWStation --selftest 15; then
    cat "$RESULT" 2>/dev/null || true
    echo "Self-test FAILED" >&2
    exit 1
fi
cat "$RESULT"

VERSION="$("$VPY" -c 'import cwstation; print(cwstation.__version__)')"
OUT="dist/CWStation-$VERSION-linux-$ARCH.tar.gz"
rm -f "$OUT"
tar -C dist -czf "$OUT" CWStation
echo "OK: $OUT"
