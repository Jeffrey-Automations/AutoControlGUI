# Implementation notes migrated from README

Historical implementation notes preserved during the README reorganization on 2026-11-10. These entries describe different development stages and are not a current acceptance checklist. See [Progress](../../../Progress.md) and [updates](../../updates/README.md) for tracked status.


成果移交管理已共用 `manage_agent_transfer(operation, request)`、`AC_agent_transfer`、
`ac_agent_transfer`、已授权的 `POST /agent/transfer` 与 Script Builder metadata。CLI 使用
`agent-task transfer --operation review_export --request request.json`。审阅返回批准 token；
创建须提供该 token、原请求 key 与明确 note。导出／导入管理可指定已登记主机；
可携证据管理也可指定已登记主机，由来源核实私有权限。传输页提供四语 Actions、可编辑 JSON 与服务回复；
审阅不自动批准，批准模板保留原主机、token 与 key 并留空备注。选项变更或关闭页面后，
旧回复不覆盖画面，已接受的导入仍由服务持有。远端批准先保存明确同意，失联或协调端重启后以原键重发，保持同一授权。
被动诊断仅列出本机契约，不代表即时授权或远程／原生能力已验证。只读完成证据在创建与使用时重新核实原私有同意，不恢复原输入权限。
实现验证记录见 docs/updates/README.md；其余交付与验收见 Progress.md。
examples/agent_transfer_export_review.json、agent_transfer_import_review.json 与
agent_transfer_evidence_review.json 提供可编辑请求，并各有独立的 create 模板。

实验性的来源主机技能操作，可通过现有 `handoff_id` 明确选择可携授权与完成／执行任务。
来源在技能事务内重新核对实际同意、接收者与私有证据，候选／发布写入后再次核对。
保留原始动作、候选自己的验证试跑与明确版本批准；新的技能试跑建立服务生成的全新请求 key，
不为旧有未带 key 的试跑补造记录。此流程不将外部动作或策略移交协调端；
技能证据保留来源主机的原动作／试跑／版本；其余跨主机验收与交付见 Progress.md。
选择移交证据的技能操作，全程保留 runtime 所有权，操作结束后才释放。

目的端导入目前仍为实验功能。明确启动的服务可通过 runtime 移交控制器与经验证的
`/agent/transfer` 接受 `review_import`／`create_import`／`get_import`／`run_import`／
`cancel_import`／`list_imports`。协调端可通过自己的不透明同意 token 路由这些有限操作；
目的端使用自己的来源登记与账号，不转发协调端 principal／origin 或来源凭据。
批准意图在派送前提交；回复丢失后的精确重试仍对应同一笔导入。
启动时接回已批准且尚未领取的工作；未结算 claim 会转为待审阅。明确的 `run_import`
以新队列代次重新核对原收件者、profile、实时 origin 与来源 grant，可重用已验证私有分块，
或只读核对既有完整目录与哈希，不重新下载／发布。续行时新增的 origin 限制仍持续生效。
已明确排入队列且未领取的只读核对可跨再次重启；采认前重验当前字节、profile 与保留的 origin。
导入收据确认完成前，目的端会在最后一次来源回复后重新核对完整文件清单与内容摘要。
文件遭改写、丢失或增加未列入清单的文件时，导入保留 requires_review，
保留用户修改与原发布成果供审阅。
目录身份、字节或权限变更不能确认发布。取消会使生产者失效；尚未完成收据确认的
发布保留 requires_review，已确认发布的文件保留为用户成果。
取消或过期的私有分块账号须确认生产者退出才清理；失败时保留配额，成功重试后才释放。
收据维持原本固定期限。
暂存目录与预先创建的文件会在复制字节前记录文件系统身份。生产者退出后，
过期清理可于重启后重试；遇到替换或无关对象时保留配额待审阅，不递归删除。
来源维护会清理过期或已撤销的私有导出账号，包含重启或授权者移除后；失败时保留配额。
来源或目的端清理完成前持续保有 runtime 所有权；无待清理数据时不获取 runtime 写入锁。
创建／续行回复会在唤醒新投递前读取已提交的收据；后续以 get_import 查询当前进度，避免回复被新 writer 阻塞。
后续维护会修剪已清理、撤销且过期的来源元数据以回收记录配额，保留同意／撤销凭据与其他记录类别。
冷启动维护以只读探测发现待处理来源记录；没有待处理记录时不创建移交控制器。
runtime 最后释放所有权时会与控制器构建互斥，并重验后建立的控制器是否退出；忙碌时保留所有权供稍后重试关闭。
私有缓存路径重定向会在打开存储前拒绝；清理失败时保留配额。
后续维护会在私有数据确认清理后，回收到期的目的端导入／派送元数据及其已结束队列记录。
仍在执行、身份被替换或未知状态的队列会阻止回收；原同意／撤销凭证与已发布用户文件保留。
冷启动维护不启动监听端或生产者；待清理账户的扫描不受大量未到期历史记录遮蔽。
可移植证据保留与共用接口已接入；其余故障交错与正式交付见 Progress.md。
来源证据实验功能已接入 owning runtime 与具名／共用账户的本机 transfer HTTP 管理路径，
提供 review_evidence／create_evidence／get_evidence／revoke_evidence／list_evidence。
独立持久授权沿用真实恢复／完成验证、当前账户与原本机 DAG 审核；已登记 peer 的 evidence
读取核对实际接收的 key／规范与 DAG 节点，只返回 ID、哈希及有限验证，不授予一般任务读取或输入。
审阅摘要不含 node.request_digest；即时读取才按精确已审阅原请求补入。
来源主机技能证据、远端管理路由与共用接口已接入；其余故障验收与交付见 Progress.md。
协调端 DAG 的实验采纳已接入独立审阅的远端恢复授权，固定原来源／key／规范／graph／node 与主机。
批准与启动先持久保存暂定状态，离开本机 writer 后即时验证来源，再核对原同意与认领，才启用。
停止会取消暂定状态；中断后只可用同一明确批准请求续接。确认期间保留 runtime 所有权，
不把独立 peer 读取串行化；认领／记录及最终采纳前后重新验证。
授权失效会阻止后续调度，只对精确已接收的下游任务请求有限暂停；回复未知或丢失时保留认领并待审阅。
已完成副作用与无关任务保留；不宣称已证明原生输入退休或完成整份故障矩阵。
旧投递格式升级会保留原批准 origin 与固定期限；多次续行的额外 origin 仍累积生效。
停止附加的 REST 观察端不会重派或取消服务持有的导入，也不释放 runtime 所有权；重新连接可读取同一笔成果。两主机与独立进程三主机测试已核对实际字节及账号范围。
更多重启／取消交错、更多暂存故障交错、完整保留、可移植证据、client／GUI 接口与完整阶段检查
仍列于 Progress.md；移交收据不授予任务输入权限，也不能证明任务完成。

来源导出的远端审阅／创建／查询／撤销已接合。协调端发出自己的不透明审阅 token，
绑定实际本机调用者、当前主机／凭据摘要、来源审阅、清单摘要与原 key。批准意图在转发前
持久提交；回复丢失或协调端重启后，相同批准仍取回同一来源成果。更换调用者、主机、凭据、
note／key 或来源回复摘要即拒绝。待审阅与持久路由各限128条；到期只清理本机路由 metadata，
保留同意边界。关闭 runtime 会清除尚未批准的本机审阅缓存，已批准的持久意图仍可恢复。
来源使用自身账号，本机 principal／origin 不转发。目的端导入、可移植完成证据与公开接口均已接入；
其余验收与正式交付见 Progress.md。

既有远端 DAG 在固定主机配置及每次保留连接调用前后，均读取实际持久化通讯录。
其他进程替换／移除端点或凭据、配置损坏或原本本机调用者被撤权时，操作会失效。
读取不建立 console，也不隔离通讯录；既有本机服务委派与封闭远端路由保持兼容。

跨主机成果移交依明确审阅与各主机本机授权运行。来源核心可审阅已完成文件成果，建立不可变 blob，
并核对实际发行者／接收者。来源管理与 peer 只读 HTTP 路由已可提供经审阅的清单／分块。
Peer 使用接收端本身的 bearer／RBAC 与速率限制，在外部 principal／用户数据库查询前拒绝
本机 principal／origin header；本机服务 client 仅在管理流程保留实际所有者委派。
移交请求在服务器读取前限制为1MiB；受限 client 在派送请求与解码成功／错误回复前核对上限，
不变更一般 HTTP 的既有上限。完整私有授权链／生命周期验收、目的端发布／
证据采纳及共用公开接口已接入；其余验收与交付见 Progress.md。移交收据不授予任务输入权限。

来源导出在打开选定文件前，排除实际 runtime／移交数据库与 sidecar、当前来源所有者及
发行者的用户数据库、服务连接文件与专属证据目录。服务登记实际私有文件，不保留一般成果的
同名文件名；manifest 只核对选中的输出。Peer 读取与相同请求重试会重新核对当前路径权限，
不重新哈希历史用户成果，并保留操作期限。DAG 成果沿最多十六层真实恢复链核对原始
提交任务、实际请求及本机 DAG admission，重新授权接纳者，并排除其不同位置的账号数据库。
恢复子任务不补造提交记录；正常 standalone 不要求 DAG 提交记录。私有恢复链摘要在审阅、建立、
相同请求重试与 peer 读取时重验；实际私有恢复所有者／审阅者绑定也纳入摘要，其数据库保持私有。
来源操作在字节存取与 grant 写入边界配合取消；提交后回复被取消仍可依固定意图精确取回。
成果期限依完成来源 updated+30 天计算，不因重试／重启刷新，也不改用较早祖先的期限。
本机只读 reader 依当前私有完成授权导出，旧输入仍撤销；自动清理、目的端发布与证据采纳已接入。
其余提交／撤权交错验收与正式交付见 Progress.md。

Runtime 透过实际 batch 主机 adapter 保管 TransferPeer；具名传输固定端点／凭据，于 HTTP 前后
重读持久化通讯录并核对当前本机调用者。来源端使用自身凭据验证，不接收本机 principal／origin
header。来源私有排除只取得实际通讯录路径，不建立／重载 console 或隔离文件。封闭清单与规范 base64 分块须符合
导出 ID／摘要、每块最多256KiB及原始期限；URL 路径前缀同样套用1MiB移交上限，一般 HTTP
保留既有上限；无效预算（含过大整数）在派送前回报类型化错误。两／三主机
导入交付仍待完成。

空闲后台 worker 以只读预检识别空队列，减少轮询与任务状态、完成事务的写入锁竞争。
发现工作后仍须在原有事务内重新核对与领取；保留 claim 代次、过期工作回收与重试上限，
不延长任务或传输期限。

租约维护会在停止事务内核对实际输入所有者与世代。延迟的监视程序不能改写已退役任务的
恢复证据，也不能取消新租约；接受的最终停止状态与取消 token 会先于停止事务发布。
仍有效的权限撤销与原有期限持续生效。

副作用已确认的浏览器任务，可通过已有完成审核与技能流程读取原来的 WebRunner context。
原 helper 先永久结束 SDK 输入／网络，再释放输入 journal／租约；runtime 最多保留 16 个 context，
自分离前预留起最多保留 300 秒，不因分离耗时延长。预览／创建核对实际 effect task 的实时 SDK view；验证只借用原 context
读取最新有界 DOM／字段值，不重新配置输入、不 ACK 原生输入、不传输，也不另开浏览器或 helper。
退出切换、能力探测与清理也拒绝嵌套工具与原生输入。
同 profile 的不同任务分开保管，context ID 本身不授权。私有完成授权审核可在原上限内明确续授权
验证 scope，原输入规范不变；已失效输入 origin 与有限私有保管本身均不授予读取权限。
拥有者删除、目标停用、来源变动、期限或读取失败会使 context 失效；只有确认进程结束才释放
进程拥有权，清理失败持续跟踪。重启不恢复页面，网络结束后的 DOM 不能当作新服务器数据。
Python／AC／MCP／REST／CLI／Builder 与 GUI Actions 共用原审核 request；技能录制保留原动作，
发布须使用自己的实际新验证试跑与明确选择的完成证据。示例见
`examples/agent_browser_retained_completion.py`。冷启动浏览器前缀重建、remote reader、正式部署，
以及暂缓的原生／浏览器／真机／24 小时验收仍待完成。

已停止且副作用已确认的任务，可用 `manage_agent_recovery("preview_completion", {"task_id": id})`
审核独立验证任务，再将精确 task_id／snapshot 与审核说明交给 `create_completion`，最后完成新任务。
私有原子绑定只选择永久只读 helper，不重播来源动作；须有新鲜独立完成条件与输入退出证据。
skill 计划须全部确认；动态任务不得含未处理的有限计划或未知效果。
可先 observe 再 finish；相同 helper 配置只重新检查就绪，不替换权限，也不缓存就绪结果。
来源／审核者权限持续有效，覆盖清理后、明确重试与重启。API／AC／MCP／REST／CLI／Builder 及 GUI Actions 共用此流程。
remote reader、正式部署仍列于 Progress.md；桌面能力仍须另行原生验证。

只有受管任务节点的 DAG，可用 `manage_agent_dag("register", {"definition": graph,
"max_parallel": 4})` 注册持久批次，再明确 `run_dag(graph, batch_id=batch["batch_id"])`。
注册不操作目标；保存整张图的拓扑、节点契约、主机设置与并行数，目标端 key／规范标记绑定批次。
可能派送前先提交 claim，目标端精确规范、完成及输入释放证据通过后才放行依赖节点。成功、中断或
提交回复遗失后都不能再次 begin；`get/list/inspect` 让协调记录跨重启保留。API／AC／MCP／REST／
CLI／Builder 及 DAG Actions 的批次注册／读取、选填批次 ID 共享流程。
停止后用 `review_continuation` 获取只读整图快照及逐节点决策，再把审阅的 `snapshot`、`decisions`
与非空 `note` 放入 `run_dag(graph, batch_id=id, recovery=request)`，批准并使用一次续接机会。
只能采纳独立完成的原任务或真实 recovery 后继任务；派送限从未 claim 且目标端未接收的 pending
节点。本地授权可在相等或更窄根目录内更新，未知 claim 永不重放。DAG Actions 提供停止新派送、
审阅及明确续接；已接受任务仍依自身生命周期处理。将协调交给已明确启动的服务，可调用
`manage_agent_dag("run_background", {"batch_id": id, "definition": graph, "max_parallel": 4})`；
明确批准的续接另带 `approval_id`。DAG Actions 提供两个后台动作；关闭视图不停止已接受的服务工作，
`get.background` 提供有限队列状态。重启使旧 attempt 失效并要求审阅，不重放排队或未知派送。
原 owner 与提交者的权限持续重新验证，本地任务绑定所属 runtime。
既有 `prune_agent_tasks()` 与每小时维护会回收过期且未使用的注册及已安全结束的成功批次，默认 30 天。
未决批次持续保护任务／恢复证据与接收 gate；结果新增 `deleted_batches`、`deleted_dag_deliveries`。
其他队列与用户成果不受影响，远程证据保留仍须明确移交契约。
caller 协调的受管批次固定来源服务路径、端点、凭证指纹及世代，本地节点共用同一 client；连接文件
身份变更就停止后续调用并要求明确审阅。服务端批次证据直接读取所属 runtime，绑定不缓存 bearer
凭证。普通非批次 client 保留动态连接行为；受管批次须有含世代的连接数据。
本地批次节点在持久 claim 后使用来源服务的封闭 `local_task` transport，以原 owner 接收精确规范／
key，并在事务内记录真实 caller。输入前更新双方权限及 attempt；管理员失去跨 owner 管理权也会
阻止执行。没有可信接收记录的旧请求不补造见证。任务 metadata 提供有限 `local_dag_admission`
审计数据，已接受输入仍依既有清理契约处理。
若恢复后继任务须让原所有者读取，preview／review_authorization 请求加入
`owner_policy="source_owner"`，明确 create／create_authorized 时另带回 `ownership.review` 为
`ownership_review`。后继任务保留来源所有者，事务内另记实际审核者，输入前持续验证双方权限。
GUI 提供所有者选择；省略策略仍由创建者持有，沿用既有读取隔离。DAG 可用正常恢复证据采纳独立完成
的原 owner 后继任务；已存在的 caller-owned 子任务不自动变更归属或补造此记录。
详见[续接协议](../../source/Zh/doc/ai_agents/agent_dag_batches_doc.rst)。

触发器可明确使用 `manage_agent_trigger("review_authorization", {"trigger_id":"..."})`，再以
`create_authorized` 提供 `trigger_id`、`snapshot`、`authorization_review`、经审阅的 `spec` 与 `note`。
新注册保留完整模板／设置／待处理上限，受原授权、仍有效限制与当前权限交集约束；事务内停用旧绑定，
并启用未来通知。共享历史让已接受事件与未完成任务跨更新、移除及重启保留，继承的旧排队事件不再派送。
计划从未来时段开始，文件检查点保留。API／AC／MCP／REST／CLI／Builder 及 GUI 触发器菜单共享流程；
普通启用不能取代失效授权，审阅只准备注记留空的请求。

已发布技能可用 `manage_agent_skill("review_authorization", {"candidate_id":"..."})`，再明确
`create_authorized`，提供 `candidate_id`、`snapshot`、`authorization_review`、经审阅的 `spec` 与
`note`。完整计划与参数定义固定；保留原根目录上限及仍有效限制，与当前权限取交集。流程只创建
同一技能的新草稿及审计证据，须重新验证并明确发布下一版，旧版本不变。相同批准去重，过期版本／
授权内容拒绝。API／AC／MCP／REST／CLI／Builder 与 GUI 技能操作菜单共享此流程；trigger 更新使用上方独立流程。

来源授权失效的停止任务，可明确使用 `review_authorization`，再以 `create_authorized` 提供
`task_id`、`snapshot`、经审阅的 `spec`、`note` 与 `authorization_review`。新任务保留所有仍有效的
来源限制，将当前权限与原根目录上限取交集；根目录只可维持或缩小，其余权限、模式／模型、预算及
完成条件固定。批准证据与唯一新任务在同一事务保存；来源及已撤销的见证不变。现有共享接口均提供
这两种操作，GUI Actions 另有授权审阅／创建命令，详见[恢复指南](../../source/Zh/doc/ai_agents/agent_recovery_doc.rst)。
任务恢复不解除输入隔离，也不重建应用状态；技能与 trigger 使用上方独立更新流程。

停止的任务可用 `manage_agent_recovery("preview", {"task_id": "..."})` 审阅来源回执与快照，
不接触应用程序。有限 skill 提供剩余动作及逐条结果；外部 agent／本机模型任务则提供空白目标的
`review_template`，须由操作人明确填写剩余工作目标，不复制旧动作列表。明确 `create` 时提供
快照、经审阅的规范与注记，创建有来源关联的新任务，重新观察并从零回执开始；重复批准返回同一
任务。执行模式、模型／端点、范围、预算及完成条件固定，未知副作用须先人工核对；不移植旧
capture、索引、坐标或已完成历史。可用 `AC_agent_task_recovery`、MCP／REST、
`agent-task recovery preview|create request.json`，或「Agent 任务 → Actions → 审阅剩余工作／
重新规划／创建经审阅的新任务」。已移交的来源不能再恢复，须由新任务继续。
登录与窗口状态的恢复须明确声明，不能推断：继任任务（或任何任务）可列出 `resume_conditions`，只接受
`screen`、`browser` 与 `file_*` 条件（回执是历史，不能证明现状）；第一个动作只在新观察全部通过时
才被接受，任一不成立或无法判定就转为 `waiting_user`，不会动作；有任何动作回执后此关卡即结束。

Android／iOS 内置受管 profile 仍未提供。内部远程副作用防护按实体设备标识保存动作前／后确认；
本地 helper 结束但动作未确认时，仍保留隔离。恢复须在 writer 退出后取得可信设备证据，再以
后续能使旧指令失效的世代证明安全。尚无内置 SDK 证据来源、设备 profile 或原生验收；
剩余接合列于 `Progress.md`。
内部 Android 传输只连接明确设置的现有 loopback ADB server，不调用 CLI、不管理 daemon、
不重试或退回旧 shell；shell-v2 的退出证据有封包／输出上限，但不代表应用完成、实体设备
身份或输入已释放。
内部 Android session 会核对指定端点、实体序号、boot 与默认显示器焦点，并以原子方式固定
boot。有限输入提案在命令连接内重验身份／焦点，限制文字与结果；提案不授权输入，仍须接合
输入窗口、遮挡、锁定／真人活动与自有 worker。
Android 检查后提案会绑定当前的原生输入窗口／队列及 keyguard 证据，核对完整触控路径、
外部拦截与遮挡，并在命令连接内重验摘要。旧 ANR／历史记录不能证明当前状态；真人活动、
全局监视器审阅仍须可信来源授权，内置受管设备执行仍未开放。
内部 Android 动作协议 v2 区分完整前置拒绝、输入失败、输入后拒绝与输入返回。
缺少／错误阶段或退出码不符都维持未知；输入返回不代表远程输入已清空或任务完成，也不授权重试。
内部自有远程 SDK worker 会核对精确任务／所有者范围、重新授权与真人接回；可信主机 factory
创建前先启动 parent 监视。持久化 begin 并收到 ACK 后才调用 SDK，相符设备／世代的清理证据
通过后才发送 end；缺证据维持隔离。可信设备控制来源、WDA adapter 与受管 profile 仍待接合。
命令编译器以一次带标签的提取核对三个原生焦点字段，接受六种顺序，缺少／重复／空值仍拒绝。
前后身份与输入安全检查、原本动作期限均保留。自有 POSIX 假设备减少 Git Bash 读取进程且维持
原始文件 bytes；有限阶段／耗时诊断不含命令、参数或输出。
内部 AndroidRemoteAdapter 已通过逐命令 AndroidCommandLease 接合 checked session 与 worker；
每个动作消耗一次新的身份／输入路由／安全观察，SDK 重新编译有限命令后才通过 ADB 发送一次。
设备端防护须在真人接回、取消或到期后阻止旧写入；没有默认 provider，标准 ADB 或停止本地
helper 不能提供这项保证。清理证据还须绑定新的随机命令 ID、boot 及独立输入／队列状态。
可明确配置主机 hierarchy_reader，提供有界、限 app 的语义元素及经过审阅的非敏感文字；未配置时
仍只有身份 metadata。XML 不授予文字权限；编辑／密码值及受保护子节点持续遮罩，不发布原始
XML 或私有 freshness hash。公开观察版本随来源及动作更新；Android 元素引用须来自当前可操作
的语义元素。新的画面读回可确认已审阅文字出现，缺少／部分／遮罩内容不能证明文字不存在。
不新增 CLI／SDK 启动或捕获备用；真实来源、受保护字段值验证、Unicode／IME 与受管 profile 仍待交付。

受管画面完成验证将内置桌面与 WebRunner 预览视为部分文字证据；文件目标与等待窗口阶段没有
语义画面证据。已知安全文字可确认出现或推翻不存在条件，遮罩与明确隐藏的标签不可作证。
组合条件缺少任一必要证据时保持未知，已知矛盾则判定失败。精确 DOM／字段值应使用明确的
浏览器完成读回；未声明覆盖标志的自定义 target 保留既有行为。

`lookup_agent_task("键", reviewed_spec)` 可选择由目标主机规范化规格，与原所有者提交时保存的
不可变摘要比较；回复声明 `spec_match_contract=1`，并提供一致／不同／无法核对／查无记录。
CLI 可加 `--spec reviewed.json`；AC／MCP／REST／Builder 共用可选对象。DAG 视图先查键，再在
目标端明确支持契约时核对已审阅的节点规格；旧端保持 `unverified`，本地来源 witness 不发到远程。
键改指向别的任务会使旧快照失效；规格一致时仍须核对完成报告的种类、数量与通过结果。
节点比较不等于整个 DAG 拓扑／原批次批准，
`resume_permitted=false` 仍保留明确继续审阅。

`inspect_agent_dag(definition, timeout_seconds=30)` 可查看本地／已登记远程主机的现有提交，
不提交、不暂停、不续跑。提供 `AC_agent_dag_inspect`、MCP、REST 动作、CLI
`agent-task inspect-dag reviewed.json`、Builder 与 DAG Actions。最多 100 节点、最长 300 秒；
远程仍须主机管理权限，不发送本地身份／数据库路径／来源 metadata，不返回远程路径或原始错误。
`recorded_completion` 仅描述查回的任务；节点规格可选择核对，`resume_permitted=false` 仍表示尚未
授权整个 DAG 继续。查无记录不代表拒绝；GUI 在图编辑后丢弃旧视图。

提交回复丢失时，可用 `lookup_agent_task("原去重键")`、`AC_agent_task_lookup`、MCP、
`POST /agent/lookup`、CLI `agent-task lookup 原去重键` 或任务视图 Actions 查询。仅读取原身份及
用户数据库范围，不提交、不续跑、不取得输入控制权；`found=false` 只是当前快照，迟到请求仍
可能被接收。GUI 不会让旧查询回复覆盖后来选择的任务／键。DAG 视图也使用此查询；规格绑定及继续审阅仍待完成；
只读查询仍须具任务访问权限。

现有 `run_dag`／`AC_run_dag`／MCP `ac_run_dag`、REST／CLI 动作文件、Script Builder 与 DAG
Actions 菜单支持受管任务节点：以 `task` 替代 `actions`／`action_file`，包含 `spec`、必填的
`idempotency_key` 与可选的 `wait_seconds`。省略 `host` 使用明确启动的本地服务；远程使用管理员
已登记的主机。目标端须已配置有后台派送的授权 runtime，本功能不部署服务。规格限 skill 或明确
配置的本地模型模式，工具、目标主机路径及完成条件由目标端验证。
节点只提交一次，等待完成条件通过、持久完成契约及输入释放证据后才启动下游。同一批次恢复
须保留去重键；不自动恢复暂停任务或重放副作用。停止、超时或通信／权限失败时，已知任务 ID
才会提出有时限的暂停；未收到确证仍为未知。失败结果保留 ID／去重键并阻止依赖节点，GUI
表格显示任务 ID。本地身份、用户数据库路径及来源 witness 不发送到远程。正式多机部署及原生／
设备验收仍分别跟踪。

DAG 类型与函数也可从 `je_auto_control.api`／`je_auto_control.api.core` 导入。

受管 HTTP 暂停／取消／停止全部／关闭服务使用独立的每 IP 配额，与普通流量同为每分钟 120 次、
突发 30 次；状态查询不会耗尽停止请求的配额。登录、实时角色、任务归属、审计与有界输入清理仍须
通过。共享客户端也为 DAG 批次／节点暂停保留传输容量；`/agent/dag` 的控制标头仅接受封闭的暂停
请求，其他带标记的操作在派送前拒绝。自定义认证门保留自己的契约；这不保证 OS／网络饱和时的优先权。

受管任务在确认输入清理后才发布成功。清理失败或仍忙碌时保留输入租约并要求审阅；确认前
中断仍需恢复。完成发布采用条件式状态转换，不覆盖同时到达的取消请求。现有 GUI／API 任务
结果通过 `metadata.input_released` 显示释放状态；新成功记录保存 `completion_contract=1`，旧记录
保持零而不自动认证。产物报告按最终状态更新，供后续 DAG 协调判断。

DAG 节点在线程池中保留调用者授权、取消与指令限制，自定义 runner 同样适用。每个节点执行前
重新读取用户权限；已删除的用户会使节点失败，后续依赖节点跳过，各操作按更新后的角色
检查权限。默认远程节点在打开主机通讯录或动作文件前要求 `manage_hosts`，避免通过主机凭据
扩大本地操作权限。管理员及受信任的直接 Python 调用仍可远程派送。受管节点采用上述完成
验证与停止契约；正式多机部署及原生验收仍待完成。

浏览器主机目标可通过可选的 `settings.helper_python` 指定已审核且已安装包的 Python
环境（本机绝对解释器路径）。明确指定的 helper 使用 `-I`，从该环境加载已安装包；虚拟环境
解释器的符号链接保留环境身份。任务选项不能指定解释器。
主机管理员可使用 `manage_agent_target("probe", {"name":"reviewed-browser"})`、`AC_agent_target`、
MCP／REST、`agent-task target probe request.json` 或 GUI 主机目标的诊断操作。
诊断以独立且有时限的自有 helper，通过 `je_web_runner` 检查浏览器依赖后结束，过程不获取输入
所有权或启动浏览器。结果可显示 `python_dependencies_ready`；浏览器启动及原生证据仍明确保持
`not_probed`／`not_recorded`。`last_probe` 仅为内存中的带时间诊断快照，不授予任务权限，
也不启用已禁用的目标。桌面／设备的原生诊断仍待完成。
已准备的隔离环境安装两个功能工作树构建的 wheel；共享环境与正式工作树保持原状。正式服务
配置及实际浏览器验收仍单独跟踪；所有浏览器自动化仍统一由 WebRunner（`je_web_runner`）提供。

桌面固定技能现在与浏览器技能共用会话连续性检查。桌面 scope 或自有 helper 结束后，
沿用旧前缀前必须审核，不能用历史记录证明暂停后的表单／窗口状态。未中断的会话可正常
运行；文件 adapter 仍以持久化产物处理恢复。检查在替代 helper 启动前执行，现有继续运行／状态／
记录接口会显示人工审核结果。暂存表单／登录／窗口状态恢复与可审核的剩余步骤重建仍待完成；
原生验收保持暂停。

固定浏览器技能的已验证前缀，现在必须保有原本仍存活的浏览器／helper 会话。
暂停、清理、helper 中断或 runtime 重启后，旧动作记录无法证明表单仍保有之前的字段值；
继续运行会在启动替代 helper 或发送下一动作前进入人工审核。请明确检查剩余步骤并创建新任务。
尚无保留尝试记录的暂停，以及已审核为 failed／not_applied 的尝试，允许全新开始。
外部拥有者仍可重新观察新会话，再规划授权范围内的新动作；未中断的固定技能沿用原
会话。登录及暂存表单状态的恢复仍是未完成工作。

本机 runtime 的用户及实时根目录授权转发，现在必须由明确的本机服务调用启用。
普通具验证的 HTTP 请求仅携带指定的 Bearer token；runtime client 验证 loopback 服务目的地与
路由后，才附上本机用户／来源存储库／witness 信息。版本化 `je_auto_control.api` 现在提供
所有已声明的 `api.core` 名称，包含受管浏览器命令、目标恢复及技能；动作类型 stub 也涵盖
所有出货命令。未解析的延后项目类型沿用生成器原有的 `Any` 策略，避免生成无效名称。
并发预算读取改在数据库独占事务内采样时钟，避免锁获取顺序不同造成任务误判超时；真正的
时钟倒退仍会停止任务。GUI／MCP／REST／CLI 共用这些修复；正式工作树及现有原生／浏览器／
设备／24 小时验收暂停保持原状。

受管浏览器文件命令 `browser_link`、`browser_download`、`browser_upload`（对应 `AC_browser_*`）
委派给 WebRunner 传输契约版本 1。上／下载授权必须具有明确的主机及任务根目录；下载让浏览器
Cookie 保留于自有 SDK／helper，核对完整长度及可选 SHA256，且不覆盖现有文件；复用必须符合
指定 SHA256。上传将最多 4 MiB 的单个普通文件读成核对过的不可变快照，验证可选 SHA256 与
SDK 元数据，不自动提交表单。网络操作仍全部位于 `je_web_runner`。
浏览器 `download_archive` 预览接受查询页 `url`、明确 `allowed_origins`、授权范围内 `directory`，
以及具有单纯 `name`、`url` 或链接 `selector`／可选 `frame` 的 `files`；每文件可用 `page_url` 覆盖
查询页。流程获取新链接、下载每文件最多 16 MiB，并生成供独立核对名称／大小／哈希的归档清单。
GUI Actions 仅起草文件目标／流程／上传示例，不启动资源；MCP／REST／CLI／Builder／模型工具
共用命令，链接读取仍需输入控制权限。部署与实际浏览器验收仍待完成，现有验收暂停保持生效。

浏览器任务可固定完成条件，例如
`{"kind":"browser","operation":"value","selector":"#field","value":"expected"}`。
操作为精确的 `text`、`value`、`visible`（布尔）或 `url`（不含定位）；必须明确授权
`AC_browser_read` 与任务 origins，完成条件不会增加权限。Finish 由同一个自有 helper 检查
当前页面位于允许的 HTTP(S) origin，再通过受控读取命令独立取得 SDK 完整值；既有 receipt、
有界预览或模型停止信号不能代替读回。空白／不可用／范围外页面、被拒读回或错误验证回复
保持未知；比较不符保持失败。取消、权限撤销及人工审核错误保留原类型。
GUI Actions 可起草不启动资源的浏览器完成示例；API／MCP／REST／CLI finish 共用验证器。
SPA URL fragment 会保留，origin 比较仅略去 fragment。实际浏览器／应用验收及已审核传输仍待完成。

受管浏览器启动前，必须先确认 WebRunner 的 `ManagedBrowserSession.contract_version == 1`，
通过后才创建 policy 或开启代理／浏览器。缺失、布尔、文本、过旧或未知标记会保留可处理的
就绪错误。SDK 来源 `575e5d2` 提供完整 text／value 读回：最多 8,000 个 UTF-16 code unit，
超限或无效 Unicode 即拒绝，不截短。AutoControl 对浏览器参数与流程预览数据应用相同 Unicode
上限，在副作用前拒绝。跨源契约通过真正的自有 helper 与替身 Chromium 验证；部署与实际
浏览器／原生验收保持单独记录。


`draft_agent_workflow("batch_form", config)` 与 `transfer` 可设置 `backend: browser`，
并提供明确的 `allowed_origins` 与已审核 browser target。CSV／XLSX 来源仍受 roots 限制；
浏览器草稿仅生成 `AC_browser_*` 动作，不退回桌面输入。填表提供 `url`、CSS `fields`、
可选 frame／新建记录控件、提交与确认 selector；每次填入都有独立的精确 value 读回。
可用 `confirmation_column` 从每行取得预期确认文字。转填提供 `source_url`／`destination_url`，
提取 text／value、应用白名单转换、填入并读回目标字段，再验证保存；提交前拒绝陈旧确认。
`AC_browser_wait`／`browser_wait` 仅轮询 text／value，也支持稍后才出现的元素；`wait_seconds`
默认 5 秒，受 action budget 限制，超时才返回的匹配结果仍拒绝，不重放填入或点击。
Python/core、共享 catalog／模型 schema、MCP、CLI／REST 任务操作、Builder 及 GUI 流程预览
使用同一编译器。浏览器读回可作为独立技能证据。实际应用验收与正式上／下载设置仍待完成；
SDK 启动前须通过完整有界读回契约版本 1 的检查。

受管浏览器 profile（`kind: browser`）统一委派给 WebRunner 的 `je_web_runner` SDK；
开发来源为 `D:\Codes\WebRunner`，集成来源位于其隔离的受管 session 功能分支。
Profile 必须提供精确的 `settings.allowed_origins`、浏览器专用工具，且不能授权桌面 app；
每项任务另须设置非空、更窄的 `options.allowed_origins`，每次激活均重新核对两层范围。
注册不启动资源；helper 环境须明确安装已审核的受管 SDK 与 Chromium，缺少时就绪失败，不自动安装。
`AC_browser_navigate`、`AC_browser_click`、`AC_browser_fill`、`AC_browser_select`、`AC_browser_check`
及 `AC_browser_read` 共用 Python/core、executor、MCP 与 Builder 定义。命令仅在受管 helper 中
运行，通过既有 task submit/observe/act 周期驱动。读取操作为 `text`、`value` 或 `visible`；
WebRunner 拒绝秘密表单字段。DOM 索引在当前 observation 内解析 selector／frame，再核对新鲜度。
失败副作用保持不确定且需对账；暂停／取消会结束拥有的资源。GUI Actions 可生成浏览器目标示例
供审核；DOM 选择仅编辑动作请求。专用 helper 跨就绪检查保留同一个全新 session，正常清理先
取得浏览器 ACK，再结束自己的进程树；符合完成审核条件的来源则将原本已冻结的 context
移交 runtime 有界保管。浏览器任务不获取共享桌面输入控制权。跨源受控测试使用真正 SDK、
替身 Chromium、自有 IPC／loopback；实际浏览器／原生验收、正式传输设置及其余浏览器流程类型仍列于 `Progress.md`。

MCP 异步调用会保留接受请求时的角色、session、原路径策略与工具列表；session 或路径策略
结束后，延迟分派会被拒绝。异步无状态调用仍使用固定 profile。插件工具列表变更会送达所有
有效 HTTP session 流；session 启停只通知拥有者，并避免重复发送。流注册与 HTTP 标头
共用锁，避免提早发送的通知破坏 HTTP 响应。
纯 metadata 的 `benchmarks/mcp_discovery.py --repeats 20` 测量工具数、JSON bytes、预热后的
进程内握手、搜索与启用耗时。Windows／Python 3.14.4 的记录中，完整模式初始有 732 个授权工具、
358,029 bytes；渐进模式为 5 个、2,029 bytes，响应大小减少 99.43%。握手为 58.263／47.439 ms，
搜索中位数为 16.243／19.718 ms；渐进启用中位数为 42.486 ms。此本机测量不含冷启动导入及原生操作。
有日期的 JSON 记录位于 `docs/benchmarks/`；既有参数策略的覆盖限制仍列于 `Progress.md`。

MCP 可选择 session 渐进揭露：`je_auto_control_mcp --tool-mode progressive` 初始只提供五个
探索控制工具；`ac_mcp_tools_enable`／`ac_mcp_tools_disable` 只改变该 session。
不会更新工具列表的客户端可使用 `--tool-mode static --tool-profile ac_screen_size,ac_list_windows`；
默认 `full` 保留不分页的授权工具列表。渐进／固定模式的 cursor 不透明、只能使用一次，并绑定
快照与调用者；工具、角色或列表设置变更，以及 cursor 过期时，须重新运行 `tools/list`。
启停只通知拥有者连接；session 结束会回收 cursor 并使尚在运行的 metadata callback 失效。
HTTP／嵌入式使用 `MCPServer.configure_tool_disclosure(...)`；主机环境变量为
`JE_AUTOCONTROL_MCP_DISCLOSURE` 与逗号分隔的 `JE_AUTOCONTROL_MCP_TOOL_PROFILE`。
`plan_mcp_tool_profile(...)` 及 Diagnostics Actions 可预览启动参数，不会启动服务。
无状态协议使用不分页的初始固定列表，不保留 session 启用状态。只读限制也覆盖后续新增的插件。
未验证／共享 token 连接显示 operator 工具，与既有调用上限一致；主机管理工具仍须已验证身份。

MCP 工具探索提供 `search_mcp_tools(query, limit=10)`、`get_mcp_tool_schema(name)`、
对应 AC／MCP 命令及 Diagnostics → Actions。搜索返回有界摘要、分类与所需权限；完整 schema
须指定单一工具查看。两种查询都重新验证角色，并遵守 registry 的只读筛选；MCP 查询使用该
server 的实时 registry，包含插件变更。CLI 可运行
`je_auto_control_mcp --search-tools document --limit 5` 或 `--tool-schema ac_mcp_tool_search`。
完整模式仍为默认；各 session 的渐进揭露可按前述设置启用。

Agent 工具调用经 `executor.execute_one(name, arguments)` 返回原始结果，与动作脚本共用
授权、变量插值、取消及日志边界；拒绝私有 executor 参数。受管任务交付进度见 `Progress.md`。

输入控制权会在分派及输入确认前写入持久记录。服务崩溃后，先手动释放按键与鼠标按钮，再以主机管理权限调用 `recover_agent_target(target, note)` 记录审核并恢复目标；任务未知结果仍须另外核对。工作区文档由输入 helper 之外的进程启动，指定的聚焦步骤会等待授权应用程序窗口就绪。

受管技能将已验证的语义流程录制为不可变候选。`manage_agent_skill` 可预览具有类型的参数、执行独立验证任务，并在明确审核该候选的成功证据后发布编号版本。定位器修复会产生须重新验证的候选；任务固定使用原版本与摘要。AC／MCP／REST／CLI 与 Agent Tasks 的 Actions 菜单提供相同操作。

原验证试跑的动作若已全部确认，可明确审核／创建并完成独立只读验证任务，再以
`manage_agent_skill("accept", {...})` 提供原 `task_id` 与可选的 `completion_task_id`。
发布保留精确候选／试跑摘要与 pin，核对最多十六层真实只读恢复链、实时权限及独立完成／清理证据。
原试跑维持停止，动作不重播；Actions 菜单可准备待审核请求。发布记录在临时 reader 证据到期后
仍保留历史 ID／摘要；尚未发布的采纳仍须有留存证据。

停止的原流程也可通过 `manage_agent_skill("record", request)` 明确提供 `completion_task_id`。
`task_id` 仍指原流程，草稿保留其已确认语义动作，另采纳只读 reader 的私有独立完成证据。
录制不重播动作、不改来源状态；来源／证据检查与草稿写入共用事务，并重验实时权限。
`provenance.completion_review` 在 reader 保留期后只是历史记录，不授予当前权限。
草稿与新增验证条件仍须自己的新验证试跑，不能直接发布；Actions 菜单只准备录制请求。

原验证试跑只执行部分动作时，先调用 `manage_agent_skill("review_execution", request)`，
提供 `candidate_id`、原 `task_id` 与另一个最终 `execution_task_id`；再以相同 ID、返回的
`execution_review`、`expected_version` 及非空 `note` 明确 `accept`。最多十六层真实可执行恢复链
必须确认完整原语义计划；不同的剩余流程即使成功也不足。比较包含 JSON 类型、capture 值、预期结果
与 grounding，但不恢复旧 capture 或重建历史 UI 状态。各任务保留原限制与独立批准；当前 caller、
全部 owner 及实际创建审核者都须持续有权限。版本、发布及历史 `publication.execution_review`
共同提交或回滚，写入后再次检查证据与权限。原试跑维持停止并保留 `publication.task_id`，不补造子任务
为 validation trial。可选 `completion_task_id` 必须验证最终可执行任务的效果，其证据嵌套存于
execution 审核记录；过期证据不能批准未发布候选。两个 Actions 示例只准备审核／接受请求，
`agent_skill_execution_review.json` 与 `agent_skill_execution_accept.json` 可编辑后使用。

受管任务保留来源路径策略：移除根目录后，后续动作、事件触发及技能验证会受阻。MCP 客户端根目录按会话隔离，来源授权结束后撤销；主机配置的固定策略则在明确更换前保留。服务停止会取消实际执行中的工作，包括取得输入前的模型初始化，尚未启动的投递则持续保存。

实验性的[受管 Agent 任务](../../AGENT_TASKS.md)提供所有者范围内的提交、观察、动作、验证、
暂停、恢复、取消、控制权代次、持久化回执、WorkQueue 派送与本机 Ollama 推理。
Python、AC、MCP、REST、CLI 与 Agent 任务面板共用后台服务，明确执行
`je_auto_control agent-task start` 才启动；新流程不强制依赖外部服务。
四条可预览模板涵盖下载归档、CSV/XLSX 填表、跨应用转移与工作区准备；
使用 `agent-task draft` 或 Actions 的「预览工作流程」检查后提交。
持久化间隔、Cron、文件与事件绑定会保留核准范围，每次触发重新授权并去重；
提交标识避免重试与重启时创建重复任务。
提供所有者范围内的回执与结果不明对账，关联执行历史、journal 及逐条报告；
服务缓存默认保留 30 天，保留用户输出与外部 journal。
证据缓存以完整数据库路径及持久数据库身份绑定于 `.agent-evidence-cache/`。
还原的数据库与旧版缓存保留原历史引用；下次动作或报告创建新的自有 journal 分段，
不读取或移动历史文件。任务 metadata 的 `artifact_cache_state` 为 `owned` 或 `historical`。
保留清理只移除当前数据库可识别的自有缓存文件；历史文件保留，留存的私有根目录禁止成果导出。

Linux 上的 helper 程序可改由可选的 [owner 服务](../../../native/owner_service/README.md) 运行：
root guardian 把每个 helper 放进它自己的 cgroup v2 树，helper 帐号无法离开；关闭 channel 会
结束整棵树（含逃离的后代），guardian 重启后会清理崩溃留下的程序。root 拥有的
`/etc/je_auto_control/owner_service.json` 绑定档只让完全列出的 helper argv 经由服务启动；
驱动桌面或浏览器的 helper 一律以本机程序运行，因为受保护的 helper 以独立 ID、空环境运行，无法存取显示；
没有绑定档时 helper 仍以本机程序运行，`agent-task status` 在 `helper_containment` 回报模式。
Python 包不会构建、安装或启动服务，且在审阅后的版本开启闸门前，构建出的服务拒绝受保护启动。

`agent-task readiness`（`agent_runtime_readiness`、`AC_agent_runtime_readiness`、MCP 工具及 Agent 任务面板的
Actions 菜单）报告桌面输入与截取、真人在场来源、Android 与 iOS 控制、浏览器和本机模型各自的状态：
`unsupported`、`missing_dependency`、`unauthorized`、`not_probed`、`not_recorded` 或 `measured`。它只读环境变量、
`PATH` 与已安装包，不连接设备、不启动 helper、不请求权限，所以不会报告 `measured`，每一项的
`native_evidence` 都是 `not_recorded`；已安装的工具只算 `not_probed`，不代表可用。

部署或回退前须比对来源与制品哈希，不能只凭相同版本号判断私有缓存兼容性。
不具此私有根目录保护的旧程序不得沿用新版数据库／缓存。经审核的回退须使用匹配的升级前状态
及其原记录位置，先取得自有输入退出确证，并从所有旧版任务根目录排除留存的新版私有文件；
保留不明 journal，不重放副作用。无法核实时维持兼容版本。

Windows USB 枚举明确以 UTF-8 输出及解码，PowerShell 子进程保持隐藏。
Python UTF-8 模式开启或关闭时，Unicode 设备名称与诊断均完整保留；枚举仍为只读。
原生调用使用专属 helper，支持取消、超时、输入记录清理与跨数据库的桌面排他控制。
Windows 共享桌面的持续来源跨 runtime／任务／helper 共用，监看开始后须重新累积解锁空闲 60 秒。
仅支持已确认的活动本机 console；远程、shadow 及未知 session 一律拒绝。
每个 helper 在输入 ACK 前后实时核实同一主机租约；来源／reader 失效会暂停输入，
未确认的按住输入清理仍保持隔离，须明确重试。关闭一个 runtime 不会停止其他 runtime 的来源。
目标说明只公开粗略 `presence` 状态与 `native_evidence=not_recorded`，不启动探测。
`agent-task stop-all` 停止可见任务。
其他共享桌面须有可信活动 adapter。原生平台验收与其余待办列在 `Progress.md`。

Linux 内部 presence_peer_linux 以不可继承的 pidfd 保留原始 Unix stream 或 seqpacket 连接者，
核验账户、进程创建时间、namespace 与存活状态，不另依 PID 打开进程。进程身份不代表桌面或输入权限。

内部 LinuxListener 与 LinuxChannel transport 拥有受保护的 Unix endpoint、socket 与 peer。
每个有界 JSON 数据包须有仍存活的原始 writer 的内核凭证与 pidfd；额外、缺失、负值或截断的控制数据
直接拒绝，收到的描述符在交付前释放。排队与 I/O 共用同一期限；取消撤销交付，尚未完成或失败的
清理维持未确定。未知文件系统对象保留不动。路径权限不能隔离同 UID 的敌对进程，用户空间的有界
等待也不保证内核 syscall 的硬实时完成。

X11 与 macOS 已有真人活动来源。X11 只计入真实设备的 XInput2 raw 事件（XTEST 从属设备一律排除），
并从 logind 读 `Active`／`LockedHint`；没有 logind 或 `XDG_SESSION_ID` 时视为锁定。macOS 用只读的 session
event tap（需要辅助功能权限）；只有进程从非 HID 来源状态发出的事件才算注入，有疑义时让任务等待而不是接手。
Wayland 没有可信来源。Linux 的 presence broker、worker 与 server 已改经此 transport：自有 worker 绑定
全新的私有 endpoint 并在 bootstrap 回复中报告，broker 只采用该 endpoint，连接时先核对 listener 即其所列
进程，再做 presence challenge。macOS 尚无 presence transport；原生验收前 runtime 仍拒绝非 Windows 共享
桌面任务；此 transport 不是完整 Linux 应用或原生输入验收。

[![PyPI](https://img.shields.io/pypi/v/je_auto_control)](https://pypi.org/project/je_auto_control/)
[![Python](https://img.shields.io/pypi/pyversions/je_auto_control)](https://pypi.org/project/je_auto_control/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../../LICENSE)
[![Documentation](https://readthedocs.org/projects/autocontrol/badge/?version=latest)](https://autocontrol.readthedocs.io/en/latest/?badge=latest)

**AutoControl** 是一套开源、跨平台的 **computer-use 与 GUI 自动化框架**，面向 AI agent、Python 应用程序与自动化测试。它能驱动鼠标与键盘、通过模板匹配、OCR、操作系统无障碍树或视觉模型找到 UI 目标、录制与回放操作流程，并以 JSON 动作文件执行——
支持 Windows、macOS、Linux（X11 与 Wayland）、BSD、Android 与 iOS。

每项能力都以三种形式提供：**Python API**、可在 JSON 文件／CLI／服务器使用的 **`AC_*` 动作命令**，
以及 **GUI 标签页**。没有任何功能只存在于 GUI。

**[English](../../../README.md)** · **[繁體中文](../../../README/README_zh-TW.md)**

---
