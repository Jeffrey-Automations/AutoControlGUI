# Completion evidence and handoffs

[README](../../../README/README_zh-CN.md) · [Documentation](../../README.md)

## Local DAG 完成证据的明确移交

其他 caller 持有的既有恢复子任务，可通过明确且可撤销的移交，向原 local DAG 提供完成证据。
以 `manage_agent_recovery` 的 `review_handoff` 提供最终 `task_id`、`batch_id`、`node_id`，
有权管理者再用相同 ID、将返回的 `handoff_review` 填入 `review`，并附非空 `note` 执行
`create_handoff`。接收者由服务依真实原始 admission 决定。在 `review_continuation` 的 successor
决策中，除 `node_id`、`action`、`task_id` 外明列 `handoff_id`，再审核并批准整份 continuation。
最多支持十六层真实恢复链，包含经私有 admission 的永久只读最终验证者；一般任务归属保持原样。

`get_handoff`／`revoke_handoff` 使用 `handoff_id`；`list_handoffs` 使用 `batch_id`、`node_id`。
创建与采纳时重查实际 owner、创建审核者、签发 session 的来源根限制、当前接收端限制、固定 scope、
效果快照、独立完成及资源退役。批准、开始及后续依赖验证都重查同意；撤销或证据丢失会阻止采纳。
期限不超过最早终止见证既有的三十天保留期限。公开响应只含有限 ID、摘要与状态，不含私有参数、
capture 或 principal 数据库路径；不授予一般任务读取／输入权、不转移归属或重放。
跨主机及非 DAG 的移交契约仍列于 `Progress.md`。

Agent Tasks 的成果移交页提供操作菜单与 JSON 编辑器；Actions 只准备审核、创建、撤销请求，
不自动派发。五个可编辑的 `agent_handoff_*.json` 示例涵盖 review/create/get/list/revoke。
Python、AC、CLI、具名 MCP、REST、Builder 共用这些 recovery 操作。本次证据涵盖契约及自有文件
流程；暂缓的原生桌面、浏览器、设备及二十四小时验收仍须各自提供证据。

## 明确续授权只读完成验证

原来源的 origin 引用过期或不可用时，明确调用
`manage_agent_recovery("review_completion_authorization", {"task_id": "<source-id>"})`。
审核服务产生的 `verification_spec`、保留／替换／当前 origin 限制，再以相同 `task_id`、返回的
`snapshot`、`authorization_review` 及非空 `note` 调用 `create_authorized_completion`。
可选 `owner_policy="source_owner"` 在创建时另须返回的 `ownership_review`；不能自行提供新验证
规范。仍有效的旧限制保留，新根目录与原上限、前一读取者上限及当前 session 取交集。
已重新授权的读取者不能改用一般完成审核来移除这些限制。

子任务永久只读，依真实已确认的原效果独立检查当前条件，不输入、不重放、不恢复 capture，
也不修改旧见证。来源／效果快照、实际 owner／reviewer 及原 DAG admission 都会重查。
创建任务与最终完成各自在自己的 SQLite writer 内写入后重验，变化时共同回滚。
最多支持十六层真实恢复链；已退役且成功的读取者可再次明确续授权，但保留前次较窄上限及所有仍有效
的继承限制。来源／效果证据已改变时仍拒绝，不能借 scope 续授权默默修复旧证据。

历史 `get` 保留 succeeded 状态；新授权失效时，当前 `completion_contract` 为零、
`completion_authorization` 为 unavailable，DAG 采纳与后续依赖验证会拒绝这份证据。
新的只读标记损坏／丢失时，在 helper 启动前拒绝。以 `completion_task_id` 录制时沿用原语义动作及
已审核的限缩 scope，但草稿仍须自己的新验证试跑。此流程不发布过期候选，也不续授权已发布技能；
既有技能重新授权流程保持分开。

Python、AC、CLI、具名 MCP、REST、Builder 共用两个操作；Recovery 页的两个明确 Actions
沿用所选任务、owner policy 与请求编辑器。可编辑示例为 `agent_completion_authorization_review.json`
与 `agent_completion_authorization_create.json`。remote 只读来源、跨主机移交、
实际应用状态重建，以及暂缓的原生／设备／浏览器／二十四小时验收仍列于 `Progress.md`。

## 明确移交已续授权读取者的完成证据

现有 `review_handoff`／`create_handoff` 现在可明确将已重新授权、永久只读读取者的完成
证据交给实际原 local DAG。指定该读取者的 task ID 与原 batch／node，由服务推导证明；不能自行提供
policy、所有者覆盖或授权 bundle。一般成果移交沿用现有规则。

预览的 `evidence.completion_authorization` 显示完成任务／审核、固定的审核摘要、根目录数量及
替换／保留／当前 origin ID，不含私人 principal 路径、动作参数或 capture。创建时以最上层返回的 `handoff_review`
作为请求的 `review`，并提供非空 `note`。每个真实任务都保留已审核的上限与所有仍有效的历史限制；不可用的
引用须明确审核替换，发出移交时额外的 session 限制也持续有效。移交沿用读取者已实际验证的相同
根目录；交集改变时须重新审核及执行只读完成验证，接收者的 session／profile 限制也会持续应用。

最多十六层真实恢复链可混合先前已审核的可执行子任务及私人读取者。成功的中间读取者必须具备实际
私人历史 scope 与退役证明，一般已成功来源没有这个例外。发出或采纳移交时不启动 helper、不重放
输入；旧来源状态、见证、收据及所有任务所有者维持原样。原所有者只取得有限完成投影，不能因此
一般读取其他 caller 的任务。撤销或授权失效会阻止采纳及后续依赖验证。

原 accepted-request hash、原始提交见证、私人 admission、graph、owner／reviewer、整条来源／子任务
快照与最后读取者的续授权都固定在证明内。读取与写入后重验使用同一个 SQLite writer，包含尚未提交
的变更；发现变动即回滚任务／移交创建。继承的 `dag_batch` 选项不等于 admission，必须沿有界真实
恢复链找到原请求及实际授权身份，不补造 admission。旧的一般完成 binding hash 保持兼容；各历史
任务各自审核限制，不能通过合并历史绕过正常十六个有效 origin 上限或原根目录边界。

相同有效重试沿用原 note 与 ID，已撤销 ID 不会重新启用；重启与采纳保留最早终止见证的三十日期限。
origin 失效后仍可查 get／list 历史与 revoke，但历史不代表可用完成证据或输入授权。Python、AC、
CLI、具名 MCP、REST、Builder 共用五个现有操作，Handoffs Actions 与 JSON 编辑器／结果区可显示
明确续授权审核，不自动派发同意。跨主机移交、remote 读取者、实际应用／设备
来源及暂缓的原生／浏览器／真机／二十四小时验收仍列于 `Progress.md`。

## 明确移交任务来源的完成证据

现有五个移交操作也接受真实非 DAG 来源任务：

- `review_handoff` 提供 `source_task` 与实际最后证据的 `task_id`。
- `create_handoff` 再以最上层返回的 `handoff_review` 作为 `review`，并填写非空 `note`。
- `list_handoffs` 提供 `source_task`；`get_handoff`／`revoke_handoff` 仍使用 `handoff_id`。

任务来源与 DAG batch／node 字段互斥，服务依实际保存的 grant 判断存储类别。真实 DAG 祖先仍须走
原 batch／node 路径，不能借由已移除 `dag_batch` 的只读读取者绕过，也不补造 DAG 节点或 admission。
一般任务不必虚构提交见证或 idempotency key；实际存在的原请求须固定并在同一 SQLite writer 重验。

现有技能操作明确选择 `handoff_id`。`record` 以 `completion_task_id` 采纳独立读取者，建立的 draft
仍须自己的新验证 trial；`accept` 使用完成读取者时，仍保留原 candidate 的真正验证任务。
`review_execution` 与对应 `accept` 可选实际 `execution_task_id`；最后证据是独立读取者时，再提供
`completion_task_id`。服务核对原本完整语义动作计划、真实执行 ID 及独立完成条件，不能把读取者
当执行任务或替代验证 trial。

grant 只提供私人有限证据视图，原所有者、来源状态与收据维持原样，一般 get／list／observe／act／
resume 权限不扩大。发出或采纳时不启动 helper、不重放输入。真实快照、可选原请求、实际 owner／
reviewer、退役输入与有效历史 origin 均持续核对；新录制的 draft 保留发出与接收 session 上限。
失效限制须经真实私人完成续授权，不能靠相同 hash 或自填 scope flag 替代；只读采纳也不会续授权
已发布技能原本的输入权限。

来源祖先与后续移交链合计最多十六条真实恢复连接。期限沿用最早终止证据的三十日，改锚定较新的
读取者不会延长旧祖先。DAG 与任务 grant 的 INSERT 后及相同重试都重验撤销墓碑；来源／请求／角色／
origin／撤销变动会回滚 grant、draft 或发布。已撤销 ID 不重启，origin 失效后的 get／list／revoke
历史只显示有限 ID／hash，不代表持续有效的完成证据或输入授权。

Handoffs 页可明确选原本机 DAG 或原任务来准备 JSON；三个技能 Actions 准备带 grant 占位符的录制、
发布与执行审核，不自动同意或发布。Python、AC、CLI、具名 REST／MCP 与 Builder 共用相同操作及
真实 caller。`examples/` 提供 `agent_task_handoff_review.json`、`agent_task_handoff_create.json`、
`agent_skill_recording_handoff.json`、`agent_skill_completion_handoff.json`、
`agent_skill_execution_handoff_review.json` 与 `agent_skill_execution_handoff_accept.json`。

跨主机移交、remote 读取者、实际应用／设备来源、暂缓的原生与二十四小时验收，以及未解的
HTTP409／bootstrap 问题仍列于 `Progress.md`。

wheel 与源码分发包包含 REST Dashboard 和 Swagger 的 HTML、CSS、JavaScript 资源。
安装后的套件沿用相同的本机 REST 路由与授权规则；提供静态页面不授予任务或桌面输入权限。
