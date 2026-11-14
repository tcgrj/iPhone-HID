# Rebuilding on macOS

These scripts never pair an iPhone, send HID commands, invoke a model, upload firmware, or activate launch agents. Run them from a permanent checkout location; a virtual environment must be recreated after moving the checkout.

## Prerequisites and desktop build

Install Xcode Command Line Tools (`xcode-select --install`) and Homebrew from https://brew.sh. Then:

```sh
# Explicitly installs official Homebrew packages and pinned PyPI dependencies.
./scripts/setup-macos.sh --install-deps
# Or, when Homebrew dependencies are already installed:
./scripts/setup-macos.sh
.venv/bin/python scripts/doctor.py
```

Homebrew packages: `python@3.12 cmake pkgconf gstreamer libplist openssl@3`. Homebrew versions are not locked because formula availability changes; Python dependencies are pinned in `requirements.txt`. UxPlay source is fetched from the official repository at pinned commit 21eef8df25d91e12635c36d8176ad192725baca2, then the included mirror-resume patch is applied. CMake builds with portable CPU options. Outputs are `.venv`, `.console-runtime/ocr`, and `wireless/.runtime/uxplay-build/uxplay`.

`PYTHON=/absolute/path/to/python3.12` overrides Python. Avoid Python 3.15 with Pillow 11.3.0. `CODEX_BIN=/absolute/path/to/codex` overrides discovery. Doctor checks PATH and the official ChatGPT/Codex app bundles, without reading credentials. It checks local CLI version only, not login state. For a foreground console launched from Terminal, add the directory containing the discovered Codex executable to PATH first. Generated launchd plists handle this automatically.

GStreamer inspection can refresh the local registry cache. No global plugins are modified. The verified Homebrew install passes the required plugin checks without a workaround. If discovery fails, repair/reinstall the GStreamer package before starting the receiver; do not remove or modify system plugins blindly.

## Firmware (compile only)

```sh
brew install arduino-cli
./scripts/build-firmware.sh --install-deps
# Explicit alternative matching the original development board:
./scripts/build-firmware.sh --original-16mb-opi
```

The script downloads ESP32 core **3.3.7** from Espressif's official board index and **NimBLE-Arduino 2.5.2** from the Arduino library registry. All Arduino data, downloads, libraries, and build products default to `.build/`; no normal Arduino installation is changed. `ARDUINO_CLI` can select a CLI executable. `ARDUINO_DIRECTORIES_DATA`, `ARDUINO_DIRECTORIES_DOWNLOADS`, and `ARDUINO_DIRECTORIES_USER` can select dedicated alternative directories; do not point them at a shared Arduino installation with a different ESP32 core.

The original build metadata records:

```
esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB,FlashMode=dio,USBMode=hwcdc,CDCOnBoot=cdc,UploadSpeed=921600
```

The baseline instead selects 8MB flash, disabled PSRAM and `default_8MB`. The firmware does not use a camera or require PSRAM. This is a proposed portable build target, not a claim that every ESP32-S3 board has been tested. **Neither the new baseline nor the new library pin has been compile-verified in this release preparation**, because the previous temporary Arduino installation had already lost its core metadata and library files. The historical NimBLE version is unknown; 2.5.2 is an explicit new-install pin from https://github.com/h2zero/NimBLE-Arduino/releases/tag/2.5.2, not a recovered historical version. Confirm the actual board's flash and PSRAM before manually uploading; this script has no upload function.

## Optional launchd files

```sh
.venv/bin/python wireless/tools/install_services.py \
  --generate --output-dir .build/launchagents
# Optional: --siri-host YOUR_MAC_LAN_IP (enables LAN Siri gateway when later launched)
# Optional: --codex-bin /absolute/path/to/codex --service console
```

This only generates plists pointing at the current checkout. It does not copy a venv, copy credentials/pairing files, install plists, run `launchctl`, load/restart services, or contact a phone. It refuses to overwrite existing plists. Review output before manually installing anything. The checkout must remain available at the same absolute path. Siri host is the **Mac's bind address**, not the ESP32 address; omitting it disables the Siri gateway. Generated plist logs remain under `wireless/.runtime/logs`.

## Local build verification (2026-11-14)

- macOS arm64, Python 3.12.13; Swift OCR compilation passed and a local blank JPEG smoke test returned `[]`.
- CMake 4.4.4, GStreamer 1.28.8_1, libplist 2.8.0, OpenSSL 3.5.9, pkgconf 3.0.9; vendored UxPlay reached 100% build success.
- Codex CLI 0.169.0-alpha.11.1 was discovered inside ChatGPT.app and `--version` succeeded.
- `avdec_h264`, `h264parse`, `videoconvert`, `jpegenc`, `multipartmux`, `tcpserversink` checks passed.
- Shell syntax and Python compilation checks passed. Service installer was not run (only `--help`).
- Fresh Python dependency installation initially hit PyPI CDN read timeouts. A retry using the existing local proxy reached package downloads but remained slow; until installation completes, doctor correctly reports missing Pillow/pyserial in the new environment. Re-run setup with normal PyPI network access.
- An official Arduino dependency-install attempt reached the registry-index download, but very low CDN/proxy throughput prevented reaching the compiler during release preparation.
- No hardware upload, service activation, pairing changes, or model calls were performed.
