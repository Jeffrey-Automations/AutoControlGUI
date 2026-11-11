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

View → 执行详情（Ctrl+Shift+D）可展开右侧详情。诊断分页会提供实际进度、停止、结果与错误状态；其他分页尚未提供时会明确显示。切换或关闭分页会断开其更新。嵌入程序可将 TabRegistry 传入 WorkspaceShell；AutoControlGUIWidget(parent) 仍可使用。

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

关闭 Remote Desktop 会释放页面；重新打开会创建新控件，不自动接回共享连接。Registry 的 TCP／WebSocket 连接仍可供脚本使用；页面拥有的 WebRTC 连接与音频在后台停止。待处理批准会拒绝，延迟回调会丢弃。已进入发送阶段的文件传输不会因关闭页面而中断。
