# AutoControl

[English](../README.md) | [繁體中文](README_zh-TW.md) | [简体中文](README_zh-CN.md)

AutoControl 是用来操作桌面应用程序的 Python 自动化框架。你可以控制鼠标与键盘、截取画面，并通过图片、OCR 或无障碍 API 寻找界面元素。支持 Python、JSON 动作文件、桌面 GUI 与 MCP 客户端。

## 开始使用

需要 Python 3.11 以上版本。

```bash
python -m pip install je_auto_control
```

先读取屏幕尺寸，这个示例不会送出键盘或鼠标输入：

```python
import je_auto_control as ac

print(ac.screen_size())
```

要使用桌面界面，安装 GUI 包后启动：

```bash
python -m pip install "je_auto_control[gui]"
python -c "import je_auto_control; je_auto_control.start_autocontrol_gui()"
```

窗口打开时，程序会关闭自动回收，改由 GUI 线程上的定时器回收 Python 的循环垃圾，退出时再打开。这是为了不让 worker 线程碰到 PySide6 6.12 会延后删除的 Qt 对象；那条路径在 Windows 上曾让进程 abort。只 `import je_auto_control` 的脚本不受影响。

## 可以做什么

- 操作鼠标、键盘与窗口。
- 用图片比对、OCR、无障碍 API 或可选的视觉模型寻找控件。
- 将重复工作保存为 JSON 动作文件。
- 通过 MCP 连接 AI 客户端，或通过 REST 与 Python 整合。
- 在可选 GUI 中使用录制、调度与远程桌面工具。

图像检测分页在后台执行匹配，并有自己的鼠标按键选择。
Actions 菜单可停止待完成的搜索；关闭分页会丢弃延迟结果，重新打开会重置输入字段。
取消可阻止后续移动与点击步骤，但无法中断已进入的原生调用。

自动点击、录制与脚本执行分页各自持有控件与后台任务；关闭会停止本页任务，重新打开会建立新的输入框。共享录制器不随分页关闭，重新打开后会读取后端状态，不支持查询时显示未知；此状态不代表原生钩子健康检查。Ctrl+4 仍可停止脚本与自动点击。

启动时打开的三个标签页只先创建 Record；Script Builder 与 Remote Desktop 在第一次被选中时才创建，启动时间与内存约减半。

View → 执行详情（Ctrl+Shift+D）可展开右侧详情。诊断分页会提供实际进度、停止、结果与错误状态，其他在后台执行工作的分页（模型请求、USB 列举、广播、DAG 执行、日志读取）也会：执行中、停止中，然后是完成、已取消或错误，工作有回报进度时一并显示。尚未执行过工作的分页会明确显示没有详情。后台停止失败时（页面放开的连接、录制或主机）会被保留而不只记录日志：诊断分页列出每一个及其错误，Actions › 重试失败的停止 会以排入时的权限再次执行。切换或关闭分页会断开其更新。嵌入程序可将 TabRegistry 传入 WorkspaceShell；AutoControlGUIWidget(parent) 仍可使用。

每个分页开头都有标题与一行用途说明，控件按用途分组在卡片上；复选框与单选按钮以主题强调色绘制，深色主题下也看得清楚。控件会随窗口缩小，不再撑宽页面：下拉菜单不再以最长项目决定宽度，表单字段放不下时标签移到字段上方，长说明会自动换行。空的表格、列表或树状清单会显示「暂无内容。」，直到第一笔数据出现，不再只显示空白格线。页面标题下方的横幅会说明该页上次执行失败（下次执行时清除），GUI 在 RBAC 范围内执行时也会说明当前角色无法执行该页的哪些指令；横幅附有关闭链接。窗口会依宽度重新排列：1,200 px 以上，导航与执行详情并排在分页两侧；较窄时详情改为覆盖在分页上的抽屉；800 px 以下导航缩成窄图标栏，按其菜单按钮或 Ctrl+K 以抽屉打开功能列表（Escape 或点击旁边即关闭）。因宽度隐藏导航不会改动已保存的偏好。

WebRTC 统计轮询在后台启动，停止后会丢弃延迟到达的样本。

Windows、macOS、X11 与 Wayland 使用不同后端，实际功能取决于系统权限与可选依赖。Windows ARM64 另有限制，部署前请先阅读安装文件。

Wayland NORMAL 输入通过受管理的子进程执行 libei 与 portal 调用。超时、取消或回复不确定时会退役该进程，不重播输入或自动切换提供者。直接使用 `LibeiBackend` 仍在调用端进程内执行；子进程退役不代表合成器已释放输入，原生验收仍待执行。

受管理的 Agent 任务与跨主机传输包含实验性功能；采用前请查看实现记录与项目进度中的验收状态。

主机选定的语义 target 支持 `semantic` 完成条件，用新读回核对已记录的目标身份及期望字段。此条件不授予内存访问权，也不启用原生 target。详见[语义完成验证](../docs/process_memory_contract.md#semantic-completion)。

## 文件

- [安装、平台支持与配置](../docs/guides/zh-CN/setup.md)
- [Python、JSON 与命令行用法](../docs/guides/zh-CN/usage.md)
- [AI Agent、MCP 与服务器整合](../docs/guides/zh-CN/integrations.md)
- [完成验证与证据移交](../docs/guides/zh-CN/evidence.md)
- [开发与相关资源](../docs/guides/zh-CN/development.md)
- [实现记录](../docs/guides/zh-CN/implementation-notes.md)
- [文档目录](../docs/README.md)
- [示例](../examples/README.md)
- [项目进度](../Progress.md)

## 许可

[MIT](../LICENSE) © JE-Chen. [第三方许可](../Third_Party_License.md).

关闭 Remote Desktop 会释放页面；重新打开会创建新控件，不自动接回共享连接。Registry 的 TCP／WebSocket 连接仍可供脚本使用；页面拥有的 WebRTC 连接与音频在后台停止。待处理批准会拒绝，延迟回调会丢弃。正在发送的文件传输会在页面关闭、连接被放掉或上传取消时于下一个区块停止，主机会丢弃未完成的文件（TCP、WebSocket 与 WebRTC 皆同）。

WebRTC host/viewer 的 `stop()` 最多等待三秒完成软件清理。`PeerStopPending` 保留同一个尚未完成的操作；显式重试只会继续等待。`PeerStopFailed` 保留清理失败的资源供显式重试，成功前禁止重新启动。Multi-viewer host 保留失败的 session 与共享来源。`FolderSyncEngine.stop_confirmed()` 在原工作线程仍存活时返回 `False`。这些结果不代表原生设备已释放；页面销毁后的恢复仍需持久资源保管与重试整合。

主机文件请求会保留原发送工作，直到工作线程退出，重复停止也不会提前释放所有权。停止会通知取消并等待原工作；无法中断的后端操作仍可能让停止保持待完成。

MCP 只读标记不授予 viewer 访问权限。已审查的实时画面与调用者数据运算使用 `read_screen`；文件、设备数据及未知工具需要 `read_data`。别名共用标准名称的权限，较强的明确设置优先。提供图像来源、从环境变量读取配置字段或规划打开本地文件时需要 `read_data`。Anchor locator 的 accessibility／OCR 允许观察实时画面，图像模板需要 `read_data`，VLM 请求需要 `drive_input`。只读调用拒绝捕获产物及 VLM 分支，目录排除可自选 ADB 可执行文件的工具。MCP CI annotations 只返回格式化文本，不写入 stdout。未经审查的 plugin 与 WebRunner 初始化工具不列入只读目录，等待依赖版本的单独审查。

MCP 的 `tools/call` 以可停止的执行进行，列为 `mcp-…`。`notifications/cancelled` 会停掉它：`ac_execute_actions` 的动作列表在下一个动作前停下，`ac_wait_for_image`／`ac_wait_for_pixel` 在轮询中途醒来；该次调用以 `-32800` 回复。`ac_stop_execution` 与其他停止请求以同样方式结束它，报告为工具错误。已经进入后端的单个指令仍会先执行完；例外的是捕获输出的 shell 指令（`ac_shell`、`AC_shell_to_var`），它的进程树会被结束；HTTP 请求（`AC_http_request`、`ac_http_request` 与其他走共用 HTTP client 的调用），它的 socket 会被关闭；以及一次模板匹配、OCR、VLM 定位请求或只读无障碍树遍历，调用不再等它（原生运算或请求在后台跑完、结果丢弃）；这些调用都随即结束。单个手势内的节奏等待也会醒来：`click_mouse` 连点之间的间隔、补间拖拽的每步与稳定停顿（按键在光标停下的位置松开），以及拟人移动与拟人打字的每步、每键延迟。

REST 主机数据读取与对应 MCP 权限一致：调度、远程 session、USB passthrough 状态、loopback／remote 设备列表及诊断需要 `read_data`。对应已注册的状态命令、`AC_probe_capabilities` 与 `AC_diagnose` 会在运行提供者之前检查权限。只读标记不授予 viewer 访问权；operator／admin 仍可使用。USB 枚举／事件、保留的 inspector 统计与进程 metrics 也需要 `read_data`；`AC_list_usb_devices`、`AC_usb_recent_events`、`AC_inspector_recent`、`AC_inspector_summary` 同样检查此权限。Dashboard 各面板分别显示缺少的权限并清除旧数据；session 刷新成功后也会清除先前的错误状态。未列入权限表的 executor 命令仍属于另一项审查范围。

主机只读模式对外部提供的目录及后续注册应用相同限制，接收请求及重新核对身份后的调用都检查混合用途参数。MCP 配置的失败截图需要可写入的工具及重新核对后具输入操作权限的调用者；只读调用与 viewer 不会触发截图。这不表示所有依赖包或诊断读取均无初始化副作用。

内部 Windows 进程内存准备工作新增映像文件测量，通过保留的只读 handle 执行有界哈希并保留失败清理供重试。这只是观察到的文件证据，不是已加载代码或 fixture 的身份证明；原生验收尚未完成，且不提供任意地址内存工具。详见[契约](../docs/process_memory_contract.md)。

主机管理的 fixture profile 通过既有目标管理 API 与 GUI JSON 编辑器，将固定 worker 绑定到已审阅的配置路径和摘要。注册不会取得资源；bootstrap 与 configure 都核对部署绑定。明确调用 probe 时，会由有时限的后台 helper 检查静态产物，报告 `static_artifacts_ready`、`fixture_execution=not_run` 与 `native_evidence=not_recorded`。runtime 关闭时，会保留所有权直到诊断 helper 完成回收。fixture 仅在受管 readiness 中取得。配置与映像检查不证明 Python 源码或 DLL 可信。原生执行仍暂停；私有交付格式与限制记载于同一契约。

WebRTC peer 也会保留媒体构造与清理失败的原始资源，观测即时停用完成，并将延后协商绑定原 peer。媒体 producer 关闭会报告待完成或不确定的清理结果，并保留原始资源。音频与录影不会通过不安全的 close／flush 重播宣称成功；LAN close 可明确重试。应用程序 caretaker 与 GUI 整合仍待完成。详见[清理契约](../docs/media_retirement_contract.md)。

HostBrowser 也会拒绝晚到发布，并保留未完成的线程与关闭所有权；对话框整合仍待完成。

MultiViewerHost 可返回含原始 session 清理对象的 offer，延后清理不会停止替换后的连接或画面来源；GUI 接入仍待完成。

主机选定的语义 adapter 可通过既有观察 API 返回多来源报告。fixture 结合经审阅的内存读取与自有只读 IPC snapshot，并在提交前重新核对两者。报告版本 3 由主机程序固定必要字段，分别保留有效字段与各字段的失败原因。缺失来源、冲突与 best-effort 读取不能授权操作或确认完成。版本 1 与 2 会被拒绝。

独立自有 UI 观察 fixture 可通过 `test/fixtures/native_memory/build_fixture.py --kind uia` 构建，静态 manifest 维持 schema 2。内部 launcher 将启动消息绑定保留进程与窗口所有者。限定范围的 UIA reader 核对该窗口、进程与根节点身份，限制树遍历并保护密码字段。只读受管 adapter 延迟创建 COM，通过共用观察 API 保留部分字段结果。

注入调用与隐藏 Python helper 已覆盖限定范围读取、报告与超时回收。原生部署信任、DOM 整合与桌面验收仍待完成，尚未执行原生 UI fixture，也未证明不干扰桌面。

内部自有 UI target 在 attestation 前保留启动器及两个独立映像租约拥有者；
清理会尝试全部资源并保留失败项目供重试。发布锁防止关闭后存入晚到的来源。
原生 factory 仅建立拥有者；原生部署信任及原生验收仍待完成。

主机管理可注册 `uia_fixture` profile，`allowed_tools`、`roots`、`apps` 都为空，
配置只接受 `config_path`／`config_sha256`。固定隔离 worker 在取得资源前核对部署、profile
与目标 pin，两端都拒绝命令。外部任务只有在没有预排动作时可使用空工具集合；
仍须提供完成条件，空计划不能证明完成，UI partial／best-effort 报告仍只供诊断。
注册与 probe 不取得资源；probe 返回 `not_supported` 与 `native_evidence=not_recorded`。
既有目标 API、CLI 与 GUI JSON 编辑器可传递此 profile。注入及隐藏 helper 测试不代表原生信任成立。

主机选定的进程内服务 adapter 可使用封闭的 `service_state` 完成条件：
`{"kind":"service_state","tool":"AC_service_start","state":"running"}`，或 STOP／stopped。
判定须有对应操作的确认回执，以及同一资源所有者在接受后取得的新 SCM 查询。
通过只表示 SCM 报告该状态，不证明原子完成、健康或桌面无干扰。这些工具名称仅属于
adapter 范围，不是全局 executor 指令。现有任务 API 与 GUI JSON 编辑器可传递此条件。
主机审阅的 `service` profile 固定 `config_path`、`config_sha256` 及 `service_key`。
非 ASCII 的键以 Windows 本身的 NT upcase 表做大小写折叠，不用 Python 的大小写映射，
因此 SCM 视为同一服务的各种写法共用同一把锁。
固定 worker 核对部署的服务与操作上限后才接受任务范围。注册、重载与 probe 不读取部署文件
或访问 SCM；原生验收仍待完成。
所有固定路径（各 profile 的 `config_path` 及部署指定的映像文件）都必须是本机磁盘路径：
UNC 共享、`\\.\pipe\` 名称、`\\?\` 设备路径与 `..` 片段一律拒绝，注册 profile 不能让主机把凭据发送到其他机器。
browser profile 也可声明主机审阅的 `semantic_fields`：最多 64 条 `{name, selector, frame?, property}`，property 为 `text`、`value` 或 `visible`。之后每次浏览器观察都会附上共用 observation report 格式的 `semantic_report`。来源绑定受管浏览器 context，新 session 即为新的目标生命周期；元素不存在报告 `not_found`，SDK 拒绝读回的值（密码、隐藏、文件或 `data-secret` 字段）报告 `protected`，读取期间换页则整个来源为 `inconsistent_snapshot`。捕获编号与时间不列入，页面未变时动作前的指纹保持相同。selector 必须唯一，因为 SDK 遇到不唯一的 selector 会让 session 退休。DOM 读取没有 revision，保持 best-effort；实际浏览器验收仍待完成。
`android` 目标 profile（设置 `serial`、`physical_id`、`package`，可选 `adb_port`、`user`、`idle_seconds`；单一 app；工具 `AC_android_tap`／`AC_android_swipe`／`AC_android_key`）经设备端 helper 操作一台设备，helper 须已安装并运行。真机验收仍待完成。
fixture 映像执行前，租约还会拒绝其他账户能更改的位置：从磁盘根目录往下的每一层都必须是实体目录
（不能是 junction 或 symlink），且只有 SYSTEM、Administrators、TrustedInstaller 与当前用户能改名、删除、
改 ACL 或新增文件；租约文件的最终路径也必须等于配置的路径。请把 fixture 部署在 `%LOCALAPPDATA%` 这类受保护目录；
授予 Authenticated Users 修改权限的磁盘根目录（次要磁盘常见）或共享的 `%TEMP%` 会被拒绝。
fixture 在自己的目录启动，只带最小环境变量：仅含系统目录的 `PATH`，不带主机的任何 token 或密钥。
