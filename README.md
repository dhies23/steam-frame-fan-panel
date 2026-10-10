# Steam Frame 快速设置菜单「风扇」页

在 Steam Frame（SteamOS + SteamVR GamepadUI）的**快速设置菜单（QAM）**底部标签栏里，
紧挨着「?」帮助气泡右边新增一个风扇图标；点开后是风扇转速控制与实时温度面板。

> **直接下载**：到 [Releases](https://github.com/dhies23/steam-frame-fan-panel/releases/latest)
> 取 `sf-fan-qam-1.0.0.tar.gz`，解压后 `sudo ./install.sh`。详细步骤见
> [`sf-fan-qam/README.md`](sf-fan-qam/README.md)。

```
    🔔   ⚙   ⚡   🔋   ❓   ✿
                          ↑ 新增的风扇标签
```

![面板](shots/qam_fan.png)

面板包含：

| 行 | 内容 |
| --- | --- |
| 风扇转速 | 拖动滑杆 = 手动设置 PWM（20 %–100 %） |
| 自动温控 | 开关：交回系统自动曲线 / 手动接管 |
| 实时转速 | 实时 RPM |
| 当前占空比 | 实时 PWM 百分比 |
| 温度 | 核心 SoC / CPU / GPU / 内存 / 散热片 / 风扇口，六个传感器实时值 |

外观不是自己写的 CSS：面板里每一行都是从当前显示的原生 QAM 标签页里**克隆**出来的
节点，所以字号、间距、圆角、焦点高亮跟系统菜单完全一致，而且 Valve 更换哈希类名后
依然有效。

---

## 安装

需要一台 Steam Frame 开发机、能开终端、有 sudo 密码。

直接用仓库里的文件装也行（推荐给测试者用 `release/` 里的发行包，见下）：

```bash
git clone https://github.com/dhies23/steam-frame-fan-panel.git
cd steam-frame-fan-panel/sf-fan-qam
sudo ./install.sh
```

`install.sh` 会先确认这台机器确实是 Steam Frame（找风扇 hwmon、原生温控服务、
CEF 调试端口），不满足就**明确拒绝安装**，不会把系统留在半装状态。装完会等最多
15 秒确认真的注入进了 QAM 页面，并打印注入的 build 哈希。

装好后戴上头显，点底栏的**电池图标**打开 QAM，在「?」右边就能看到风扇标签。

> 如果装的时候 SteamVR 没开，脚本会提示「还没注入成功」——这是正常的，
> 启动 SteamVR 之后几秒它会自动接上，**不需要重装**。

## 卸载

```bash
cd steam-frame-fan-panel/sf-fan-qam
sudo ./uninstall.sh
```

会停服务、把风扇交回系统自动温控、删掉所有装上去的文件，然后**验证**原生控制器
确实回来了（打印 `pwm1` 和转速）。卸载后系统跟没装过一样。

## 出问题

```bash
sudo ./diagnose.sh > sf-fan.log 2>&1
```

只读，不改任何东西。检查九个板块：系统、风扇硬件、原生温控、面板服务、
SteamVR/GamepadUI、CEF 调试端口（列出所有 target 并标出哪个是 QAM）、文件、
最近日志、内核风扇消息，最后给结论。把 `sf-fan.log` 发出来即可。

**看不到风扇标签**
1. 确认 QAM 是从**电池图标**打开的（不是底部大栏）；
2. `journalctl -u sf-fan-qamd.service -n 20` 看有没有 `inject -> xxxx`；
3. 没有的话多半是 SteamVR 没起来，或者装完没重启过 SteamVR。

**「实时转速」大概三秒才跳一次**
这是**硬件**的节奏，不是面板慢。实测面板从拿到数据到画到屏幕上是 0.6 秒以内，
但风扇控制器本身大约每 3 秒才产出一个新读数（内核测速窗口的限制，`dmesg` 里能看到
`tach did not complete in expected period`）。界面上已经是最新的了。

**手动调了转速，过一会儿自己变回自动**
这是保护机制。三种情况会交回系统：SoC ≥ 88 °C、你打开了「自动温控」开关、
服务被停或崩了（单元里的 `ExecStopPost` 兜底）。

## 安全说明

- **手动模式最低 20 %，永远不会写出 0。** 这颗 Delta 风扇在 20 % 以下会失速，
  原生控制器的下限也是 30 %，所以滑杆拖到最左也只会到 20 %。
- **不影响原生温控。** 手动模式只是临时停下原生控制器并接管 `pwm1`；一旦切回自动、
  温度过高、或服务退出，原生控制器立刻拿回控制权。
- **卸载后完全恢复原状**，没有改任何系统文件（只往 `/home/steamos/sf-fan-qam/`
  放文件、往 `/etc/systemd/system/` 放一个单元）。
- 只用 Python 标准库，不联网，不装任何额外依赖。

## 组成

| 文件 | 作用 |
| --- | --- |
| `sf-fan-qam/install.sh` | 一键安装 |
| `sf-fan-qam/uninstall.sh` | 一键卸载 |
| `sf-fan-qam/diagnose.sh` | 一键诊断 |
| `sf-fan-qam/README.md` | 给测试者的安装 / 卸载 / 排错说明 |
| `sf-fan-qam/device/sf_fan_qam.js` | 注入到 QAM 页面的前端脚本 |
| `sf-fan-qam/device/sf_fan_qamd.py` | root 守护进程：读传感器、写 `pwm1`、通过 CDP 注入前端 |
| `sf-fan-qam/device/sf-fan-qamd.service` | systemd 单元 |
| `sf-fan-qam/device/技术说明.md` | 技术文档：原理、调试工具、踩过的坑 |
| `tools/` | 开发期的验证脚本（CDP 驱动界面，不用戴头显） |
| `tools/make_release.py` | 打包发新版 |

装到设备上的位置：

```
/home/steamos/sf-fan-qam/                 程序本体
/etc/systemd/system/sf-fan-qamd.service   服务单元
```

## 开发

`tools/` 下的脚本通过 CDP 直接驱动界面来验证，不需要戴头显。它们需要一个
`~/.ssh/config` 里的 `frame` 主机别名（用户名 `steamos`），并且把设备的 CEF
调试端口转发到本地：

```bash
ssh -N -L 8081:127.0.0.1:8081 frame &     # 或者直接设 SF_CDP=<设备IP>:8081
```

依赖：Python 3、`websocket-client`。

```bash
python tools/sf_verify.py              # 完整验收（20 项）
python tools/sf_test_regress.py        # 已报故障的回归（18 项）
python tools/sf_test_toggle_visual.py  # 开关外观是否真的切换（6 项）
python tools/sf_compare_style.py       # 与原生菜单逐项对比（9 项）
python tools/sf_refresh.py             # 抓最新 DOM
python tools/build_preview.py          # 生成离线预览 HTML，不用头显也能看
python tools/make_release.py           # 打出 release/ 下的发行包
python tools/publish_release.py        # 把发行包作为 GitHub Release 附件上传
```

Windows 上跑设备端脚本用 `sf.ps1`（会处理 CRLF 问题）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File sf.ps1 script.sh
```

改完代码打包发新版：

```bash
python tools/make_release.py
```

会在 `release/` 下生成 `sf-fan-qam-<版本>.tar.gz`、`.zip` 和 `SHA256SUMS`。
打包脚本会强制把 `install.sh` / `uninstall.sh` / `diagnose.sh` 写成 `755`——
Windows 文件系统没有执行位，直接用 `tar` 或 `Compress-Archive` 打出来的包
解压后跑不了。

## 许可

GPL-3.0，见 [LICENSE](LICENSE)。
