# iPhone-HID

**作者：科技阁**

用一块 ESP32-S3，把 AI 的操作指令变成 iPhone 能识别的蓝牙键盘和鼠标输入。电脑通过 AirPlay 接收手机画面，再由 Codex 判断下一步该点哪里。

这是视频演示项目的整理开源版，提供固件源码、Mac 控制台、中文安装说明和 Siri 快捷指令生成器。可以把整个仓库交给 Codex，让它按本文检查环境、安装依赖和启动。首次仍需要你连接开发板、确认刷机、配对蓝牙、开启屏幕镜像并登录自己的 Codex 账户，不是下载后免配置运行。

**重要：AirPlay 接收器运行在 Mac 上，不在 ESP32-S3 上。** 手机使用时无需连电脑数据线，但开发板仍须供电，Mac 须开机并运行服务。项目不越狱、不安装 iPhone 控制 App，也不使用摄像头。它仍会读取画面：Codex 模式会将当前画面和任务发送到你登录的模型服务，不能理解为“无图像传输”或“纯离线”。

## 能做什么

- 在本机网页查看 iPhone 投屏，执行移动、点击、滑动和有限的键盘输入。
- 用自然语言给出任务，按“观察画面 → 操作 → 确认新画面”的顺序执行。
- 可选用 Siri 快捷指令提交任务、测试连接或停止任务。
- 断流、模型错误、指针定位失败时停止，不自动重复可能已执行的点击。

目前公开的是 **Mac + Codex 的稳定开发路线**。本地小模型、UI-Venus 和混合规划属于未完成的实验，不打包进此版本。功能仍是原型，不能保证任意 App、任意任务都成功，也不保证不会触发第三方平台的自动化限制。

## 硬件与软件

- 一块支持 **Wi-Fi 2.4 GHz 和 BLE 的 ESP32-S3 开发板**。无需摄像头。视频原板为 16 MB Flash、OPI PSRAM 配置；不同板型必须核实 Flash/PSRAM 设置，不能直接照抄。
- 一台 Mac。当前验证平台为 Apple Silicon macOS；Windows/Linux 尚未完整验证。
- 一部支持 AirPlay 屏幕镜像和辅助触控指针设备的 iPhone。保持解锁，打开辅助触控。
- 同一可信局域网，不能开 AP/客户端隔离；开发板连接 2.4 GHz Wi-Fi。
- Homebrew、Xcode Command Line Tools，以及已登录且可使用视觉模型的 Codex CLI。模型服务额度/费用由自己的账户承担。

## 先让 Codex 接手

下载本仓库后，在 Codex 中打开该目录，发送：

> 请先读取 README.md 和 AGENTS.md，检查这台 Mac 的环境，按文档部署 iPhone-HID。先执行不触碰手机的依赖检查、构建和测试。需要刷机时让我确认具体串口和板型；需要配对、投屏、登录时告诉我操作步骤。不要读取或上传我的密钥，不要下单、付款、发送消息，也不要擅自启用开机常驻服务。

也可以手动操作：

```sh
git clone https://github.com/tcgrj/iPhone-HID.git
cd iPhone-HID
```

没有 Git 可以在 GitHub 点击 **Code → Download ZIP**，解压后进入目录。后续命令都在仓库根目录执行。

## 1. 安装 Mac 依赖

先安装 [Homebrew](https://brew.sh/) 和 [Xcode Command Line Tools](https://developer.apple.com/xcode/resources/)。按 [Codex 官方说明](https://github.com/openai/codex) 安装并登录 CLI，确认终端能执行 `codex --version`。本项目不自带账号，不读取或复制你的认证文件。

```sh
bash scripts/setup-macos.sh --install-deps
```

脚本创建仓库内 `.venv`，安装固定 Python 依赖，下载固定版本 UxPlay 源码并应用仓库内补丁，编译 macOS OCR 与 UxPlay。首次下载需要联网，不会刷开发板、配网、启动常驻服务或操作手机。安装详情、可选参数和板型见 [安装说明](docs/SETUP.md)。

```sh
.venv/bin/python scripts/doctor.py
.venv/bin/python -m unittest discover -s wireless/tests -v
```

如果 Codex 只有桌面应用内置版本、终端找不到命令，按 doctor 提示设置 `CODEX_BIN` 或 PATH。不要把别人的模型名直接复制到自己的账号。默认使用自己的 Codex 默认模型；需要时可在 `wireless/.runtime/planner.json` 填写自己可用的视觉模型，模板在 `config/planner.example.json`。

## 2. 编译与刷入 ESP32-S3

```sh
bash scripts/build-firmware.sh --install-deps
```

构建流程见 [安装说明](docs/SETUP.md)。脚本不自动刷机。先核对板子的型号、Flash 大小、USB 接口和串口，再按文档上传。**刷机会替换当前固件；已有配网和蓝牙绑定也可能受影响。不要对不确定的设备执行上传或清空 Flash。**

首次配网用能传数据的 USB 线连接 Mac 和开发板。之后 USB 可以只接电源，ESP32 与 Mac 通过 Wi-Fi 通信，与 iPhone 通过 BLE 通信。不要把开发板接到 iPhone USB 口。

## 3. 启动并连接手机

分别开两个终端：

```sh
# 终端一：AirPlay 接收端
.venv/bin/python wireless/tools/run_receiver.py

# 终端二：网页控制台
.venv/bin/python -m wireless.console.server
```

1. 打开 <http://127.0.0.1:8766/>，通过网页为开发板配置 2.4 GHz Wi-Fi。密码只用于通过 USB 配网，保存到开发板 NVS，不写入仓库。
2. 在 iPhone「设置 → 辅助功能 → 触控 → 辅助触控」开启辅助触控，在设备设置中配对 **TechGe Wireless iPhone**。具体菜单随 iOS 版本略有不同。
3. iPhone 控制中心 → 屏幕镜像 → **TechGe iPhone Screen**。首次连接输入接收端终端显示的随机验证码。
4. 网页应显示实时画面、蓝牙已连接。先试方向键和无风险点击，再提交“读取屏幕文字”等只读任务。
5. 运行时盯住手机。遇到异常点网页「停止」。停止不会撤销已经执行的操作。

默认网页只监听本机 127.0.0.1，不要改为公网监听。不要同时启动两份接收端/控制台。更换网络或设备 IP 后，连接 USB，在网页重新读取连接信息。

## 4. Siri 快捷指令（可选）

先跑通网页，再看 [Siri 配置](docs/SIRI.md)。每个人在本机生成自己的认证密钥和快捷指令，仓库不会提供作者已配好的快捷指令文件。

可用语音任务包括“连接测试”“停止任务”。任务实际执行仍要求 Mac 服务运行、手机已解锁、蓝牙与 AirPlay 均连接。Siri 无法代替你重新选择已断开的屏幕镜像。

## 安全、隐私与限制

- **默认会向 Codex 发送画面。** 请先关闭私密聊天、密码、银行卡等页面。不要在手机上展示不应交给模型服务的内容。
- Mac 网页、Siri 与开发板令牌均属于本地私人配置。`.runtime/`、`.console-runtime/`、日志、配对信息及生成的 `.shortcut` 已加入忽略列表，不能上传分享。
- Wi-Fi 输入和可选 Siri 接口没有 TLS，仅适合可信内网，不能做路由器公网转发。Bearer token 不能替代网络加密。
- 系统提示限制付款、订单提交、删除、发消息、凭据和安全修改，但**提示词不是不可绕过的安全边界**。不要让此原型无人看管地操作敏感页面。
- HID 文本输入仅支持可打印 ASCII；中文搜索可用拼音，再选择可见候选。复杂手势、拖动、iOS 悬停变形及部分受保护内容可能失败。
- 30 fps 预览不等于 30 次/秒决策。云模型延迟可能达到数十秒；视频经过剪辑，不能当作持续执行速度。
- 本机 OCR 和指针检测会用内存处理图像。默认 app-server 路线不保存截图文件；可选旧 exec 路线会使用完成后清理的临时图片。模型服务自身的数据处理遵循你的账户设置与服务政策。
- 默认不启用保活、登录自启或本地模型。常驻服务属于可选部署，请阅读文档后自行决定。

更多问题见 [排障与验证记录](docs/VALIDATION.md)。

## 项目结构

```text
wireless/firmware/    ESP32-S3 固件源码
wireless/console/     网页控制台、AirPlay 帧接收、模型协议与动作验证
wireless/shortcuts/   本机 Siri 快捷指令生成器
patches/             固定版本 UxPlay 的镜像恢复补丁
wireless/tests/      不连接真实手机的自动化测试
scripts/             安装、固件构建与环境检查
config/              无密钥的示例配置
docs/                安装、Siri、验证与第三方许可说明
```

## 开源许可

本项目原创代码由 **科技阁** 整理和维护，以 **GPL-3.0-or-later** 发布，见 [LICENSE](LICENSE)。第三方文件保留各自的版权和许可，不能把整个仓库重新标成单一 MIT 项目。详细来源、固定版本和修改记录见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 引用、致谢与作者署名

- [ESP32 iPhone Agent](https://github.com/onehumanbeing/esp32-iphone-agent)，作者 **Henry Yuan**，MIT。参考其常驻模型客户端、图像压缩、动作后观察和短动作历史设计。本项目采用独立的 Wi-Fi 指令、BLE HID 与 Mac AirPlay 架构，不是其 USB 固件或官方分支。已保留 [MIT 许可原文](wireless/docs/esp32-iphone-agent-LICENSE.txt)。
- [UxPlay](https://github.com/FDH2/UxPlay)，由 **antimof、F. Duncanh / FDH2 及贡献者**开发维护，GPL-3.0-or-later。用于 Mac AirPlay 接收。安装器按固定 commit 下载其完整源码和许可，并应用仓库内的一处镜像恢复补丁。
- UxPlay 继承与集成的项目包括 **Florian Draschbacher / FD- 的 RPiPlay、dsafa22 的 AirplayServer、Juho Vähä-Herttua 的 ShairPlay、EstebanKubata 的 PlayFair、Fedor Indutny 的 llhttp**。下载后的各文件保留原署名和许可证。
- [NimBLE-Arduino](https://github.com/h2zero/NimBLE-Arduino)，**h2zero / Ryan Powell 及贡献者**，Apache-2.0；[Arduino-ESP32](https://github.com/espressif/arduino-esp32)，**Espressif Systems 及贡献者**，LGPL-2.1 及其第三方组件许可。用于固件蓝牙、Wi-Fi 与板级支持，按构建脚本下载，不随仓库分发预编译固件。
- [Codex](https://github.com/openai/codex)，**OpenAI 及贡献者**，Apache-2.0；[GStreamer](https://gstreamer.freedesktop.org/)，**GStreamer 开发团队与插件作者**；[Pillow](https://github.com/python-pillow/Pillow)，**Alex Clark 及 Pillow 贡献者，源自 Fredrik Lundh / Secret Labs 的 PIL**；[pySerial](https://github.com/pyserial/pyserial)，**Chris Liechti 及贡献者**。这些是运行或构建依赖，使用时保留各自许可。
- 开发阶段研究过 [UI-Venus](https://github.com/inclusionAI/UI-Venus)，作者 **inclusionAI / Venus Team**。本次公开包不包含其参考代码、提示词、模型权重或本地执行器；不能因列入致谢就推断这些内容可按本项目许可证重新分发。
