#!/bin/bash
# Compile only. Deliberately has no upload command or serial-port argument.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI="${ARDUINO_CLI:-arduino-cli}"
command -v "$CLI" >/dev/null || { echo 'Install official CLI: brew install arduino-cli' >&2; exit 1; }
export ARDUINO_DIRECTORIES_DATA="${ARDUINO_DIRECTORIES_DATA:-$ROOT/.build/arduino-data}"
export ARDUINO_DIRECTORIES_DOWNLOADS="${ARDUINO_DIRECTORIES_DOWNLOADS:-$ROOT/.build/arduino-downloads}"
export ARDUINO_DIRECTORIES_USER="${ARDUINO_DIRECTORIES_USER:-$ROOT/.build/arduino-user}"
INDEX='https://espressif.github.io/arduino-esp32/package_esp32_index.json'
# Pinned new-install target. The historical installation was pruned; its exact library version is unknown.
NIMBLE_VERSION=2.5.2
PROFILE=baseline
INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --install-deps) INSTALL=1;;
    --original-16mb-opi) PROFILE=original;;
    *) echo 'Usage: scripts/build-firmware.sh [--install-deps] [--original-16mb-opi]' >&2; exit 2;;
  esac
done
mkdir -p "$ARDUINO_DIRECTORIES_DATA" "$ARDUINO_DIRECTORIES_DOWNLOADS" "$ARDUINO_DIRECTORIES_USER"
if [[ "$INSTALL" == 1 ]]; then
  "$CLI" core update-index --additional-urls "$INDEX"
  "$CLI" core install esp32:esp32@3.3.7 --additional-urls "$INDEX"
  "$CLI" lib update-index
  "$CLI" lib install "NimBLE-Arduino@$NIMBLE_VERSION"
fi
CORE="$ARDUINO_DIRECTORIES_DATA/packages/esp32/hardware/esp32/3.3.7"
LIB="$ARDUINO_DIRECTORIES_USER/libraries/NimBLE-Arduino"
[[ -f "$CORE/platform.txt" && -f "$CORE/boards.txt" ]] || { echo 'Missing complete ESP32 3.3.7 core. Run with --install-deps.' >&2; exit 1; }
[[ -f "$LIB/library.properties" ]] && grep -q "^version=$NIMBLE_VERSION$" "$LIB/library.properties" || { echo "Missing NimBLE-Arduino $NIMBLE_VERSION. Run with --install-deps." >&2; exit 1; }
if [[ "$PROFILE" == original ]]; then
  FQBN='esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB,FlashMode=dio,USBMode=hwcdc,CDCOnBoot=cdc,UploadSpeed=921600'
else
  FQBN='esp32:esp32:esp32s3:FlashSize=8M,PSRAM=disabled,PartitionScheme=default_8MB,FlashMode=dio,USBMode=hwcdc,CDCOnBoot=cdc,UploadSpeed=921600'
fi
# Refuse mixed core versions so the installed 3.3.7 is selected unambiguously.
for installed in "$ARDUINO_DIRECTORIES_DATA"/packages/esp32/hardware/esp32/*; do
  [[ "$installed" == "$CORE" ]] || { echo "Multiple ESP32 cores; use a dedicated Arduino data directory." >&2; exit 1; }
done
"$CLI" compile --fqbn "$FQBN" \
  --build-path "$ROOT/.build/firmware-$PROFILE" "$ROOT/wireless/firmware/wireless_hid"
echo "Compiled $PROFILE; no hardware was flashed. Confirm your board's flash/PSRAM before uploading manually."
