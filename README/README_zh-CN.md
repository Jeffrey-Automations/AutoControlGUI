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

View → 执行详情（Ctrl+Shift+D）可展开右侧详情。诊断分页会提供实际进度、停止、结果与错误状态，其他在后台执行工作的分页（模型请求、USB 列举、广播、DAG 执行、日志读取）也会：执行中、停止中，然后是完成、已取消或错误，工作有回报进度时一并显示。尚未执行过工作的分页会明确显示没有详情。切换或关闭分页会断开其更新。嵌入程序可将 TabRegistry 传入 WorkspaceShell；AutoControlGUIWidget(parent) 仍可使用。

每个分页开头都有标题与一行用途说明，控件按用途分组在卡片上；复选框与单选按钮以主题强调色绘制，深色主题下也看得清楚。控件会随窗口缩小，不再撑宽页面：下拉菜单不再以最长项目决定宽度，表单字段放不下时标签移到字段上方，长说明会自动换行。窗口会依宽度重新排列：1,200 px 以上，导航与执行详情并排在分页两侧；较窄时详情改为覆盖在分页上的抽屉；800 px 以下导航缩成窄图标栏，按其菜单按钮或 Ctrl+K 以抽屉打开功能列表（Escape 或点击旁边即关闭）。因宽度隐藏导航不会改动已保存的偏好。

WebRTC 统计轮询在后台启动，停止后会丢弃延迟到达的样本。

Windows、macOS、X11 与 Wayland 使用不同后端，实际功能取决于系统权限与可选依赖。Windows ARM64 另有限制，部署前请先阅读安装文件。

Wayland NORMAL 输入通过受管理的子进程执行 libei 与 portal 调用。超时、取消或回复不确定时会退役该进程，不重播输入或自动切换提供者。直接使用 `LibeiBackend` 仍在调用端进程内执行；子进程退役不代表合成器已释放输入，原生验收仍待执行。

受管理的 Agent 任务与跨主机传输包含实验性功能；采用前请查看实现记录与项目进度中的验收状态。

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

关闭 Remote Desktop 会释放页面；重新打开会创建新控件，不自动接回共享连接。Registry 的 TCP／WebSocket 连接仍可供脚本使用；页面拥有的 WebRTC 连接与音频在后台停止。待处理批准会拒绝，延迟回调会丢弃。已进入发送阶段的文件传输须依后端的协作式取消停止。

WebRTC host/viewer 的 `stop()` 最多等待三秒完成软件清理。`PeerStopPending` 保留同一个尚未完成的操作；显式重试只会继续等待。`PeerStopFailed` 保留清理失败的资源供显式重试，成功前禁止重新启动。Multi-viewer host 保留失败的 session 与共享来源。`FolderSyncEngine.stop_confirmed()` 在原工作线程仍存活时返回 `False`。这些结果不代表原生设备已释放；页面销毁后的恢复仍需持久资源保管与重试整合。

主机文件请求会保留原发送工作，直到工作线程退出，重复停止也不会提前释放所有权。停止会通知取消并等待原工作；无法中断的后端操作仍可能让停止保持待完成。

MCP 只读标记不授予 viewer 访问权限。已审查的实时画面与调用者数据运算使用 `read_screen`；文件、设备数据及未知工具需要 `read_data`。别名共用标准名称的权限，较强的明确设置优先。提供图像来源、从环境变量读取配置字段或规划打开本地文件时需要 `read_data`。Anchor locator 的 accessibility／OCR 允许观察实时画面，图像模板需要 `read_data`，VLM 请求需要 `drive_input`。只读调用拒绝捕获产物及 VLM 分支，目录排除可自选 ADB 可执行文件的工具。MCP CI annotations 只返回格式化文本，不写入 stdout。未经审查的 plugin 与 WebRunner 初始化工具不列入只读目录，等待依赖版本的单独审查。

MCP 的 `tools/call` 以可停止的执行进行，列为 `mcp-…`。`notifications/cancelled` 会停掉它：`ac_execute_actions` 的动作列表在下一个动作前停下，`ac_wait_for_image`／`ac_wait_for_pixel` 在轮询中途醒来；该次调用以 `-32800` 回复。`ac_stop_execution` 与其他停止请求以同样方式结束它，报告为工具错误。已经进入后端的单个指令仍会先执行完。

REST 主机数据读取与对应 MCP 权限一致：调度、远程 session、USB passthrough 状态、loopback／remote 设备列表及诊断需要 `read_data`。对应已注册的状态命令、`AC_probe_capabilities` 与 `AC_diagnose` 会在运行提供者之前检查权限。只读标记不授予 viewer 访问权；operator／admin 仍可使用。USB 枚举／事件、保留的 inspector 统计与进程 metrics 也需要 `read_data`；`AC_list_usb_devices`、`AC_usb_recent_events`、`AC_inspector_recent`、`AC_inspector_summary` 同样检查此权限。Dashboard 各面板分别显示缺少的权限并清除旧数据；session 刷新成功后也会清除先前的错误状态。未列入权限表的 executor 命令仍属于另一项审查范围。

主机只读模式对外部提供的目录及后续注册应用相同限制，接收请求及重新核对身份后的调用都检查混合用途参数。MCP 配置的失败截图需要可写入的工具及重新核对后具输入操作权限的调用者；只读调用与 viewer 不会触发截图。这不表示所有依赖包或诊断读取均无初始化副作用。

内部 Windows 进程内存准备工作新增映像文件测量，通过保留的只读 handle 执行有界哈希并保留失败清理供重试。这只是观察到的文件证据，不是已加载代码或 fixture 的身份证明；原生验收及公开内存工具仍未提供。详见[契约](../docs/process_memory_contract.md)。

WebRTC peer 也会保留媒体构造与清理失败的原始资源，观测即时停用完成，并将延后协商绑定原 peer。媒体 producer 关闭会报告待完成或不确定的清理结果，并保留原始资源。音频与录影不会通过不安全的 close／flush 重播宣称成功；LAN close 可明确重试。应用程序 caretaker 与 GUI 整合仍待完成。详见[清理契约](../docs/media_retirement_contract.md)。

HostBrowser 也会拒绝晚到发布，并保留未完成的线程与关闭所有权；对话框整合仍待完成。

MultiViewerHost 可返回含原始 session 清理对象的 offer，延后清理不会停止替换后的连接或画面来源；GUI 接入仍待完成。
