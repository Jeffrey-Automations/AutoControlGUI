# Automation usage

[README](../../../README/README_zh-CN.md) · [Documentation](../../README.md)

## 为什么选择 AutoControl

- **一套 API，七个平台。** `wrapper/platform_wrapper.py` 在导入时挑选后端；同一份脚本在
  Windows、macOS、X11 与 Wayland 上都不需要改写。
- **不写 Python 也能脚本化。** 911 个 `AC_*` 命令覆盖全部功能，因此一个 JSON 文件能做到库
  能做的任何事——包含循环、分支、try/catch、宏与变量。
- **默认无头运行。** `import je_auto_control` 绝不会加载 Qt。GUI 是可选包，包在同一个无头内核之外。
  公开导出项在被访问时才加载来源模块。`__all__` 与 `dir()` 可列出名称，不必加载全部功能；
  通配符导入会请求所有名称。尚未解析的名称不会出现在 `vars(je_auto_control)`。
  X11 的普通包导入不会打开显示连接或输入设备，也不会启动键盘监听。
  桌面操作在调用时才获取资源。读取 `keyboard_keys_table` 或调用
  `get_keyboard_keys_table()` 会解析实际服务器键码，因此需要 X 连接。
- **四种定位方式。** 模板匹配、OCR、无障碍树、视觉语言模型——可通过锚点定位器与自愈回退串接组合。
- **依赖基线轻量。** REST 服务器、JSON Schema 校验、JWT、TOTP、WebSocket 帧、ACME 客户端、
  USB/IP 协议与 Prometheus 指标全部以标准库实现；较重的依赖都是可选项。


## 如何选择自动化层

AutoControl 不需要取代所有自动化工具；应选择最符合界面的那一层：

| 需求 | 适合工具 |
|---|---|
| 稳定的浏览器 DOM／API 自动化 | Playwright／Selenium |
| 简单的 Python 鼠标键盘脚本 | PyAutoGUI 或 AutoControl |
| 原生桌面应用程序自动化 | **AutoControl** |
| 无障碍树 GUI 自动化 | **AutoControl** |
| OCR GUI 自动化 | **AutoControl** |
| 截图／视觉模型 GUI 定位 | **AutoControl** |
| Self-healing 跨平台 GUI locator | **AutoControl** |
| AI agent 操作真实桌面 | **AutoControl + MCP** |
| 确定性的 JSON GUI workflow | **AutoControl** |

AutoControl 的差异在于把 **真实电脑输入 + 语义／视觉定位 + self-healing + agent/MCP 集成** 放在同一个跨平台自动化接口中。


## 60 秒上手

**1. 作为 Python 库**

```python
import je_auto_control as ac

ac.set_mouse_position(500, 300)
ac.click_mouse("mouse_left")
ac.write("Hello World")
ac.hotkey(["ctrl_l", "s"])

x, y = ac.locate_image_center("save_button.png", detect_threshold=0.9)
ac.click_text("Submit")                       # OCR
ac.click_accessibility_element(name="OK")     # 无障碍树
ac.click_by_description("the green Submit button")   # 视觉模型
ac.screenshot("shot.png", screen_region=[0, 0, 800, 600])
```

**2. 作为 JSON 动作文件** — `flow.json`

```json
[
    ["AC_set_var", {"name": "user", "value": "alice"}],
    ["AC_locate_and_click", {"image": "login.png", "mouse_keycode": "mouse_left"}],
    ["AC_write", {"write_string": "${user}"}],
    ["AC_retry", {"max_attempts": 3, "body": [
        ["AC_wait_text", {"target": "Welcome", "timeout": 10}]
    ]}],
    ["AC_assert_text", {"text": "Welcome"}],
    ["AC_generate_html_report", {"html_name": "report"}]
]
```

```bash
je_auto_control run flow.json --var user=bob
je_auto_control run flow.json --dry-run     # 只列出步骤，不会真的动鼠标
```

**3. 作为桌面应用**

```bash
pip install je_auto_control[gui]
python -c "import je_auto_control; je_auto_control.start_autocontrol_gui()"
```

录制一段流程、在可视化 Script Builder 里编辑，然后存成 CLI 能直接执行的同一种 JSON 格式。
（`python -m je_auto_control` 是旧式的动作文件执行器——`-e`、`-d`、`-c`、`--execute_str`——不会打开 GUI。）

---

## 能力总览

每一行都能无头执行。“GUI 标签页”是同一功能在桌面应用中的位置；标签页的命令都放在窗口的
**Actions** 菜单里。

| 能力 | Python API | `AC_*` 命令 | GUI 标签页 |
|---|---|---|---|
| 鼠标 | `click_mouse`（`clicks=2` 即双击）、`set_mouse_position`、`mouse_scroll`、`tween_drag`／`drag_path`（以 `step_delay_s`、`settle_s` 控制节奏） | `AC_click_mouse`、`AC_tween_drag`、`AC_drag_path` | Auto Click |
| 键盘 | `write`、`write_secret`、`hotkey`、`type_keyboard`、`keyboard_key_name`（键码 → 标准键名；Windows 也接受 `ctrl`、`esc`、`enter` 等别名） | `AC_write`、`AC_write_secret`、`AC_hotkey` | Auto Click |
| 屏幕与像素 | `screenshot`、`screen_size`、`get_pixel` | `AC_screenshot` | Screenshot |
| 图像匹配 | `locate_image_center`、`locate_and_click` | `AC_locate_and_click` | Image Detect |
| OCR 文字 | `click_text`、`wait_for_text`、`read_text_in_region`、`ocr_status` | `AC_click_text`、`AC_wait_text`、`AC_ocr_status` | OCR Reader |
| 无障碍树 | `find_accessibility_element`、`click_accessibility_element` | `AC_a11y_find`、`AC_a11y_click` | Accessibility |
| 视觉模型定位 | `locate_by_description`、`click_by_description` | `AC_vlm_locate`、`AC_vlm_click` | VLM |
| 锚点定位 | — | `AC_anchor_click`、`AC_anchor_locate` | — |
| 自愈定位器 | `self_heal_run`、`self_heal_locate`、`self_heal_click` | `AC_self_heal_click` | Self-Healing |
| 自然语言规划 | `plan_actions`、`run_from_description` | `AC_llm_plan` | LLM Planner |
| Computer-use agent | `AgentLoop`、`run_agent` | `AC_run_agent` | Computer Use |
| 录制与回放 | `record`、`stop_record` | `AC_record`、`AC_stop_record` | Record |
| JSON 脚本 | `execute_action`、`execute_files` | 全部 911 个命令 | Script、Script Builder |
| 变量与流程控制 | `execute_action_with_vars` | `AC_set_var`、`AC_loop`、`AC_for_each`、`AC_try`、`AC_retry` | Variables |
| 数据驱动执行 | — | `AC_for_each_row`（CSV／JSON／SQLite／Excel） | Data Sources |
| 断言 | `assert_text`、`assert_image` | `AC_assert_text` 等 21 个 | Assertions |
| 测试套件 | `run_suite` | `AC_run_suite` | Test Suites |
| 调度（间隔 + cron） | `default_scheduler` | — | Scheduler |
| 全局热键 | `default_hotkey_daemon` | — | Hotkeys |
| 事件触发 | `default_trigger_engine` | `AC_email_trigger_add` | Triggers、Webhooks、Email |
| 窗口管理 *(Windows、macOS、X11)* | `list_windows`、`focus_window` | `AC_focus_window`、`AC_snap_window` | Window Manager |
| 剪贴板（文本 + 图片） | `get_clipboard`、`set_clipboard`、`get_clipboard_image`、`set_clipboard_image` | `AC_clipboard_get`、`AC_clipboard_set`、`AC_clipboard_get_image`、`AC_clipboard_set_image` | — |
| 远程桌面 | `RemoteDesktopHost`、`RemoteDesktopViewer` | `AC_start_remote_host`、`AC_remote_connect` | Remote Desktop |
| USB 枚举与直通 | `list_usb_devices`、`enable_usb_passthrough` | `AC_usb_*`（16 个命令） | USB Devices、USB Share |
| 密钥保险库 | `default_secret_manager` | `AC_secret_set` + `${secrets.NAME}` | Secrets |
| 报表（HTML／JSON／XML） | `generate_html_report` | `AC_generate_html_report` | Report |
| 运行历史 | `HistoryStore`、`manual_history_scope` | `AC_history_list`、`AC_history_capture` | Run History、Script Executor、Script Builder |
| 动作日志 | `execute_journal_run`、`inspect_journal` | `AC_journal_capture`、`AC_journal_read` | Run History、Script Builder |
| 指标与追踪 | `default_metric_registry`、`render_metrics_text` | — | — |
| 系统诊断 | `run_diagnostics` | `AC_diagnose` | Diagnostics |
| 测试代码生成 | `generate_code` | — | — |

自愈定位器会在回退或点击前原样传递取消。稽核日志在写入或返回记录前遮蔽本次运行已解析的秘密值；返回的定位结果保留原值，读取时不改写既有日志文件。

实时 image／VLM 自愈现在共用一次延迟逻辑截图及实际裁切原点，两条路径的 `screen_region` 均为 `[左, 上, 右, 下]`。Schema-v2 记录增加 run／step 身份、内容与配置版本、frame hash、策略／截图耗时及实际 backend／model，仍兼容旧记录。未配置验证的点击仅记录已送出或失败，验证保持未知。GUI 提供区域输入与所选记录证据，Script Builder 保留结构化区域 JSON。旧 `healed`／`heal_rate` 统计定位候选，独立的操作指标需要明确验证。

实验性 `self_heal_run(SelfHealRequest(...))` 默认只定位。明确选择 `operation="click"`，再通过 `VerificationRequest(verifier=...)`（Python bool callback）或 `VerificationRequest(description=...)`（已配置的 VLM）于输入送出后验证条件。VLM 验证使用新截取的逻辑图像，可能产生 API 费用。`verified` 分为真、假及未知；`found` 与 `issued` 本身不代表操作通过验证。异常与取消原样传递，不重试点击。`AC_self_heal_run` 和 MCP `ac_self_heal_run` 接受嵌套 `request`；明确验证失败使命令／CLI 失败，或返回含结构化结果的 MCP `isError`。GUI **Self-Healing** 提供选填的操作后条件，Script Builder 可编辑 JSON 请求。独立 VLM 截取也改用相同的内存逻辑原点／Retina 归一化。Framework assertion 会中止定位后备。

已捕获的自愈记录新增可选的 `journal_path`，搭配 run／step ID。实验性 `inspect_heal_source(path, run_id, step_id)`、`AC_self_heal_source` 与 MCP `ac_self_heal_source` 只读取原始步骤经清理的生命周期快照。在 **Self-Healing** 选取记录后，使用 **动作 → 查看原始步骤** 打开后台读取器；切换目标时会等待旧读取停止并保留请求者上下文，关闭则取消待处理工作；Run History 读取器也可选填步骤 ID。先筛选 run／step 再应用输出上限，整份日志仍会验证，进度通知前后重查路径根目录，取消不返回部分结果。旧记录或未经动作日志捕获的操作没有来源链接；查阅不会重放命令。

实验性因果同步提供 `CausalBucket`、`CausalConfigStore`、`SyncActor`、保留冲突的 entry 版本与持久化本机 `SyncOutbox`。独立且经过验证的 `GET/PUT /config/{user_id}/causal` 第三版协议，在保存重发收据的同一个 CAS 事务内验证设备注册、确认、退休／完整同步 epoch 与删除回收。回收后保留永久的最小删除凭据；旧版写入不能覆盖已升级账号。私有 `AC_config_store_get`／`AC_config_store_commit` 与对应 MCP／Builder 命令可读取及提交带显式 `_actor` 的因果 JSON；纯数据合并／peer 与私有 outbox 命令仍可使用。显式的 `CausalSyncClient` 与 `AC_config_causal_fetch`、`AC_config_causal_commit`、`AC_sync_outbox_flush`（含 MCP／Builder）已提供第三版 HTTP 投递：结果不明时重发固定请求，只有明确的过期版本才在有界预算内重新合并。`CausalReceipt` 在 outbox 原子确认原收据与最新完整快照；命令凭据使用实时的 `options.secret_env` 引用。`CausalSyncClient.control` 与私有 `AC_sync_peer_control`／`ac_sync_peer_control`／Builder Data 命令可持久化注册、确认、回收、退休与完整重同步。`SyncControlRequest(operation_id=...)` 让已完成 RPC 的重试保持幂等；完整重同步须明确提供 `discard_pending=True`，收到收据后才原子采用新世代并归档待送旧编辑。本机 `status` 不读取凭据或网络。`python -m examples.causal_peer_control` 提供暂存 loopback 工作流；明确的本机资产版本可通过 `AssetManifest`、`DirectoryAssetTransport`、`build_asset_manifest`、`sync_assets` 与私有 `AC_sync_asset_manifest`／`AC_sync_assets`（MCP／Builder）操作。全部资产先暂存并通过 SHA-256／大小验证，再一次发布完整目录；受损缓存拒绝使用，脚本保持未执行。`python -m examples.sync_assets` 只使用暂存目录。七种实验性 adapter 已将显式选定的脚本、locator、热键、触发器、通讯录、JSON 设置与已保存的原生 GUI 偏好设置保存为持久化因果 profile。`SyncBindings` 将显式指定的秘密与机器值换成具名引用；`materialize_sync_profile` 发布完整且未启用的原生格式版本。私有 `AC_sync_adapter_snapshot`、`AC_sync_adapter_apply`、`AC_sync_adapter_resolve`、`AC_sync_profile_materialize` 与对应 MCP／Builder 命令提供相同流程。`python -m examples.sync_adapters` 仅使用临时文件。私有绝对路径绑定接受高熵目录名称，仍拒绝可识别的凭证格式。原生数值定义会在存储前以分类错误拒绝超出范围的值，包括超大 JSON 整数。`WorkspaceSettingsSyncAdapter` 仅读取原生 GUI INI 的主题、字号、导航显示／宽度，并发布未启用的 `workspace.ini`；显式复制为独立工作文件后，才能交给新 GUI 使用。`python -m examples.sync_workspace` 不导入 Qt。`SyncWorkspace` 已整合明确来源、持久离线捕捉、因果 HTTP、精确冲突审阅与完整重同步来源基线。私有 `AC_sync_workspace`／`ac_sync_workspace`／Builder Data 共用 status／capture／sync／review／resolve／preferences／materialize 与明确 peer 控制，全部需要 DRIVE；网络凭据使用 `options.secret_env`。`python -m examples.sync_workspace_http` 以两组临时来源与 loopback 演示冲突解决、重启及退休编辑不重放。接收数据保持未启用。引用资产传输见下方；明确的原生工作副本加载见下方，`ConfigSyncClient` 保留时间戳合并。参阅[因果／outbox 指南](../../source/Zh/doc/causal_sync/causal_sync_doc.rst)与 `python -m examples.causal_sync`。

延迟创建的 **工作区同步** 页面通过 **Actions** 提供本机状态／采集、网络同步与设备控制、精确因果查看／解决冲突，以及完整未启用发布。粘贴明确的私有工作区配置，凭据只填环境变量名称。同步不会自动应用收到的偏好设置。选择 `workspace`、查看当前版本后，再执行“应用已查看的 GUI 偏好设置”，才会更新当前窗口的主题、字号及导航面板。`SyncWorkspace.preferences(observed=change_ids)` 与现有 AC／MCP／Builder 的 `preferences` 操作，仅在已查看版本完全匹配且无冲突时返回四个标准值；缺少或删除的值采用安全默认值。Worker 保留调用者 context、重新验证 DRIVE 权限，支持取消并在关闭后丢弃旧结果。页面显示修订版、待发送／冲突／引用数与最近成功同步版本；打开页面不会启动连接。

明确的原生加载使用 `load_sync_profile(directory, target_root, expected_digest=...)` 与 `LoadedSyncProfile`，并提供私有 `AC_sync_profile_load`／`ac_sync_profile_load`／Builder Data。以已发布的 `files` 文件夹及精确查看的 manifest 摘要创建全新可编辑工作区，先验证全部 bytes、标准原生文件及封存 heads 一致，再原子发布。加载的热键及每个触发器节点都是停用的原生对象；定位器与通讯录 handle 使用工作副本。类型化资产引用及原生热键／触发器路径按工作根目录解析，脚本文字保留原意，秘密保持 placeholder。在“工作区同步”发布后，文件夹／摘要字段会填入结果；选择工作副本存放文件夹，再执行“加载已查看的原生 profile”。其他明确 Actions 可检查所选原生类别、在 Builder 打开已加载脚本快照，或应用其偏好快照。每次操作都重新验证当前调用者与捕获所有者的权限；打开脚本后仍须明确执行 Run；Builder 将导入的命令名称与位置参数显示为字面文字。`python -m examples.sync_profile_load` 使用七种临时来源与真实 PNG，不调用网络或设备。

文件夹镜像改用 SHA-256 内容比对，不再依赖修改时间递增：只改时间不重发，时间相同或较旧的内容修改仍会发送。FolderSyncEngine 重启时保留待发与离线修改，逐文件检查停止请求，并持续拥有尚未结束的发送工作。传输所有者可在发布文件后明确调用 record_received(path)，避免回发收到的内容。原生 GUI 的固定内容回执处理见下文。

文件发送现在会等待每个 DataChannel callback，将缓冲数据限制在 1 MiB，并将通道失败报告给调用方。可选的 `cancelled` 判断会停止排队写入；声明的字节数可检测来源截短或增长。原生文件夹任务绑定授权、引擎、viewer 与 peer connection，所有权变化时停止。收件箱下载移至事件循环之外，通过每个通道最多 32 个请求的队列依次发送。默认手动模式接受数据不代表远端发布完成；确认模式见下文。GUI 重连交接见下文。

原生文件接收器现在会在关闭、文件／控制通道关闭、连接进入终止状态、更换通道或撤销文件权限时清除未完成内容。已关闭的接收器拒绝延迟数据；具体 peer／通道与认证检查会保护替换后的传输，也会拒绝 viewer 在认证前接收文件。状态清理先于用户 callback，避免旧失败影响 callback 建立的新连接。文件／审计／状态 callback 保留原始取消及强制中断对象。清理会尝试关闭文件及删除暂存文件，文件系统失败写入日志。现有 Remote Desktop 控件自动使用此生命周期；已完成的目标与原有线上格式仍可使用。

本机 `FileReceiveReceipt(path, sha256, size)` 现在会在原子发布后固定原始接收内容。`FileTransferReceiver.handle_message(on_receipt=...)` 与原生 host／viewer 的 `set_file_receipt_callback()` 提供回执，不必重读已发布文件。`FolderSyncEngine.record_receipt()` 避免回发并保留后续本机修改；现有 `record_received(path)` 则明确快照当前内容。GUI 文件夹开关绑定接收回执的引擎及 viewer，并在访问监控目录前重新验证原始授权。相对收件箱／监控路径绑定创建时的工作目录，现有路径通知使用绝对路径。这些本机回执供下文的原生确认模式使用；GUI 重连交接见下文。

原生 `FileTransferSender.send`、viewer 的 `send_file` 与 host 的 `push_file` 现在接受仅限关键字的 `require_commit=True`。确认模式会先探测已认证的原生对端，再读取来源元数据／内容；通过第二版 begin／end 元数据发送，并在原子发布后核对传输 ID、不可预测的结束 nonce、SHA-256 及字节数。相对来源路径会在交换前固定。每个文件都重新确认支持与权限，等待有时限；取消、通道／事件循环替换或撤销权限都保留失败状态。GUI 文件夹发送一律要求此模式，因此仅接受但丢失的数据不会推进投递状态；不确定的发送会由同一引擎重试。手动发送仍默认使用原有线上格式。GUI 文件夹投递要求两端都支持确认传输；不支持时会在发送文件内容前失败。GUI 明确重连／恢复见下文。

GUI 重连时会为每个面板保留一份内存中的文件夹基准。重新连接后再按开始同步：相同的已认证 host 指纹、绝对监控路径与本机用户，会通过新授权的 sender 接续失败／离线修改。缺少或更换 host 指纹、路径或用户时建立新基准；旧工作仍在运行时拒绝交接，待它退出后才能重试。明确关闭文件夹同步会重置基准；停止／重连 viewer 则保留，关闭应用后清除。指纹沿用既有已认证 host 元数据的信任模型，没有新增密码学身份保证。SDK 可先停止 FolderSyncEngine，待工作确实退出后导出 checkpoint()，将不可变的 FolderSyncCheckpoint 传给路径／递归设置相同且 sender 已明确授权的新引擎。基准包含初始忽略文件与收到的内容，并非远端确认清单。

TCP／WebSocket 剪贴板传输沿用明确的 SDK 调用与 GUI 推送剪贴板按钮。收到的文字／图片不会自动传回或广播；用户仍可明确重复发送相同内容。Viewer／host 在读到缓冲消息后，会重新检查原始连接、认证及完整控制权限，再应用剪贴板数据。Viewer 会在编码前固定原通道，拒绝改发至替换后的连接。GUI 排队中的传输保留具体 viewer 与连接发起用户，写入本机剪贴板、明确读取及发送前都会重新检查权限与所有权。过期或撤销的工作会被忽略或报告权限错误；普通 provider／callback 错误仍受控，原始取消与强制中断对象继续传播。文字／图片 JSON 格式及既有 API 不变。Callback 注册仅以弱引用绑定一次原始 viewer，避免断线 viewer 自己保留自己及 Qt 面板直到循环垃圾回收；实际排队数据仍保留原始 peer 与权限，直到处理或丢弃。受控本机协议、loopback 与 offscreen 测试替换原生剪贴板 provider；真机与付费 API 验收仍暂缓。

实验性引用资产使用 `SyncAssetBlob`、`SyncAssetReference`、`SyncAssetStore` 与 `SyncAssetHTTPClient`。明确的 `SyncBindings.assets` 别名将选定文件封存为不可变 SHA-256 引用；只改资产也会建立新的因果版本。`SyncWorkspace` 在准备新定义请求前上传已验证分块，支持中断续传，并在完整且未启用的发布前下载引用内容。现有私有 AC／MCP／Builder 工作区／profile 命令共用这些字段。`asset_cache_path` 选择 client cache；signaling 的 `--asset-store`／`AUTOCONTROL_SYNC_ASSET_STORE` 选择独立 server 数据库。带验证的第一版资产路由使用 256-KiB 分块、每文件 64 MiB 上限，每账户默认限制 256 MiB、8,192 块与 4,096 条 blob 收据。超过配额会明确失败；不可变历史不自动回收。原生输出路径相对于 generation 根目录。`python -m examples.sync_referenced_assets` 经临时 loopback HTTP 传送真实 PNG 与脚本，不执行脚本或改当前工作区。

实验性持久化配置使用 `ConfigStore.commit(..., base_revision=..., operation_id=...)` 与第二版 signaling PUT envelope。SQLite 事务使 bucket 与重发收据在重启后保留；过期版本或 ID 改配其他内容会冲突。`ConfigSyncClient` 默认条件写入；旧版盲写须在 client／server 明确开启。`--config-store` 选择延迟打开的数据库。私有 `AC_config_store_get`／`AC_config_store_commit` 与对应 MCP 工具共用 Script Builder 的显式 Data 命令。只存储数据，不执行脚本或启用触发器；因果合并与离线 outbox 单独交付。参阅[持久化配置指南](../../source/Zh/doc/config_store/config_store_doc.rst)与 `python -m examples.config_store`。

实验性日志产码候选支持 `generate_candidate_from_log(path, run_id=...)`、`AC_generate_candidate_from_log` 与 MCP `ac_generate_candidate_from_log`。它会整合开始／完成快照，保留已记录的控制来源与重试证据，并将不完整重建标为已观察路径。失败／未完成调用、未知命令及遮罩输入均列为排除项，不编造并行顺序。Python／pytest／Robot 产物通过静态、命令及不发送输入的干跑检查。`codegen --from-log run.jsonl --run-id selected` 输出 JSON 审阅包；`-o review.zip` 或 `write_candidate_archive` 可将代码、动作与来源信息一起原子导出。Recording Editor 与 Script Builder 的 **动作 → 审阅日志候选脚本** 提供代码／差异／来源／警告；Builder 导入为独立操作，拒绝覆盖审阅期间的编辑变更。生成与导入均不执行候选。参阅[候选指南](../../source/Zh/doc/journal_candidates/journal_candidates_doc.rst)与 `python -m examples.journal_candidates`。

实验性候选模板版本提供 `create_template_candidate`、`preview_template_candidate`、`verify_template_candidate`、`accept_template_candidate`、`revert_template_candidate`，以及对应 `AC_template_candidate_*`／`ac_template_candidate_*` 操作。新的不可变 JSON 版本包保存原始字节及按目标 PNG／JPEG／BMP 格式编码的候选；预览返回有界缩略图。验证在本机数据集比较两个固定版本；接受须有已标注命中、预期 miss、全部已标注案例正确，并提供已预览版本的 SHA-256。接受时重新验证数据集，只原子替换仍匹配的原始内容；恢复精确还原原始字节，拒绝覆盖后续修改。未知样本与原生操作结果分别呈现。验证使用记录的阈值；启用图像不修改脚本阈值。**Self-Healing → 候选模板** 提供五个动作、后台任务、取消与 JSON 证据。运行 `python -m examples.template_candidates` 可执行只使用临时文件的示例。

实验性固定图像比较支持 `evaluate_locators`、`evaluate_healing_manifest`、`AC_self_heal_evaluate`、MCP `ac_self_heal_evaluate` 与 **Self-Healing → 版本比较**。报告分别呈现已标注正确率、误判、未知与已验证恢复，包含 p50／p95 及来源，可由 `write_healing_report` 或 GUI 动作导出 JSON／HTML。本机数据集入口不会截图、点击或自行选择网络 backend。参阅[数据集、统计母体与限制](../../../benchmarks/self_healing/README.md)。

除了这张表，`utils/` 下还有 311 个无头包，覆盖断言、韧性、数据质量、i18n 审计、脱敏、
治理、可观测性等等。完整的逐模块地图在 **[architecture_explore.md](../../../architecture_explore.md)**。

---

实验性的结构化日志已从 `je_auto_control` 导出（也可通过 `utils.action_journal` 使用）：`journal_scope` 记录现有 executor 调用，`execute_action_with_journal` 隔离一次执行。本机 loop／parallel／DAG 步骤保留 parent ID，并区分失败、取消与 dry-run。现有 history 拥有者会自动链接显式捕获，包括本机 parallel／DAG worker 开启的 journal；`HistoryStore.journals_for_run` 可查询非拥有式链接，清理 history 不会删除日志文件。CLI 支持 `run script.json --journal run.jsonl [--journal-run-id ID]` 与 `journal run.jsonl [--run-id ID] [--limit 100]`。查询会按追加顺序显示遮罩后的生命周期快照，默认最多 100 条，上限 10,000 条。`AC_journal_capture` 接受命名参数，在拥有者 executor 上执行嵌套 `body`，保留原变量作用域；`AC_journal_read` 与 CLI、公开的 `inspect_journal` 共用遮罩后的有界查询。两个命令都可在 Script Builder 编辑。捕获会在 history 链接、创建文件及执行动作前拒绝含有当次执行已知密钥值的标识符或目标路径。MCP 的 `ac_journal_capture` 与 `ac_journal_read` 提供结构化结果、进度与协作式取消。捕获的日志根目录限制与 observer 会保留到嵌套捕获及本机 workers；查询可在逐条验证时取消。Python 可通过 `JournalRunOptions` 与 `execute_journal_run` 使用相同控制。

手动执行可通过 `manual_history_scope`、`AC_history_capture`、CLI 的 `run --history [--history-db PATH]`，或 Script Executor／Script Builder 的 **记录到运行历史** 选择记录。GUI 的可选日志路径也能独立使用；GUI／CLI 保留原有结果 JSON 与变量作用域，命令则返回 `history_id`、`record`、`failed_actions`。已有与嵌套捕获都会关联到新的手动历史记录。CLI 预览使用 `cli.preview` 标签，普通执行使用 `cli.run`。

Run History 提供只读日志查看。使用 **操作 → 使用所选执行的日志** 选择来源关联，或用 **选择日志** 指定外部文件；设置执行 ID 与快照上限后，使用 **读取日志**。开始／完成快照保持分离，选中后会显示完整的遮罩数据。**取消读取日志** 与关闭视图会在逐条边界请求取消；文件解析在后台 worker 执行，仅选择关联不会打开文件。

`${secrets.NAME}` 解析后的值会在 executor 执行期间的应用程序诊断中遮罩，包括嵌套动作及本机 parallel／DAG。CLI／REST／MCP 请求与排程、trigger、hotkey、email 执行会将遮罩保留到错误处理及 audit／history 写入完成；报表记录保存遮罩后的快照。DAG 会将拥有者的遮罩保留到 node 诊断完成，包括独立调用与自定义 local runner。watchdog、observer 与 callback executor 会将遮罩保留到最后的错误处理；独立规则彼此隔离。CLI stderr 会遮罩，API 结果、抛出的异常与 CLI 结果数据保留原始值。遮罩于拥有者的请求或执行结束时清除。中止的 history 记为 `error`，journal 步骤保持 `cancelled`，不再获取错误截图。取消会穿过非严格执行、恢复／重试、回调与本机 worker；history 结算失败也不会取代原始硬中止信号。

## 命令行界面

每次 `je_auto_control run`（包括 `--dry-run` 与未带 `--var`）使用独立变量作用域。顶层 `run_from_description` 与 `StateMachine.run()` 也会隔离变量，同一次执行内的动作与状态仍可共享；嵌套调用沿用已有的执行作用域。自行创建的 `Executor()` 保留自己的变量。

```bash
je_auto_control run script.json [--var name=value] [--dry-run] [--allow-package NAME]
je_auto_control validate script.json          # 别名：lint
je_auto_control fmt script.json [--check]
je_auto_control list-commands [--filter mouse] [--json]
je_auto_control record out.json [--duration 5]
je_auto_control codegen script.json --target pytest -o test_flow.py
je_auto_control failure-bundle failure.zip --error "login timed out"
je_auto_control list-jobs
je_auto_control start-server --port 9938      # TCP socket 服务器
je_auto_control start-rest   --port 9939      # REST API
je_auto_control version
```

`--var name=value` 会尽量以 JSON 解析（`count=10` 会变成整数），否则视为字符串。
`run` 只要有任何动作失败就以 1 退出（仍会跑完整份脚本），CI 步骤会随之失败。旧版 `python -m je_auto_control -e file.json` 入口仍然可用，它的 `-e`、`-d` 与 `--execute_str` 标志也同样在有动作失败时以 1 退出。由 [TestPioneer](https://github.com/Integration-Automation/TestPioneer) 启动时（它会设置 `TEST_PIONEER_ARTIFACT_DIR`），以相对名称要求的 HTML、JSON、XML 报告会写到该目录底下。

---

Windows 焦点事件等待支持已绑定的协作取消 token 与 executor stop token，退出等待时解除事件订阅；真实 COM 验收仍待执行。

普通 GUI 标签页任务会把取消信号传给支持协作取消的核心操作。停止、超时或关闭所属窗口会取消操作；未检查取消信号的后端，其迟到结果会被丢弃。脚本任务仍使用 executor 的停止与清理保护规则。
