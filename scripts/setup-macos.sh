#!/bin/bash
# Builds local artifacts only. Never starts services, pairs devices, or flashes firmware.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$(uname -s)" == Darwin ]] || { echo 'macOS is required.' >&2; exit 1; }
command -v brew >/dev/null || { echo 'Install Homebrew from https://brew.sh first.' >&2; exit 1; }
xcode-select -p >/dev/null || { echo 'Install Xcode Command Line Tools first: xcode-select --install' >&2; exit 1; }
if [[ "${1:-}" == --install-deps ]]; then
  brew install python@3.12 cmake pkgconf gstreamer libplist openssl@3
elif [[ $# != 0 ]]; then
  echo 'Usage: scripts/setup-macos.sh [--install-deps]' >&2; exit 2
fi
export HOMEBREW_PREFIX="$(brew --prefix)"
PYTHON="${PYTHON:-$HOMEBREW_PREFIX/opt/python@3.12/bin/python3.12}"
for tool in "$PYTHON" cmake pkg-config swiftc gst-inspect-1.0; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Run scripts/setup-macos.sh --install-deps" >&2; exit 1; }
done
export PKG_CONFIG_PATH="$HOMEBREW_PREFIX/opt/openssl@3/lib/pkgconfig:$HOMEBREW_PREFIX/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
pkg-config --exists gstreamer-1.0 gstreamer-video-1.0 gstreamer-app-1.0 gstreamer-sdp-1.0 libplist-2.0 openssl
"$PYTHON" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --disable-pip-version-check --index-url https://pypi.org/simple --timeout 20 --retries 2 -r "$ROOT/scripts/requirements.txt"
mkdir -p "$ROOT/.console-runtime" "$ROOT/wireless/.runtime"
swiftc -O "$ROOT/wireless/console/ocr.swift" -o "$ROOT/.console-runtime/ocr"
bash "$ROOT/scripts/fetch-uxplay.sh"
cmake -S "$ROOT/wireless/vendor/UxPlay" -B "$ROOT/wireless/.runtime/uxplay-build" \
  -DCMAKE_BUILD_TYPE=Release -DNO_MARCH_NATIVE=ON -DNO_X11_DEPS=ON \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build "$ROOT/wireless/.runtime/uxplay-build" --parallel "$(sysctl -n hw.ncpu)"
echo 'Built Python environment, OCR and UxPlay. Run .venv/bin/python scripts/doctor.py next.'
