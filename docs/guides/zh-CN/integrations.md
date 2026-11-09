# Agents and integrations

[README](../../../README/README_zh-CN.md) · [Documentation](../../README.md)

## AI Agent 与 Computer Use

**AutoControl 是开源、跨平台的 computer-use 与 GUI 自动化框架。**

当 AI agent 需要操作真实桌面、原生应用程序、真实浏览器窗口、远程桌面或移动设备，而不只是操作浏览器 DOM/API 时，使用 AutoControl。

### 何时选择 AutoControl

- 真实鼠标与键盘输入
- 屏幕截图与坐标操作
- OCR 与原生无障碍树
- 图像／模板匹配
- Vision-Language Model UI 定位
- Anchor 与 self-healing locator
- 跨平台桌面／移动设备自动化
- JSON 动作文件
- MCP computer use

建议的 agent loop：

**observe → identify → act → wait → verify → recover**

完整的 [AI Agent 指南](../../../AI.md) 提供 MCP 配置、工具选择、OpenAI 集成、安全性与 computer-use 关键词。

### AI-friendly MCP

```bash
pip install je_auto_control
je_auto_control_mcp
```

MCP 提供完整的 `ac_*` 工具，以及 `click`、`type`、`screenshot`、`find_text`、`click_text`、`drag`、`focus_window`、`wait_image` 等短名称 alias。

只做检查：

```bash
je_auto_control_mcp --read-only
```

只需要 canonical `ac_*` 名称：

```bash
JE_AUTOCONTROL_MCP_ALIASES=0 je_auto_control_mcp
```

OpenAI agent 请使用 `export_openai_tools(only=[...])` 提供聚焦工具集，不要一次提供整个 AutoControl 命令目录。

### 项目识别

**项目：** AutoControl<br>
**Repository：** `Integration-Automation/AutoControlGUI`<br>
**Python package / PyPI：** `je_auto_control`<br>
**MCP command：** `je_auto_control_mcp`


---


## 服务器与集成

| 接口 | 启动方式 | 说明 |
|---|---|---|
| **MCP 服务器** | `je_auto_control_mcp`（stdio）或 `AC_start_mcp_http_server` | 820 个工具，供 Claude Desktop／Claude Code／自定义 tool loop 使用：完整的 `ac_*` 工具接口，以及常用 GUI 操作的短名称 alias。除了以 `initialize` 握手的各版协议，也支持无状态的 MCP 2026-07-28。Bearer 认证、TLS、审计日志、限流、插件热重载、CI 假后端。 |
| **REST API** | `je_auto_control start-rest` | Bearer token、按 IP 限流与锁定、SQLite 审计 hook、`/metrics`、`/openapi.json`、`/docs` Swagger UI、`/dashboard`。 |
| **TCP socket 服务器** | `je_auto_control start-server` | 以换行分隔的 JSON 动作列表。默认绑定 `127.0.0.1`。 |
| **pytest 插件** | 安装后自动生效 | 提供 fixture 与供 pytest-bdd／behave 使用的 Gherkin step library。 |
| **语言服务器** | `python -m autocontrol_lsp.server` | 为 `AC_*` 动作 JSON 提供补全与诊断，命令清单直接取自运行期的命令表。 |
| **远程桌面** | `RemoteDesktopHost` 或 GUI | TCP、WebSocket 或 WebRTC；TOTP、信任列表、TURN 配置、文件／剪贴板／音频同步。 |

除非明确指定，所有服务器都绑定在 `127.0.0.1`。

MCP 窗口状态工具 `ac_window_minimize`、`ac_window_maximize` 与 `ac_window_restore` 在后端接受请求时返回窗口 handle，被拒绝时回复 `isError: true`（包括 handle 失效或激活请求被拒）。Win32 原始 `ShowWindow` 的先前可见性由后端规范化处理。

**包闸门。** `AC_add_package_to_executor` 与 `AC_add_package_to_callback_executor` 会导入 Python 包并把成员注册成命令，所以从上面任何一个入口送来的动作列表都可能加载 `os` 或 `subprocess`。没有被放行的包不会加载：不在允许清单上的包在导入前就被拒绝，该动作以 `AutoControlExecuteActionException` 失败。放行包（含子模块）的方式：在 Python 里调用 `executor.allow_packages("name", …)`；对所有入口——两个 CLI、socket／REST／MCP 服务器与调度器——设置环境变量 `JE_AUTOCONTROL_ALLOWED_PACKAGES`（以逗号分隔的名称，进程启动时读取）；或只对一次 CLI 执行使用 `je_auto_control run script.json --allow-package NAME`（可重复）。`executor.set_allow_arbitrary_packages(True)` 会对所有包打开闸门，也就是先前版本的默认行为（当时会发 `DeprecationWarning`）。这些都不是 `AC_*` 命令，所以动作列表不能自己打开闸门。

**可选的加固设置。** 下列各项在设置之前都是关闭的，没设置的服务器行为与先前相同。`JE_AUTOCONTROL_RBAC_USERS=<用户文件>` 让 REST API 与 MCP HTTP 传输把 bearer token 对应到用户，并按角色（viewer／operator／admin）授权每一个路由、工具与特权 `AC_*` 命令；此时共用 token 会被拒绝。`JE_AUTOCONTROL_MCP_PATH_ROOTS`（以操作系统的路径分隔符分开的目录）把每一个属于文件路径的 MCP 工具参数限制在这些目录里，`JE_AUTOCONTROL_MCP_PATH_ROOTS_FROM_CLIENT=1` 再加上 client 的 `roots/list`，`JE_AUTOCONTROL_MCP_ENV_REF_ALLOW` 限制 `ac_resolve_ref` 可以读哪些 `env://` 名称。`JE_AUTOCONTROL_ACTION_SIGNING_PUBLIC_KEY` 让端点只能验证 Ed25519 签名的动作文件而不能签名（`create_signing_keypair`；私钥留在签名的机器上）。远程桌面的 viewer 只把 host 推来的文件写在 `~/Downloads/AutoControl` 下面（`JE_AUTOCONTROL_REMOTE_DOWNLOAD_DIR`）；这一项默认就是开的。

REST GUI 在用户存储文件启用时显示 RBAC 模式并禁用共用 token 字段。`rest_api_registry.status()` 提供 `rbac_enabled`，该模式的 `token` 为 `null`；请使用个别用户 token。只实现 `check()` 的自制 REST gate 仍可用于共用 token 模式；RBAC 要求已验证的用户 context，会拒绝没有身份的成功结果。

RBAC viewer 不会取得列管的敏感读取工具，即使 MCP `readOnlyHint` 为 true：剪贴板／历史、本机文档／数据／SQL 与 dotenv 读取、引用解析、认证数据生成、持久存储读取、对外检查、麦克风捕获与外部 VLM 请求都需要 operator／admin。断言容器的 spec 也可能读取这些资源，因此同样需要 operator。屏幕观察与纯输入解析保持既有分类。`ac_realize_item`、`ac_idempotency_begin` 与 `ac_rate_limit` 会改变状态，已从 `--read-only` 模式排除。

间隔／cron 调度、触发器、热键、watchdog 规则、webhook、e-mail 触发器与 observer 回调会保留注册者身份。每次触发重新检查来源用户文件与角色；已删除的用户、无法使用的来源文件与 viewer 不能执行后台工作。启动 daemon 不会改变已有工作的所有者。所有者信息不保存 RBAC bearer token；未带 `store_path` 的显式 Python `AuthorizationContext` 保留角色快照，未在 RBAC 下注册的工作会清除 worker 原有身份。observer／watchdog 回调使用独立变量作用域，watchdog 动作失败不会算成成功消除弹窗。嵌套回调会保留调用端的失败计数；webhook 所有者被撤销权限时响应 HTTP 403 与 `fired: false`。

### 远程桌面的线路协议

TCP host 在发送 `AUTH_FAIL` 前就释放认证失败的 client 名额。Viewer 即使因错误 token、错误握手消息或拒绝批准而失败，也能立即重试，不必等待 socket 清理或日志完成；待处理握手仍有独立的资源上限。

把主机开放出去之前值得先了解，而且这一段在其他文档里都没有写。默认传输是**裸
TCP 上的长度前缀分帧**（不需要额外依赖），连接一开始就是 **HMAC-SHA256 的
challenge／response 握手**：认证不通过的观看端在拿到任何一帧之前就会被断开。
JPEG 帧按配置的 FPS 与质量编码，再通过一个共享的**最新帧槽**发给已认证的观看
端——所以慢的观看端是**丢帧**，不会把其他人一起卡住。观看端发来的输入是 JSON，
会先比对**动作允许列表**才交给既有的输入包装层执行，观看端无法自己发明新的操作。

```python
# 让别人连进来——启动一个主机，把 token 与 port 给对方
from je_auto_control import RemoteDesktopHost
host = RemoteDesktopHost(token="hunter2", bind="127.0.0.1",
                         port=0, fps=10, quality=70)
host.start()
print("listening on", host.port, "viewers:", host.connected_clients)
```

```python
# 控制另一台机器——连上去并发送输入
from je_auto_control import RemoteDesktopViewer
viewer = RemoteDesktopViewer(host="10.0.0.5", port=51234, token="hunter2",
                             on_frame=lambda jpeg: ...)
viewer.connect()
viewer.send_input({"action": "mouse_move", "x": 100, "y": 200})
viewer.disconnect()
```

也可以用 IP 允许列表（CIDR 网段或具体地址）限制谁能连进来，列表外的对端在握手
阶段就会被拒绝：

```python
RemoteDesktopHost(token="tok", ip_allowlist=["10.0.0.0/8", "192.168.1.100"])
```

---
