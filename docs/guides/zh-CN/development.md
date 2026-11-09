# Development and resources

[README](../../../README/README_zh-CN.md) · [Documentation](../../README.md)

## 文档与示例

| 资源 | 内容 |
|---|---|
| [`examples/`](../../../examples) | 45 个自包含脚本：截图点击、OCR、调度器、远程桌面、agent loop、可观测性、录制、变量、热键、触发器、报表、MCP、REST、密钥、插件、computer use、Wayland、跨主机 DAG、chat-ops、pytest/BDD、锚点定位、动作日志。 |
| [Read the Docs](https://autocontrol.readthedocs.io/en/latest/) | 完整 API 参考，含英文与中文。 |
| [architecture_explore.md](../../../architecture_explore.md) | 逐层记录每个模块的职责。 |
| [docs/CAPABILITY_MATRIX.md](../../CAPABILITY_MATRIX.md) | 能力 × 平台对照矩阵。 |
| [docs/API_LIFECYCLE.md](../../API_LIFECYCLE.md) | 稳定 API 与弃用策略。 |
| [docs/updates/](../../updates/README.md) | 更新记录：各版本说明与完成的工作，每月一个文件（原 `WHATS_NEW.md`）。 |
| [CHANGELOG.md](../../../CHANGELOG.md) | 兼容性变更记录。 |
| [SECURITY.md](../../../SECURITY.md) | 安全策略与报告方式。 |

---

## 开发

```bash
git clone https://github.com/Integration-Automation/AutoControlGUI.git
cd AutoControl
pip install -r dev_requirements.txt
uv sync                 # 或：以已提交的 uv.lock 做可重现安装
```

```bash
python -m pytest test/unit_test/headless      # 无头单元测试
python -m pytest test/integrated_test/        # 跨模块流程测试

ruff check je_auto_control/
pylint je_auto_control/
bandit -c pyproject.toml -r je_auto_control/

python test/verify/typing_contract_verify.py            # mypy，整个包，三个目标平台
python test/verify/typing_contract_verify.py --extras   # 同一项检查，改用真正的 PySide6／aiortc 类型
python -m sphinx -b html -W docs/source docs/_build/html  # 文档，警告视为错误
```

dev／main 的无头任务会保留七天的 `native-<os>-<python>` artifact，内含合并进程输出、
包／运行环境版本与退出码。Linux 经 GDB 保留各线程原生堆栈；其他平台保留 Python
faulthandler 输出，测试失败仍会使任务失败。可在 repo 执行单一命令
`python scripts/ci_native_diagnostics.py --artifact-dir test-artifacts -- python -m pytest -v --tb=short --timeout=120`；
Linux 安装 GDB 后，可在 `--` 前加入 `--native`。
含空格／引号的 argv 仍是原始参数，已处理的 `SIGINT` 会传给子进程。
Linux 先在完整套件的 debugger 外验证诊断工具；前置检查记录也收在同一 artifact。

选定的 dev 推送由 `.github/workflows/ei-lifecycle.yml` 在隔离 libei／libeis
容器执行，将版本及两份原生记录保留于 `ei-lifecycle-<run>-<attempt>` artifact 十四天。
半开与 live 释放子进程分别有十／六十秒时限与 faulthandler；其他子进程失败使 CI 失败，
释放成功必须有 begin／end 标记。半开探测另须有相同整数 fd 数量，live 清理先释放拥有的
device refs。run 39507190704 在 libei／libeis 1.3.901-1 通过 9/9 与 20/20 检查，
包含坐标越界拒绝且不转用 CLI。半开 `ei_unref` 仍会 SIGSEGV，因此保留 runtime 保护，
helper 隔离仍待完成。设备暂停与序号回读仍未验证；受控 socket peer 不代表合成器授权、
真机或多屏幕验收。

欢迎贡献——请见 [CONTRIBUTING.md](../../../CONTRIBUTING.md) 与
[CODE_OF_CONDUCT.md](../../../CODE_OF_CONDUCT.md)。CI 会强制两条规则：`import je_auto_control`
绝不能加载 PySide6；每个功能都必须同时具备无头 API 与 GUI 界面。

---

## 许可

[MIT License](../../../LICENSE) © JE-Chen。
内含与可选第三方组件的许可请见 [Third_Party_License.md](../../../Third_Party_License.md)。

- **主页**：https://github.com/Integration-Automation/AutoControlGUI
- **PyPI**：https://pypi.org/project/je_auto_control/
- **文档**：https://autocontrol.readthedocs.io/en/latest/

旧式 MCP 动作包装、并行分支及本机 DAG worker 也会保留相同的来源限制。

受管指针动作可指定该次观察的元素索引或缩略图坐标，由主机检查当前画面并换算原生坐标，包括缩放与负屏幕原点。收据保存几何依据，不保存图像字节。`AgentObservationStale` 表示分派前已拒绝动作；本机 agent 只在 adapter 确认没有按住或待处理输入时，在重试预算内重新观察。

紧急停止先返回带有 metadata.details_deferred 的精简状态，完整产物链接可由单个任务查询。

托管鼠标按下前会规范按钮所有权并确认实际光标位置。Windows 指针检查会拒绝其他窗口遮挡。影像仅将指定窗口绘制到清空的私有 GDI 内存，几何变化会拒绝该画面；绘制或读取失败也会释放资源。不改用桌面捕获。这些路径已用模拟原生 API 测试，实际原生验收仍未验证。

Agent 任务界面将任务范围、工作流程设置、触发器、技能及恢复分页。观察页显示只读元素和已验证、严格遮罩的 JPEG，每个逻辑画面像素对应一个呈现像素。选择元素或影像坐标只会编辑该次观察的动作请求；由 Actions 的「执行观察动作」通过共用任务 API 发送。切换任务会清除预览，迟到回复不能替换当前任务；新画面必须重新选择，旧索引不能直接复用。关闭界面仅解除请求订阅。

托管工作流程可用 workflow_wait／AC_workflow_wait 等待指定控件的精确值或状态，只重复读取；可取消且受动作预算限制，默认五秒、上限六十秒，不重发写入或提交。固定技能每一步都验证已有收据与固定顺序，恢复也不能跳过读回失败的步骤；模型自主循环仍保留停滞检测。新表单／跨应用模板会在提交前拒绝原本已匹配的确认值，提交后等待新的状态转换。批次可设置 new_record_selector 逐条重置；确认仅证明配置的界面转换，有交易标识值时应使用它。归档模板完成时会重读指定清单及文件摘要，清单上限一 MB，总验证数据上限六十四 MiB。

AgentHumanReview 表示未保存内容或未知对话框需人工审核；包括外部观察请求都会记录 waiting_user 并释放输入控制权，明确恢复后仍会重新检查。Windows 依据原生对话框／禁用所有者及英中日已知未保存文字判断。Workspace 也会拒绝标题首尾带星号的文档，并可在窗口设置中加入 unsaved_selector 与 unsaved_value，在改变排列前检查应用特有指示；不声称能推断所有程序的未保存状态。标准文件对话框沿用 AC_handle_file_dialog 执行器，托管 driver 只接受唯一精确标题、相同 PID、已确认前景，以及授权根目录内的绝对路径。UIA 控件须属于实际指定的根窗口，同 PID 的其他窗口也会拒绝。模拟原生与本机 HTTP 测试已有覆盖，实际平台验收仍未验证。

主机目标通过 AgentTargetProfile 与 manage_agent_target（AC_agent_target，register/get/disable/enable/probe）设置。名称及设置固定不可替换，目前提供 desktop／files／browser adapter，未实现类型会被拒绝；浏览器可使用主机审阅的 helper_python。任务固定主机设置摘要，不能扩大工具、应用、根目录或网络来源。启停状态会跨重启保存并在分派时检查；禁用会请求暂停及清理，重新启用仍须明确恢复任务。list_agent_targets／AC_agent_target_list／CLI agent-task targets 仅提供被动信息，readiness=not_probed、native_evidence=not_recorded；完整设置需要 manage_hosts。CLI agent-task target 及 GUI「主机目标」页使用同一服务。匿名有效 MCP 工具 session 的直接及旧式包装调用都以 operator 权限执行；MCP 主机管理需要已验证的管理员，可信任的直接 Python 调用维持原行为。浏览器自动化统一由 WebRunner（je_web_runner）提供，本机开发来源为 D:/Codes/WebRunner；browser profile 使用受管 je_web_runner SDK 契约，依赖诊断不代表原生可用。

既有浏览器自动化（包括 open_path(URL) 与 AC_open_path）统一交由 WebRunner，Python 包名为 je_web_runner。URL 计划的 backend 现为 je_web_runner，原本比较 webbrowser 描述值的调用端需改用新值；函数接口与本机文件打开维持兼容。实际 URL 执行需要配置的 WebRunner 项目，缺少时传出 WebRunnerBridgeError，不改用 OS 浏览器。本机开发来源为 D:/Codes/WebRunner；纯计划及注入 opener 测试不需要该包。协议支持由 WebRunner 与所选浏览器决定。既有浏览器 GUI／MCP／AC 及录制的 WR_* 动作都使用同一桥接。
