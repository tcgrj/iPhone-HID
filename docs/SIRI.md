# Siri 快捷指令

先确认网页能控制手机。Siri 只是任务入口，不代替 AirPlay 与蓝牙连接。此功能使用明文 HTTP + Bearer 认证，仅限可信内网，不开放公网。

## 添加共享模板

安装完成后，在 iPhone 上打开：

- [添加「科技阁助手·公开版」](https://www.icloud.com/shortcuts/6054b353340c4b658ddc024f15d1d8ca)
- [添加「帮我点外卖·公开版」](https://www.icloud.com/shortcuts/4d77ebdadf1c495585c786b6056fc3fa)

公开模板不含私人配置。首次添加时按提示填写以下两项，配置一次即可：

- **服务地址**：本机服务的完整 URL，例如 `http://你的Mac局域网IPv4:8769/task`，末尾保留 `/task`。
- **连接密钥**：本机生成的 token 原文，**不要加 `Bearer`**；模板会自动添加认证前缀。

添加后可改名为「科技阁助手」「帮我点外卖」，方便用 Siri 呼叫。已有个人版不用改。填好配置后的版本仅供自己使用，不要再公开分享。

先手动运行刚添加的助手快捷指令，按系统提示允许访问局域网，输入“连接测试”。确认服务有响应并改名为「科技阁助手」后，就可以说“嘿 Siri，科技阁助手”并交代任务，或在任务输入时说“停止任务”。使用时 Mac 服务必须运行，iPhone 保持解锁、蓝牙与投屏已连接。Siri 不能替你重新开启断开的屏幕镜像。

「帮我点外卖·公开版」用于选餐和加购，要求进入结算后停止，由你确认，不自动下单或付款。提示词不是强制安全隔离，使用时仍需看着手机。

以下步骤供手动配置或排障使用。

## 1. 手动启动入口

查找 **Mac 当前局域网 IPv4**，不要填写开发板 IP、127.0.0.1 或其他人的地址。将下面的占位符替换后启动控制台：

```sh
.venv/bin/python -m wireless.console.server --siri-host YOUR_MAC_LAN_IP
```

本机网页仍监听 127.0.0.1:8766，Siri 网关绑定指定 IPv4 的 8769。首次启动会在 `wireless/.runtime/siri.json` 生成自己的随机密钥，权限 0600。不要发到聊天、GitHub 或截图里。

## 2. 在本机生成个人版本（可选）

如果不使用共享模板，也可以在自己的 Mac 上生成已填好配置的个人版本。另开终端，在仓库根目录运行，填入与启动参数相同的 Mac IPv4：

```sh
.venv/bin/python wireless/shortcuts/build.py YOUR_MAC_LAN_IP
```

输出为 `wireless/.runtime/科技阁助手.unsigned.shortcut`。在支持 `shortcuts sign` 的 macOS 中签名后导入自己的快捷指令 App：

```sh
shortcuts sign --mode people-who-know-me \
  --input 'wireless/.runtime/科技阁助手.unsigned.shortcut' \
  --output 'wireless/.runtime/科技阁助手.shortcut'
open 'wireless/.runtime/科技阁助手.shortcut'
```

签名与导入可能要求登录 Apple 账号或本人确认，请按系统提示完成，不要交出 Apple 密码。签名服务、iCloud 同步和快捷指令动作兼容性取决于系统版本。**生成文件内含控制密钥，只有你自己的设备应持有；不要公开分享已生成版本。** 不需要签名文件时，也可以在快捷指令 App 手动按下面流程创建。

动作顺序：询问输入 → 获取 URL 内容（POST）→ 读取返回字典的 message → 关闭 Siri 并继续 → 前往主屏幕。URL 为 `http://你的MacIPv4:8769/task`，JSON 请求体为 `{"task": "询问的结果"}`，Authorization 请求头在本机读取你的 `siri.json` 形成 `Bearer 密钥`。不要把密钥写入文档或共享模板。

## 3. 手机验证与维护

等待个人 iCloud 同步，或通过你自己的设备间传输导入。先在 iPhone 手动运行一次，允许快捷指令访问你指定的局域网服务，然后用 Siri 说“科技阁助手”，回答“连接测试”。应收到服务响应，且网页未产生手机操作。

再尝试无风险任务。说“停止任务”可取消当前任务和待执行队列。Siri 收起后才应观察手机，仍可能需要你手动收起；“关闭 Siri”与“前往主屏幕”并非所有 macOS/iOS 版本都支持。若无法找到动作，请删去这两个动作，手动收起 Siri，**不要把兼容性问题误认为可以自动重连屏幕镜像**。

可选外卖模板：

```sh
.venv/bin/python wireless/shortcuts/build.py YOUR_MAC_LAN_IP --takeaway
```

它生成“帮我点外卖”，提示想吃什么，约束加购和进入结算后停止，不下单、不付款。提示词不是强制安全隔离，务必全程监督；初次不建议用真实购物任务验收。

Mac IP 变化时，更新启动参数，并修改公开模板的第一条“文本”为新的完整 URL；个人生成版则重新生成/导入。不要重复运行旧地址版本。泄露 token 时先停止网关，在本机移走旧 `siri.json`，重新启动生成新密钥，并替换所有个人快捷指令；旧快捷指令会失效。
