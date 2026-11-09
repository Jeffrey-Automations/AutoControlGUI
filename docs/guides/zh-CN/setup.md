# Installation and configuration

[README](../../../README/README_zh-CN.md) · [Documentation](../../README.md)

## 安装

```bash
pip install je_auto_control            # 内核
pip install je_auto_control[gui]       # 加上 PySide6 桌面应用
```

按需安装的可选组件：

| Extra | 启用的功能 |
|---|---|
| `gui` | PySide6 桌面应用（51 个标签页）：左侧可搜索的导航面板（`Ctrl+K`）按分类列出全部功能，标签页在第一次打开时才创建，**View → Theme** 切换深色／浅色。窄窗口的内容可滚动；关闭窗口时，主题、字号、导航面板显示（`Ctrl+B`）与宽度会保存到 `~/.je_auto_control/gui.ini`。主题直接使用 Qt，不需要 `qt-material`。 |
| `webrtc` | WebRTC 远程桌面、USB 直通（`aiortc`、`av`） |
| `signaling` | 独立的信令／rendezvous 服务器（`fastapi`、`uvicorn`） |
| `discovery` | mDNS / Zeroconf 局域网主机发现 |
| `pdf` / `office` | PDF 与 Excel／Word／PowerPoint 读取 |
| `fuzzy` / `locale` | `rapidfuzz` 模糊匹配、`babel` 区域解析 |
| `s3` / `audio` | S3 制品存储、系统音量控制 |

使用标签页关闭按钮关闭 factory 创建的功能面板时，下一次 Qt event loop 会释放 widget、订阅与计时器；重新打开会创建新面板。**View → Tabs** 与嵌入用的 `hide_tab` 只隐藏并保留状态。`tab_registry.open/close` 与 `close_tab` 提供明确的生命周期接口。既有的所有者表单与 Remote Desktop 在生命周期迁移完成前，关闭后仍保留以供重用。

**Windows arm64** 装得起来也跑得起来，少的是上游在那里发不出来的那些：
`opencv-python` 与 `cryptography` 都没发 `win_arm64` wheel。所以 `find_image*`、
`screenshot()`（OpenCV／BGR 那一支——Pillow 截图仍可用）、密钥金库、动作文件加密、
ACME／TLS 与加密录影会抛出指名缺哪个 wheel 的错误，而不是难以追查的失败。
鼠标、键盘、屏幕尺寸、窗口管理、无障碍树、动作执行器、MCP／REST／TCP 服务器
与 GUI 都正常——这是实测的，不是推论的。其他平台不受影响。

**系统需求：** Python ≥ 3.11。
Linux 请先安装构建依赖：

```bash
sudo apt-get install cmake libssl-dev
```

OCR、VLM 与 LLM 后端（`pytesseract`、`easyocr`、`paddleocr`、`anthropic`、`openai`）
都是按需加载——只装你实际会用到的。Tesseract 方面，`find_tesseract_cmd()` 找出可执行文件
（依次是 `$TESSERACT_CMD`、`PATH`、安装程序的默认文件夹），`set_tessdata_dir()` 把它指向
语言数据文件夹，`ocr_status()`／`ocr_languages()` 在第一次 OCR 之前就说出缺了什么。

**日志文件：** 库写到 `~/.je_auto_control/logs/AutoControlGUI.log`，第一条记录时
才创建（只 import 不会写任何文件），同一个账户的所有进程共用（追加写入、每行带进程 ID，
超过 10 MB 就改名为 `.1`）。要写到别处就设置
`JE_AUTOCONTROL_LOG_FILE`，设为 `os.devnull` 则不写文件。

---

## 平台支持

| 平台 | 后端 | 输入 | 屏幕捕获 | 录制 | 窗口管理 |
|---|---|:---:|:---:|:---:|:---:|
| Windows 10 / 11 | Win32 ctypes（可选 Interception 驱动） | ✅ | ✅ | ✅ | ✅ |
| macOS 10.15+ | pyobjc / Quartz | ✅ | ✅ | ✅¹ | ✅ |
| Linux X11 | python-Xlib（可选 `uinput`） | ✅ | ✅ | ✅ | ✅ |
| Linux Wayland | 经桌面 portal 的 libei，或 ydotool／wtype ＋ 截图工具 | ✅ | ✅ | ❌ | ❌ |
| FreeBSD／OpenBSD／NetBSD | python-Xlib，与 Linux 同一套 X11 后端 | ✅² | ⚠️² | ✅² | ✅² |
| Android | adb + uiautomator2 | ✅ | ✅ | — | — |
| iOS | WebDriverAgent / facebook-wda | ✅ | ✅ | — | — |

¹ macOS 的录制走 Quartz event tap，需要**辅助功能**权限
（系统设置 → 隐私与安全性 → 辅助功能）。没有授权时会直接抛出并指名
缺的是哪个权限，而不是安静地录到一个空的 session。

² BSD 直接跑同一套 X11 后端——同一个 X server、同一个 `python-Xlib`，而输入、
录制与窗口管理就只依赖这一个包。`freebsd` CI job 在真的 FreeBSD 14 上驱动真的
输入，再从 X server 读回来；OpenBSD 与 NetBSD 走同一条代码路径，只是没有 CI
runner。唯一的例外是屏幕截取，卡住的是打包而不是平台：它走 Pillow／mss 与
OpenCV，而 `opencv-python`、`pillow`、`cryptography` 都没有发 FreeBSD wheel。
从 ports 构建之后，截取、图像匹配、OCR 与动作加密也都能用——
`import je_auto_control` 本身已经不需要它们任何一个。

Wayland 的按键、按钮与指针输入在 `auto` 模式下，仅在可选原生后端缺失时改用 CLI。
portal 请求开始后，拒绝、超时、握手失败、设备暂停或权限撤销都会停止输入，
不会自动切换提供者；重复调用保留不含原生资源的失败状态，不重开同意对话框。
`JE_AUTOCONTROL_WAYLAND_INPUT_BACKEND=libei` 强制原生输入，`=cli` 明确选择 CLI。
解决权限问题后，可明确调用 `je_auto_control.linux_wayland.libei.reset_default_backend()`
以允许重新请求。原生组合键中断时会在同一后端尝试释放所有已按下的按键，并保留原始取消。
此行为不改变明确的 wtype 文本输入路径或屏幕截取选择。

`ydotool` 退路需要
**ydotool 1.0 以上**。AutoControl 送的每一个参数都是那一版才有的；0.1.x
（Debian bookworm 与目前所有 Ubuntu 仍以这个名字提供，Debian trixie 则根本没有）
对同一批参数返回 0 却不送出任何事件。AutoControl 会检测并直接拒绝，
而不是为根本没送出的输入回报成功。Arch、Fedora 与 Debian unstable 提供的是 1.0。

这条退路要能**准确定位**，还有一个前提:合成器的指针加速度必须是关的。
`ydotool mousemove --absolute` 并不发任何绝对事件——它先把光标推到合成器夹取的
那个角落，再发相对位移，所以这段位移会被合成器加速。对真的 wlroots session 量到的是:
libinput 的默认 profile 让光标走的距离正好是请求的两倍。ydotool 自己的 `--help`
也是这样写的；AutoControl 每个进程会记一次警告，而不是安静地把点击放到错的地方。
请对 ydotoold 的设备关掉加速度（sway:`input type:pointer accel_profile flat`
加上 `pointer_accel 0`），或者装上 `liboeffis`，改走协议层本来就是绝对坐标的 libei。

倍率是合成器自己的设置，客户端读不回来，所以只有你知道它关了没有：
`JE_AUTOCONTROL_WAYLAND_POINTER_ACCEL=flat` 表示已经关掉，移动就不再出声；
`=strict` 则宁可拒绝这次移动，也不让点击落在别的地方；不设置就维持
“警告一次后照样移动”的默认。

Wayland 的屏幕截取需要合成器对应的工具，因为没有单一工具能覆盖全部：wlroots 系
（sway、Hyprland、river）用 `grim`，GNOME 用 `gnome-screenshot`，KDE 用 `spectacle`。
装好其中一个之后，所有截取路径——截图、图像与锚点定位、OCR、屏幕录制、远程桌面——都会
经由它。三个都没装时，内置 D-Bus client 会通过 session bus 尝试 `xdg-desktop-portal`，第一次可能会弹
同意对话框。再不行，截取会带着安装提示明确失败，而不是返回空白的 XWayland root；
`je_auto_control.api.run_diagnostics()`（以及 GUI 的 Diagnostics 标签页）的 `screen_capture`
检查会报告当前使用的是哪一层。

原生 Wayland 指针坐标在原始坐标与布局原点换算后仍不属于任何授权 EIS 区域时，
会以 `state="failed"` 的 `LibeiUnavailable` 拒绝，停止自动 CLI 备用，
不发送移动、frame 或后续点击。有效坐标、未提供区域的设备、同一 sender 的后续有效请求，
以及显式选择 CLI 的现有行为保持不变。

**输入／截取能力**提供 `je_auto_control.api`（也由包根目录导出）的
`BackendContext`、`CapabilityStatus`、`CapabilitySnapshot` 与 `probe_capabilities`。
调用 `probe_capabilities(BackendContext.current()).to_dict()`、无参数的
`AC_probe_capabilities`／只读 `ac_probe_capabilities`，或选择
**Diagnostics → Actions → 查看输入与截取能力**；Builder 提供相同无参数命令。
`python -m examples.capabilities` 显示本机前置条件与确定性的 XWayland 范围示例，不操作桌面。

输入项描述按键／指针事件；现有 wtype 文字路径独立。探测只读环境、PATH 与不等待锁的现有原生状态，
不加载可选原生库、不连接、不读取事件、不截取或请求授权。找到工具或 bus 地址只代表
`unverified`，不等于可用。缓存 libei 须完成握手，且键盘、绝对指针、按钮与滚轮事件种类都在运行才报告可用；
部分授权保持未验证，事件种类暂停或必要设备移除则报告暂停／撤销。八种状态为 `available`、`unverified`、`needs_permission`、
`needs_dependency`、`unsupported`、`paused`、`revoked`、`failed`。
`available` 仅是最近的本机观察，可能过时；实际操作仍重新验证权限。XWayland 一律
`desktop_wide=False`，无法覆盖原生 Wayland 窗口；其他范围标记仍受授权区域限制，不代表已验证每个屏幕。

Context 会复制环境／工具数据，可由拥有者提供无原生对象的输入／截取观察，但不授予权限。
默认本机结果不含环境值、命令参数、可执行文件路径或原生错误文字；AC／MCP 不接受外部提供观察。
显式选择 CLI 与观察到可选原生依赖缺失后的自动备用分开；拒绝、暂停、撤销与失败不表示改走 CLI。
截取工具／portal 选择独立诊断，重绘与切换语言只使用现有快照。原生 portal 恢复、compositor 重启、
截取结果与 context 的接合，以及原生 session 的重试／取消／停止控制仍列于 `Progress.md`。

GUI 工作基础提供 `gui.task_controller.TaskController`：
`submit(work, owner=widget)` 返回调用者持有的 `TaskHandle`，通过
`TaskOutcome`／`TaskProgress` 传递终态与进度。工作取得不依赖 Qt 的
`CancellationToken`，提供 checkpoint、有界且可被取消唤醒的等待与进度报告。
提交时捕获 context，执行前重新读取 store 用户；工作须持有数据、不引用 widget，并验证自身操作所需的 capability。
现有 `DeferredAuthorization.scope()` 保持输入权限要求，`context_scope()` 仅更新并绑定身份。

拥有者、handle 或 controller 销毁时会请求协作式停止并丢弃延迟结果；每项工作有独立 ID／token，
回调在 GUI 线程执行。不强制中断不配合的调用，也不把已成功提交的结果改标为取消。
错误与进度使用捕获的秘密遮罩 scope，终态不保留异常 traceback；线程启动失败会恢复两层登记并保留原失败。
Diagnostics 已接入此共用控制器；其余面板／backend 迁移与原生 session 操作仍列于 `Progress.md`。

主动 **Diagnostics → Actions → 运行诊断** 以共用控制器在 GUI 线程外运行。
**停止诊断** 请求协作式停止；四种语言的状态区分运行中、清理中、已取消和失败，并显示已完成检查数。
重复运行不另开工作，关闭后丢弃延迟进度／结果，显式重试会建立新的拥有者工作。
GUI 以不保留异常 traceback 的 typed outcome 呈现取消；核心／SDK／CLI 与 MCP handler
保持原始直接／包装取消对象。普通检查错误仍计入报告并继续其余项目。

两个 SDK namespace 导出 `CancellationToken`、`TaskProgress`、`cancellation_scope`。
使用 `with cancellation_scope(token): report = run_diagnostics()`，拥有者可由另一线程调用
`token.cancel()`；现有无参数诊断签名不变。Scope 不授予权限，`cancellation_scope(None)`
只在有时限的自有资源清理期间暂停取消。`AC_diagnose` 与新增的只读 `ac_diagnose` 共用报告；
MCP 不接受参数，使用请求取消／进度，与显式 GUI 操作同样需要 `read_screen`，拒绝外部 token／授权数据。
这些是主动检查，截取可能请求同意；`ac_probe_capabilities` 保持独立的被动选项。

Scoped Wayland D-Bus 的连接／读取／部分写入，以最多 0.1 秒的间隔轮询，保持原本总时限。
取消时在原 bus 以独立 0.25 秒预算尝试 Request.Close，再释放连接；取消的已返回图片会删除。
Scoped CLI 截取会停止并回收自己建立的 helper／process group，清理有时限，pipe close 失败也不覆盖原取消，
已回收的数字 PID 不再作为信号目标。liboeffis 获取 session 时会观察停止并释放自身 context。
不强制中断不配合或原生调用，清理期间 GUI 仍可操作；restore／重启、原生 session 控制、
截取拥有者 metadata 与其余面板／backend 迁移保留于 `Progress.md`。

`python -m examples.cancellable_diagnostics` 默认只做受控取消示例，不调用 provider。
`--active --cancel-after 2` 才显式运行诊断并在两秒后请求停止；真机／设备／API 验收另外列管。

打开 Diagnostics 只显示已翻译的「尚未运行」状态，不执行检查。
选择 **Actions → 运行诊断** 才会启动现有主动检查，可能截取屏幕或需要 portal 同意；
切换语言不启动检查。显式的 `run_diagnostics`、`AC_diagnose` 与 MCP 诊断调用保持主动行为；
无副作用的能力查看使用下方独立操作。

未完成的 screenshot portal 请求会在断开原始 bus 前尝试 `Request.Close`，
使用独立的 0.25 秒 D-Bus I/O 预算。服务器返回替代 handle 时会跟随该 handle；
方法回复不确定时则使用预测 handle，已完成的 Response 不重复关闭。
普通清理错误不覆盖主要截取失败；原始取消与强制中断对象会穿过包装及清理继续传播。
D-Bus 写入与回复共用调用预算，连接建立有明确时限，connect／认证／Hello 中断时，
即使 `__enter__` 失败也会释放自己拥有的描述符。实际合成器／对话框取消仍待平台验收。

有一件只在 Wayland 出现、需要事先规划的事：**截取回来的图里可能有鼠标光标。**
这里没有任何一条截取请求光标，但只要 backend 没有光标平面（包含任何以
`WLR_NO_HARDWARE_CURSORS=1` 运行的 session），wlroots 就会画**软件光标**并把它
合成进输出缓冲区，而截取交回来的正是那一份。Windows 与 X11 都不含光标，所以
“定位器、模板匹配或 OCR 在目标中间看到一个光标形状的洞”只会在这里发生。
Wayland 不让客户端读光标位置，所以没有东西可以可靠地遮或避开：请在截取之前
把指针移离要拍的区域。`screen_capture` 检查会以 `cursor_may_be_captured` 报告这件事。

如果以上都不适用你的环境，可以直接指定自己的命令——它优先于所有检测，`{output}` 会被
换成临时 PNG 路径：

```bash
export JE_AUTOCONTROL_WAYLAND_CAPTURE_COMMAND="mycapture --png {output}"
```

Wayland 禁止非特权客户端进行全局输入录制——若要录制，请设置
`JE_AUTOCONTROL_LINUX_DISPLAY_SERVER=x11` 并在 X11 会话下运行。窗口管理支持
Windows、macOS（pyobjc）与 X11（含 XWayland）；纯 Wayland 会话的协议不让客户端看到其他程序的窗口，
所以 `list_windows()` 返回空列表，其余窗口操作一律抛出带原因的 `AutoControlUnsupportedOperationException`。对于会忽略合成输入的应用，
可选用驱动层后端（`JE_AUTOCONTROL_WIN32_BACKEND=interception`、
`JE_AUTOCONTROL_LINUX_BACKEND=uinput`、ViGEm 虚拟手柄）；驱动未安装时会自动回退到原有行为。

---

## 配置

AutoControl 读取的每一个环境变量。这里没有任何一项是必填的：完全不设置时，AutoControl 会自行选择平台后端，服务器只绑定 `127.0.0.1`，所有需要主动开启的功能（签名强制、RBAC、USB 直通、工具路径限制）都是关闭的。[配置参考](https://autocontrol.readthedocs.io/en/latest/Zh/doc/configuration/configuration_doc.html)（[源文件](../../source/Zh/doc/configuration/configuration_doc.rst)）列出完整的可接受值，并把每个变量链接到说明该功能的页面；CI 会拿它以及下面的表格和代码比对。

### 平台后端

| 变量 | 默认 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_WIN32_BACKEND` | `sendinput` | 设为 `interception` 时键盘与鼠标改走 Interception 驱动程序；找不到驱动或 DLL 时会警告并回退到 `SendInput`。 |
| `JE_AUTOCONTROL_LINUX_BACKEND` | `x11` | 设为 `uinput` 时直接写入内核输入事件；`/dev/uinput` 无法写入时会警告并回退到 XTest。 |
| `JE_AUTOCONTROL_LINUX_DISPLAY_SERVER` | `auto` | 决定加载哪一个 Linux 后端：`auto` 读取 `XDG_SESSION_TYPE` 与 `WAYLAND_DISPLAY`；`wayland` 或 `x11` 则强制指定（在 Wayland 会话设为 `x11` 只能操作 XWayland 窗口）。 |

### Windows Interception 驱动程序

| 变量 | 默认 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_INTERCEPTION_DLL` | 未设置：先找 `PATH`，再找包旁边 | `interception.dll` 的完整路径。 |
| `JE_AUTOCONTROL_INTERCEPTION_KEYBOARD` | `1` | 键盘事件要发往的 Interception 设备编号（`1`–`10`）。 |
| `JE_AUTOCONTROL_INTERCEPTION_MOUSE` | `11` | 鼠标事件要发往的 Interception 设备编号（`11`–`20`）。 |

### Wayland

| 变量 | 默认 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_WAYLAND_INPUT_BACKEND` | `auto` | 设为 `cli` 时通过 `ydotool` 发送输入，完全不向桌面 portal 提出请求。这是启动前就做好的选择：用户拒绝授权后，AutoControl 不会自行切换过去。 |
| `JE_AUTOCONTROL_WAYLAND_POINTER_ACCEL` | `warn` | 只影响 `ydotool` 路径的绝对移动（那其实是会被合成器加速的相对位移）：`warn` 警告一次后照样移动，`flat` 表示加速已关闭、不再警告，`strict` 直接拒绝移动。 |
| `JE_AUTOCONTROL_WAYLAND_CAPTURE_COMMAND` | 未设置 | 自定义的截图命令行，以 `{output}` 表示 PNG 的输出路径。优先于 `grim`、`gnome-screenshot`、`spectacle` 与 portal。 |
| `JE_AUTOCONTROL_WAYLAND_RECORD_DEVICES` | 未设置：一个都不读 | `PhysicalRecorder` 可以读取的 `/dev/input/event*` 设备（以逗号分隔）；物理输入录制必须逐一指定设备才会启用。 |

### MCP 服务器

| 变量 | 默认 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_MCP_READONLY` | 未设置 | 设为 `1` 时只提供、也只能调用标记为只读的工具。 |
| `JE_AUTOCONTROL_MCP_TOOL_PROFILE` | 未设置 | `static` 模式的工具清单：以逗号分隔的工具名称与 `category:<名称>`。 |
| `JE_AUTOCONTROL_MCP_ALIASES` | `1` | 设为 `0` 时不注册 `ac_*` 工具之外的简短别名（`click`、`screenshot` …）。 |
| `JE_AUTOCONTROL_MCP_TOKEN` | 未设置 | HTTP 传输的 Bearer 令牌。启用 RBAC 之后不再接受。 |
| `JE_AUTOCONTROL_MCP_ALLOWED_ORIGINS` | 未设置：只接受本机来源 | HTTP 传输额外接受的浏览器来源（以逗号分隔，须完全相符，例如 `https://example.test:8443`）。 |
| `JE_AUTOCONTROL_MCP_CONFIRM_DESTRUCTIVE` | 未设置 | 设为 `1` 时具破坏性的工具在执行前先向客户端请求确认（MCP elicitation）。 |
| `JE_AUTOCONTROL_MCP_PATH_ROOTS` | 未设置：不限制 | 工具的每一个文件参数都必须落在这些目录内（以操作系统的路径分隔符分隔）。 |
| `JE_AUTOCONTROL_MCP_PATH_ROOTS_FROM_CLIENT` | 未设置 | 设为 `1` 时同时接受 MCP 客户端通过 `roots/list` 报告的根目录。 |
| `JE_AUTOCONTROL_MCP_ENV_REF_ALLOW` | 未设置：不限制 | `ac_resolve_ref` 可以读取的环境变量名称（以逗号分隔，可用 `fnmatch` 模式）；设了却没有指名任何变量时，一个都不允许。 |
| `JE_AUTOCONTROL_MCP_AUDIT` | 未设置 | JSON-lines 文件的路径，每一次 `tools/call` 写入一条记录。 |
| `JE_AUTOCONTROL_MCP_ERROR_SHOTS` | 未设置 | 工具每次失败时存放截图的目录。 |
| `JE_AUTOCONTROL_FAKE_BACKEND` | 未设置 | 设为 `1` 时 MCP 服务器只在内存中记录鼠标、键盘与剪贴板调用而不实际执行，供没有显示器的 CI 使用。 |

### REST／RBAC 与 chat-ops

| 变量 | 默认 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_RBAC_USERS` | 未设置：沿用共享令牌 | 用户文件的路径。设置它就等于为 REST API 与 MCP HTTP 传输启用角色。 |
| `JE_AUTOCONTROL_CHATOPS_SCRIPT_ROOT` | 未设置：`run` 会被拒绝 | chat-ops 的 `run` 命令唯一可以加载动作文件的目录。 |

### 执行与签署动作文件

| 变量 | 默认 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_ALLOWED_PACKAGES` | 未设置：一个都不允许 | `AC_add_package_to_executor` 可以加载的包（以逗号分隔，含子模块），对所有入口生效。只在进程启动时读取一次。 |
| `JE_AUTOCONTROL_REQUIRE_SIGNED_ACTIONS` | 未设置 | 设为 `1` 时所有会执行动作文件的路径，都拒绝没有有效签名文件的动作文件。 |
| `JE_AUTOCONTROL_ACTION_SIGNING_PRIVATE_KEY` | 未设置 | Ed25519 私钥（PEM）的路径。只在负责签署的机器上设置；设置后签署会写出第 2 版的签名文件。 |
| `JE_AUTOCONTROL_ACTION_SIGNING_PUBLIC_KEY` | 未设置 | 对应公钥的路径。在每一台执行端设置：它只能验证，不能签署。 |
| `JE_AUTOCONTROL_ACTION_SIGNING_PASSPHRASE` | 未设置 | 私钥创建时若设置了口令，在这里提供。 |
| `JE_AUTOCONTROL_ACCEPT_LEGACY_ACTION_SIGNATURES` | 未设置 | 设为 `1` 是迁移模式：设置公钥之后，第 2 版之前写出的 HMAC 签名文件会被拒绝，除非设置了这个变量。所有文件重新签署后请再关掉。 |

### 远程桌面与信令

| 变量 | 默认 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_REMOTE_DOWNLOAD_DIR` | `~/Downloads/AutoControl` | 远程桌面查看端存放主机传来文件的目录。收到的路径一律限制在这个目录内。 |
| `JE_AUTOCONTROL_USB_PASSTHROUGH` | 未设置 | 设为 `1` 时在远程桌面通道上启用 USB 直通指令。 |
| `AC_SIGNALING_SECRET` | 未设置 | 信令／配置同步服务器的共享密钥（`X-Signaling-Secret`）。服务器在没有 `--shared-secret` 时读取它。 |

### GUI

| 变量 | 默认 | 作用 |
|---|---|---|

### 日志、数据与测试

| 变量 | 默认 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_LOG_FILE` | `~/.je_auto_control/logs/AutoControlGUI.log` | 日志文件写入的位置。指定空设备（`/dev/null`、`NUL`）即可关闭文件输出。在写入第一条记录时才读取，而不是在 import 时。 |
| `JE_AUTOCONTROL_ENV` | `default` | 资产库当前使用的环境（`active_environment()`），让同一份脚本在 `dev` 与 `prod` 读到不同的值。 |
| `JE_AUTOCONTROL_REDACTION` | `off` | 截图遮蔽的默认策略：`off`、`moderate` 或 `strict`。未知的名称会报错，不会被当成 `off`。 |
| `JE_AUTOCONTROL_PYTEST_ARTIFACTS` | `./autocontrol_screenshots` | 测试没有使用 `autocontrol_screenshot_dir` fixture 时，pytest 插件写入失败截图的目录。 |

---
