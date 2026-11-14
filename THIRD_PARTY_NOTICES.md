# 第三方来源、修改与许可证

项目整理与原创代码：**科技阁**，Copyright (c) 2026 科技阁，GPL-3.0-or-later。根目录 LICENSE 是 GPL-3.0 正文；“or later”由本声明指定。各第三方文件原有许可与署名优先，第三方文件不因放在本仓库中改变许可证。

## 设计参考与补丁依赖

### UxPlay

- 来源：<https://github.com/FDH2/UxPlay>
- 固定版本：1.73.6，commit `21eef8df25d91e12635c36d8176ad192725baca2`。
- 本仓库只分发 `patches/uxplay-mirror-resume.patch`，不重复打包上游源码。安装器从上述官方仓库下载固定 commit 到 `wireless/vendor/UxPlay`，保留全部上游文件头和许可。
- 总体许可：GPL-3.0-or-later；下载源码内保留 `LICENSE`。内部部分文件为 LGPL-2.1-or-later 或 MIT，按文件头与附带许可处理；补充 LGPL-2.1 完整文本在 `docs/licenses/LGPL-2.1.txt`。
- 本项目修改：`lib/raop_rtp_mirror.c` 在已验证的视频数据到来时恢复暂停的渲染器，兼容未先收到预期 codec 通知的情况。2026-11-14 发布整理时加注修改标识，保留 dsafa22、fduncanh 原有声明。
- 作者与来源链：antimof；F. Duncanh / FDH2 及贡献者；[RPiPlay](https://github.com/FD-/RPiPlay) 的 Florian Draschbacher / FD-；AirplayServer 的 dsafa22；[ShairPlay](https://github.com/juhovh/shairplay) 的 Juho Vähä-Herttua；[PlayFair](https://github.com/EstebanKubata/playfair) 的 EstebanKubata；[llhttp](https://github.com/nodejs/llhttp) 的 Fedor Indutny。
- 保留 `lib/playfair/LICENSE.md`、`lib/llhttp/LICENSE-MIT` 及所有文件头。本次只发布本项目源码与补丁，不发布依赖二进制；如以后发布二进制，需同时履行对应源码与所链接依赖的分发义务。

### ESP32 iPhone Agent（设计参考）

- 来源：<https://github.com/onehumanbeing/esp32-iphone-agent>
- 作者：**Henry Yuan**；MIT。
- 参考 commit：`39aa23e17de957bc01529fbd8f22f4deef0e08ca`。
- 参考范围：常驻模型客户端、压缩图像、动作后统一观察、短动作历史。没有直接打包其 USB 固件或 Jev 服务。本项目是 Wi-Fi 指令 + BLE HID + Mac AirPlay 实现，不是官方分支。
- 原始许可见 `wireless/docs/esp32-iphone-agent-LICENSE.txt`；README 中保留可见署名。

## 构建时下载或用户自行安装的依赖

这些依赖不随本仓库以二进制分发。具体第三方条款以下载版本内的 LICENSE / NOTICE 为准。

- Arduino-ESP32 **3.3.7**：Espressif Systems 及贡献者，LGPL-2.1，另含 ESP-IDF 和第三方组件各自许可。<https://github.com/espressif/arduino-esp32>
- NimBLE-Arduino **2.5.2**：h2zero / Ryan Powell 及贡献者，Apache-2.0；其底层 NimBLE 保留 Apache 项目声明。<https://github.com/h2zero/NimBLE-Arduino>
- Codex CLI：OpenAI 及贡献者，Apache-2.0。<https://github.com/openai/codex>
- GStreamer：GStreamer 团队及各插件作者，核心 LGPL-2.1-or-later，插件/底层库以各自许可为准。<https://gstreamer.freedesktop.org/>
- pySerial **3.5**：Chris Liechti 及贡献者，BSD-3-Clause。<https://github.com/pyserial/pyserial>
- Pillow **11.3.0**：Alex Clark 及贡献者，源自 Fredrik Lundh / Secret Labs AB 的 Python Imaging Library，HPND/PIL 许可及组件许可。<https://github.com/python-pillow/Pillow>
- OpenSSL、libplist、CMake、pkgconf、Python、Apple Swift/Vision 和 Arduino CLI 是构建或运行工具，按各自发行版条款安装；它们的产品名称不代表对本项目的认可。

## 不随本发布版分发的实验内容

开发阶段研究过 inclusionAI / Venus Team 的 UI-Venus，来源 <https://github.com/inclusionAI/UI-Venus>。审阅的分支 commit 为 `6d5f8baf3d28868b3e32fefa9da501e99964a8c5`；该树未发现 LICENSE/NOTICE，README 仅有研究和教育用途说明，因此未据此推定可按 GPL/MIT 再分发。

本公开包排除了原实验目录中复制的三个 UI-Venus Python 文件、参考提示词、模型权重、Venus 执行器、本地模型和混合规划工具。此处仅保留研究来源与作者署名，不授权重新加入未明确许可的内容。
