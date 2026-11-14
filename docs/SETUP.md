# 安装与板型说明

首次需要联网安装依赖。源码不含硬件、账号、模型额度、Wi-Fi 密码或预配置密钥。不要把“源码完整”理解为“无需配置”。

## Mac

先安装 Homebrew 与 Xcode Command Line Tools，再在仓库根目录运行：

```sh
bash scripts/setup-macos.sh --install-deps
.venv/bin/python scripts/doctor.py
.venv/bin/python -m unittest discover -s wireless/tests -v
```

脚本使用 Homebrew Python 3.12，安装 Pillow 11.3.0 / pySerial 3.5；从官方仓库获取固定 commit 的 UxPlay 1.73.6，应用 patches/uxplay-mirror-resume.patch，再构建 UxPlay 与 Swift Vision OCR。Homebrew 的系统库会随官方 formula 更新，未声称整个系统依赖逐字节可复现。只创建项目内的环境与构建输出，不刷机，不启动控制服务。

依赖已齐全时可省略 `--install-deps`；仍会按固定版本安装 Python 包。可以设置 `PYTHON=/完整路径/python3.12`。不要使用 Python 3.15 配旧版 Pillow。

若下载超时，先确认能正常访问 Homebrew、PyPI、GitHub、Arduino 和 Espressif 官方下载站，再重试原命令。不要从不明网盘下载代替的可执行文件。脚本遵循终端现有的网络代理环境，不修改系统网络或安全设置。

## Codex

使用自己的 Codex CLI 与账号。`codex --version` 应可执行，先在终端完成官方登录。控制台不安装、复制或读取认证文件。

doctor 能查找 PATH 或官方桌面 App 内置的 CLI，但仅检查程序版本，不等于账号已登录、模型有权限或套餐有额度。若终端找不到，可按 doctor 输出将 CLI 所在目录加入本次终端 PATH，再启动服务：

```sh
export PATH="你的Codex可执行文件所在目录:$PATH"
```

本发布版使用自己的默认模型，不指定作者的内部模型名或付费优先服务档。需要时：

```sh
mkdir -p wireless/.runtime
cp config/planner.example.json wireless/.runtime/planner.json
```

将 `model` 设为你账号中可用、支持图像的模型名，或者保持 `null`。`effort` 的可用值由模型决定；若模型不支持 `low`，按官方模型能力调整。不要上传这个目录。`keep_awake` 默认 false；开启时会保持 Mac 显示并周期轻移手机指针，不是绕过手机锁屏。

本项目依赖 Codex 的实验性 app-server JSONL 协议，验证版本在 VALIDATION.md。协议不兼容时会报错停止，不把识屏模型切换为可执行任意工具的代理。官方协议：<https://github.com/openai/codex/tree/main/codex-rs/app-server>。

## ESP32-S3 构建

```sh
brew install arduino-cli
bash scripts/build-firmware.sh --install-deps
```

脚本把 Arduino 数据、库和下载放在仓库 `.build/` 中，不修改已有 Arduino 环境，固定 Arduino-ESP32 3.3.7 与 NimBLE-Arduino 2.5.2。后者是公开发布版的明确新安装版本，不是从旧临时环境恢复出的历史版本。实际编译结果见 VALIDATION.md。

默认目标为 8 MB Flash、无 PSRAM：

```text
esp32:esp32:esp32s3:FlashSize=8M,PSRAM=disabled,PartitionScheme=default_8MB,FlashMode=dio,USBMode=hwcdc,CDCOnBoot=cdc,UploadSpeed=921600
```

原视频开发板使用 16 MB Flash、OPI PSRAM：

```sh
bash scripts/build-firmware.sh --original-16mb-opi
```

对应目标：

```text
esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB,FlashMode=dio,USBMode=hwcdc,CDCOnBoot=cdc,UploadSpeed=921600
```

代码不需要摄像头或 PSRAM，但不代表任意 ESP32-S3 模块都使用同一配置。Flash 只有 4 MB 的板子需另行调整分区并验证；经典 ESP32、ESP32-C3 等不在本次验证范围。

### 手动刷写

先确认串口和板型，关闭占用串口的工具。下面只展示命令模板，**不要原样执行占位符**：

```sh
export ARDUINO_DIRECTORIES_DATA="$PWD/.build/arduino-data"
export ARDUINO_DIRECTORIES_DOWNLOADS="$PWD/.build/arduino-downloads"
export ARDUINO_DIRECTORIES_USER="$PWD/.build/arduino-user"
arduino-cli board list
# FQBN 替换成上面与你真实开发板相符的完整目标。
# PORT 替换成确认过的串口；PROFILE 为 baseline 或 original。
arduino-cli upload --fqbn 'FQBN' --port 'PORT' \
  --input-dir ".build/firmware-PROFILE" wireless/firmware/wireless_hid
```

刷机会替换原固件。若无法进入下载模式，按板厂说明使用 BOOT/RESET 按键及正确 USB 接口，不要直接擦除整片 Flash。完成后回 README 第 3 节，在网页通过 USB 配网，再由 iPhone 配对蓝牙与投屏。

## 可选常驻部署

默认以前台两个终端启动，便于看见错误。生成 launchd 配置是另一个显式步骤，不会自动启用：

```sh
.venv/bin/python wireless/tools/install_services.py \
  --generate --output-dir .build/launchagents
```

可加入 `--siri-host 你的Mac局域网IPv4`、`--codex-bin /完整路径/codex`。生成的 plist 指向当前仓库和虚拟环境，不会复制私人配置或搬迁 venv。仓库必须放在长期保留的位置，移动后需重新部署。

启用前请让 Codex 检查现有同名 `cn.techge.iphone.*` 服务，确认没有正在执行任务，也没有另一套控制器。不要覆盖现有配置或启动双份服务。需要你明确同意后，才按 macOS launchctl 的正常流程安装/加载。macOS 隐私授权因目录与系统设置不同而异，生成文件不代表后台启动已验证。卸载前同样先停止任务。
