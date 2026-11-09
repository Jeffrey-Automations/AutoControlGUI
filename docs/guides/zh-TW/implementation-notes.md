# Implementation notes migrated from README

Historical implementation notes preserved during the README reorganization on 2026-11-10. These entries describe different development stages and are not a current acceptance checklist. See [Progress](../../../Progress.md) and [updates](../../updates/README.md) for tracked status.


成果移交管理已共用 `manage_agent_transfer(operation, request)`、`AC_agent_transfer`、
`ac_agent_transfer`、具授權的 `POST /agent/transfer` 與 Script Builder metadata。CLI 使用
`agent-task transfer --operation review_export --request request.json`。審閱回傳批准 token；
建立須提供該 token、原請求 key 與明確 note。匯出／匯入管理可指定已登記主機；
可攜證據管理也可指定已登記主機，由來源核實私有權限。傳輸頁提供四語 Actions、可編輯 JSON 與服務回覆；
審閱不自動核准，核准範本保留原主機、token 與 key 並留白備註。選項變更或關閉頁面後，
舊回覆不覆寫畫面，已接受的匯入仍由服務持有。遠端核准先保存明確同意，失聯或協調端重啟後以原鍵重送，維持同一授權。
被動診斷僅列出本機契約，不代表即時授權或遠端／原生能力已驗證。只讀完成證據在建立與取用時重新核對原私有同意，不恢復原輸入權限。
實作驗證紀錄見 docs/updates/README.md；其餘交付與驗收見 Progress.md。
examples/agent_transfer_export_review.json、agent_transfer_import_review.json 與
agent_transfer_evidence_review.json 提供可編輯請求，並各有獨立的 create 範本。

實驗性的來源主機技能操作，可透過既有 `handoff_id` 明確選取可攜授權與完成／執行任務。
來源在技能交易內重新核對實際同意、接收者與私有證據，候選／發布寫入後再次核對。
保留原始動作、候選自己的驗證試跑與明確版本批准；新的技能試跑建立服務產生的全新請求 key，
不為舊有未帶 key 的試跑補造紀錄。此流程不將外部動作或政策移交協調端；
技能證據保留來源主機的原動作／試跑／版本；其餘跨主機驗收與交付見 Progress.md。
選取移交證據的技能操作，全程保留 runtime 擁有權，操作結束後才釋放。

目的端匯入目前仍為實驗功能。明確啟動的服務可透過 runtime 移交控制器與經驗證的
`/agent/transfer` 接受 `review_import`／`create_import`／`get_import`／`run_import`／
`cancel_import`／`list_imports`。協調端可透過自己的不透明同意 token 路由這些有限操作；
目的端使用自己的來源登錄與帳號，不轉送協調端 principal／origin 或來源憑證。
核准意圖在派送前提交；回覆遺失後的精確重試仍對應同一筆匯入。
啟動時接回已核准且尚未領取的工作；未結算 claim 會轉為待審閱。明確的 `run_import`
以新佇列世代重新核對原收件者、profile、即時 origin 與來源 grant，可重用已驗證私有分塊，
或唯讀核對既有完整目錄與雜湊，不重新下載／發布。續行時新增的 origin 限制仍持續生效。
已明確排入佇列且未領取的唯讀核對可跨再次重啟；採認前重驗目前位元組、profile 與保留的 origin。
匯入收據確認完成前，目的端會在最後一次來源回應後重新核對完整檔案清單與內容摘要。
檔案遭改寫、遺失或增加未列入清單的檔案時，匯入保留 requires_review，
保留使用者修改與原發布成果供審閱。
目錄身分、位元組或授權變更不能確認發布。取消會使產生者失效；尚未完成收據確認的
發布保留 requires_review，已確認發布的檔案保留為使用者成果。
取消或到期的私有分塊帳戶須確認產生者退場才清理；失敗時保留配額，成功重試後才釋放。
收據維持原本固定期限。
暫存目錄與預先建立的檔案會在複製位元組前記錄檔案系統身分。產生者退場後，
到期清理可於重啟後重試；遇到置換或無關物件時保留配額待審閱，不遞迴刪除。
來源維護會清理到期或已撤銷的私有匯出帳戶，包含重啟或授權者移除後；失敗時保留配額。
來源或目的端清理完成前持續保有 runtime 擁有權；無待清理資料時不取得 runtime 寫入鎖。
建立／續行回覆會在喚醒新派送前讀取已提交的收據；後續以 get_import 查詢目前進度，避免回覆被新 writer 擋住。
後續維護會修剪已清理、撤銷且到期的來源中繼資料以回收筆數配額，保留同意／撤銷憑證與其他記錄類別。
冷啟動維護以唯讀探測發現待處理來源記錄；沒有待處理記錄時不建立移交控制器。
runtime 最後釋放擁有權時會與控制器建構互斥，並重驗晚建立的控制器是否退場；忙碌時保留擁有權供稍後重試關閉。
私有快取路徑轉向會在開啟儲存前拒絕；清理失敗時保留配額。
後續維護會在私有資料確定清理後，回收到期的目的端匯入／派送中繼資料及其已結束佇列紀錄。
仍在執行、身分被替換或未知狀態的佇列會阻止回收；原同意／撤銷憑證與已發布使用者檔案保留。
冷啟動維護不啟動監聽端或產生者；待清理帳戶的掃描不受大量未到期歷史紀錄遮蔽。
可攜證據保留與共用介面已接入；其餘故障交錯與正式交付見 Progress.md。
來源證據實驗功能已接入 owning runtime 與具名／共用帳戶的本機 transfer HTTP 管理路徑，
提供 review_evidence／create_evidence／get_evidence／revoke_evidence／list_evidence。
獨立持久授權沿用真實恢復／完成驗證、當前帳戶與原本機 DAG 審核；已登錄 peer 的 evidence
讀取核對實際接收的 key／規格與 DAG 節點，只回傳 ID、雜湊及有限驗證，不授予一般任務讀取或輸入。
審閱摘要不含 node.request_digest；即時讀取才依精確已審閱原請求補入。
來源主機技能證據、遠端管理路由與共用介面已接入；其餘故障驗收與交付見 Progress.md。
協調端 DAG 的實驗採認已接入獨立審閱的遠端恢復授權，固定原來源／key／規格／graph／node 與主機。
核准與啟動先持久保存暫定狀態，離開本機 writer 後即時查驗來源，再核對原同意及認領，才啟用。
停止會取消暫定狀態；中斷後只可用同一明確核准請求續接。確認期間保留 runtime 擁有權，
不把獨立 peer 讀取序列化；認領／紀錄及最終採認前後重新驗證。
授權失效會阻擋後續排程，只對精確已接收的下游任務請求有限暫停；回覆未知或遺失時保留認領並待審閱。
已完成副作用與無關任務保留；不宣稱已證明原生輸入退休或完成整份故障矩陣。
舊派送格式升級會保留原核准 origin 與固定期限；多次續行的額外 origin 仍累積生效。
停止附加的 REST 觀察端不會重派或取消服務持有的匯入，也不釋放 runtime 擁有權；重新連線可讀取同一筆成果。兩主機與獨立程序三主機測試已核對實際位元組及帳號範圍。
更多重啟／取消交錯、更多暫存故障交錯、完整保留、可攜證據、client／GUI 介面與完整階段檢查
仍列於 Progress.md；移交收據不授予任務輸入權限，也不能證明任務完成。

來源匯出的遠端審閱／建立／查詢／撤銷已接合。協調端發出自己的不透明審閱 token，
綁定實際本機呼叫者、目前主機／憑證摘要、來源審閱、清單摘要與原 key。批准意圖在轉送前
耐久提交；回覆遺失或協調端重啟後，相同批准仍取回同一來源成果。改換呼叫者、主機、憑證、
note／key 或來源回覆摘要即拒絕。待審閱與耐久路由各限128筆；到期只清理本機路由 metadata，
保留同意邊界。關閉 runtime 會清除尚未批准的本機審閱快取，已批准的耐久意圖仍可恢復。
來源使用自身帳號，本機 principal／origin 不轉送。目的端匯入、可攜完成證據與公開介面均已接入；
其餘驗收與正式交付見 Progress.md。

既有遠端 DAG 在固定主機設定及每次保留連線呼叫前後，均讀取實際持久化通訊錄。
其他程序替換／移除端點或憑證、設定損壞或原本本機呼叫者被撤權時，操作會失效。
讀取不建立 console，也不隔離通訊錄；既有本機服務委派與封閉遠端路由保持相容。

跨主機成果移交依明確審閱與各主機本機授權運作。來源核心可審閱已完成檔案成果，建立不可變 blob，
並核對實際發行者／接收者。來源管理與 peer 唯讀 HTTP 路由已可提供經審閱的清單／分塊。
Peer 使用接收端本身的 bearer／RBAC 與速率限制，在外部 principal／使用者資料庫查詢前拒絕
本機 principal／origin header；本機服務 client 僅在管理流程保留實際擁有者委派。
移交要求在伺服器讀取前限制為1MiB；受限 client 在派送要求與解碼成功／錯誤回覆前核對上限，
不變更一般 HTTP 的既有上限。完整私有授權鏈／生命週期驗收、目的端發布／
證據採認及共用公開介面已接入；其餘驗收與交付見 Progress.md。移交收據不授予任務輸入權限。

來源匯出在開啟選定檔案前，排除實際 runtime／移交資料庫與 sidecar、目前來源擁有者及
發行者的使用者資料庫、服務連線檔與專屬證據目錄。服務登記實際私有檔案，不保留一般成果的
同名檔名；manifest 只核對選中的輸出。Peer 讀取與相同要求重試會重新核對目前路徑權限，
不重新雜湊歷史使用者成果，並保留操作期限。DAG 成果沿最多十六層真實恢復鏈核對原始
提交任務、實際請求及本機 DAG admission，重新授權接納者，並排除其不同位置的帳號資料庫。
恢復子任務不補造提交列；正常 standalone 不要求 DAG 提交列。私有恢復鏈摘要在審閱、建立、
相同要求重試與 peer 讀取時重驗；實際私有恢復擁有者／審閱者綁定也納入摘要，其資料庫保持私有。
來源操作在位元組存取與 grant 寫入邊界配合取消；提交後回覆被取消仍可依固定意圖精確取回。
成果期限依完成來源 updated+30 天計算，不因重試／重啟刷新，也不改用較早祖先的期限。
本機唯讀 reader 依目前私有完成授權匯出，舊輸入仍撤銷；自動清理、目的端發布與證據採認已接入。
其餘提交／撤權交錯驗收與正式交付見 Progress.md。

Runtime 透過實際 batch 主機 adapter 保管 TransferPeer；具名傳輸固定端點／憑證，於 HTTP 前後
重讀持久化通訊錄並核對目前本機呼叫者。來源端使用自身憑證驗證，不接收本機 principal／origin
header。來源私有排除只取得實際通訊錄路徑，不建立／重載 console 或隔離檔案。封閉清單與正規 base64 分塊須符合
匯出 ID／摘要、每塊最多256KiB及原始期限；URL 路徑前綴同樣套用1MiB移交上限，一般 HTTP
保留既有上限；無效預算（含過大整數）在派送前回報型別化錯誤。兩／三主機
匯入交付仍待完成。

閒置背景 worker 以唯讀預檢辨識空佇列，減少輪詢與任務狀態、完成交易的寫入鎖競爭。
發現工作後仍須在原有交易內重新核對與認領；保留 claim 世代、過期工作回收與重試上限，
不延長任務或傳輸期限。

租約維護會在停止交易內核對實際輸入擁有者與世代。延遲的監看程序不能改寫已退休任務的
恢復證據，也不能取消新租約；接受的最終停止狀態與取消 token 會先於停止交易發布。
仍有效的撤權與原有期限持續生效。

副作用已確認的瀏覽器任務，可透過既有完成審閱與技能流程讀取原本的 WebRunner context。
原 helper 先永久結束 SDK 輸入／網路，再釋放輸入 journal／租約；runtime 最多保留 16 個 context，
自分離前預留起最多保留 300 秒，不因分離耗時延長。預覽／建立核對實際 effect task 的即時 SDK view；驗證只借用原 context
讀取最新有界 DOM／欄位值，不重新配置輸入、不 ACK 原生輸入、不傳輸，也不另開瀏覽器或 helper。
退休切換、能力探測與清理也拒絕巢狀工具與原生輸入。
同 profile 的不同任務分開保管，context ID 本身不授權。私有完成授權審閱可在原上限內明確續授權
驗證 scope，原輸入規格不變；已失效輸入 origin 與有限私有保管本身均不授予讀取權限。
擁有者刪除、目標停用、來源變動、期限或讀取失敗會使 context 失效；只有確認程序結束才釋放
程序擁有權，清理失敗持續追蹤。重啟不還原頁面，網路結束後的 DOM 不能當作新伺服器資料。
Python／AC／MCP／REST／CLI／Builder 與 GUI Actions 共用原審閱 request；技能錄製保留原動作，
發布須使用自己的實際新驗證試跑與明確選取的完成證據。範例見
`examples/agent_browser_retained_completion.py`。冷啟動瀏覽器前綴重建、remote reader、正式部署，
以及暫緩的原生／瀏覽器／真機／24 小時驗收仍待完成。

已停止且副作用已確認的任務，可用 `manage_agent_recovery("preview_completion", {"task_id": id})`
審閱獨立驗證任務，再將精確 task_id／snapshot 與審閱說明交給 `create_completion`，最後完成新任務。
私有原子綁定只選擇永久唯讀 helper，不重播來源動作；須有新鮮獨立完成條件與輸入退休證據。
skill 計畫須全部確認；動態任務不得含未處理的有限計畫或未知效果。
可先 observe 再 finish；相同 helper 設定只重新檢查就緒，不替換權限，也不快取就緒結果。
來源／審閱者權限持續有效，涵蓋清理後、明確重試與重啟。API／AC／MCP／REST／CLI／Builder 及 GUI Actions 共用此流程。
remote reader、正式部署仍列於 Progress.md；桌面能力仍須另行原生驗證。

只有受管任務節點的 DAG，可用 `manage_agent_dag("register", {"definition": graph,
"max_parallel": 4})` 註冊耐久批次，再明確 `run_dag(graph, batch_id=batch["batch_id"])`。
註冊不操作目標；保存整張圖的拓樸、節點契約、主機設定與並行數，目的端 key／規格標記綁定批次。
可能派送前先提交 claim，目的端精確規格、完成及輸入釋放證據通過後才放行相依節點。成功、中斷或
提交回覆遺失後都不能再次 begin；`get/list/inspect` 讓協調紀錄跨重啟保留。API／AC／MCP／REST／
CLI／Builder 及 DAG Actions 的批次註冊／讀取、選填批次 ID 共用流程。
停止後以 `review_continuation` 取得唯讀整圖快照及逐節點決策，再把審閱的 `snapshot`、`decisions`
與非空 `note` 放入 `run_dag(graph, batch_id=id, recovery=request)`，核准並使用一次續接機會。
只能採認獨立完成的原任務或真實 recovery 後繼任務；派送限從未 claim 且目的端未接收的 pending
節點。本機授權可在相等或更窄根目錄內更新，未知 claim 永不重播。DAG Actions 提供停止新派送、
審閱及明確續接；已接受任務仍依自身生命週期處理。將協調交給已明確啟動的服務，可呼叫
`manage_agent_dag("run_background", {"batch_id": id, "definition": graph, "max_parallel": 4})`；
明確批准的續接另帶 `approval_id`。DAG Actions 提供兩個背景動作；關閉視圖不停止已接受的服務工作，
`get.background` 提供有限佇列狀態。重啟使舊 attempt 失效並要求審閱，不重播排隊或未知派送。
原 owner 與提交者的權限持續重新驗證，本機任務綁定所屬 runtime。
既有 `prune_agent_tasks()` 與每小時維護會回收過期且未使用的註冊及已安全結束的成功批次，預設 30 天。
未決批次持續保護任務／復原證據與接收 gate；結果新增 `deleted_batches`、`deleted_dag_deliveries`。
其他佇列與使用者成果不受影響，遠端證據保留仍須明確移交契約。
caller 協調的受管批次固定來源服務路徑、端點、憑證指紋及世代，本機節點共用同一 client；連線檔
身分變更就停止後續呼叫並要求明確審閱。服務端批次證據直接讀取所屬 runtime，綁定不快取 bearer
憑證。一般非批次 client 保留動態連線行為；受管批次須有含世代的連線資料。
本機批次節點在耐久 claim 後使用來源服務的封閉 `local_task` transport，以原 owner 接收精確規格／
key，並在交易內記錄真正 caller。輸入前更新雙方權限及 attempt；管理員失去跨 owner 管理權也會
阻止執行。沒有可信接收紀錄的舊請求不補造見證。任務 metadata 提供有限 `local_dag_admission`
稽核資料，已接受輸入仍依既有清理契約處理。
若復原後繼任務須讓原擁有者讀取，preview／review_authorization 請求加入
`owner_policy="source_owner"`，明確 create／create_authorized 時另帶回 `ownership.review` 為
`ownership_review`。後繼任務保留來源擁有者，交易內另記實際審閱者，輸入前持續驗證雙方權限。
GUI 提供擁有者選擇；省略政策仍由建立者持有，沿用既有讀取隔離。DAG 可用正常復原證據採認獨立完成
的原 owner 後繼任務；已存在的 caller-owned 子任務不自動變更歸屬或補造此紀錄。
詳見[續接協定](../../source/Zh/doc/ai_agents/agent_dag_batches_doc.rst)。

觸發器可明確使用 `manage_agent_trigger("review_authorization", {"trigger_id":"..."})`，再以
`create_authorized` 提供 `trigger_id`、`snapshot`、`authorization_review`、經審閱的 `spec` 與 `note`。
新註冊保留完整模板／設定／待處理上限，受原授權、仍有效限制與目前權限交集約束；交易內退休舊綁定，
並啟用未來通知。共用歷史讓已接受事件與未完成任務跨更新、移除及重啟保留，沿用的舊排隊事件不再派送。
排程從未來時段開始，檔案檢查點保留。API／AC／MCP／REST／CLI／Builder 及 GUI 觸發器選單共用流程；
一般啟用不能取代失效授權，審閱只準備註記留空的請求。

已發布技能可用 `manage_agent_skill("review_authorization", {"candidate_id":"..."})`，再明確
`create_authorized`，提供 `candidate_id`、`snapshot`、`authorization_review`、經審閱的 `spec` 與
`note`。完整計畫與參數定義固定；保留原根目錄上限及仍有效限制，與目前權限取交集。流程只建立
同一技能的新草稿及稽核證據，須重新驗證並明確發布下一版，舊版本不變。相同核准去重，過期版本／
授權內容拒絕。API／AC／MCP／REST／CLI／Builder 與 GUI 技能操作選單共用此流程；trigger 更新使用上方獨立流程。

來源授權失效的停止任務，可明確使用 `review_authorization`，再以 `create_authorized` 提供
`task_id`、`snapshot`、經審閱的 `spec`、`note` 與 `authorization_review`。新任務保留所有仍有效的
來源限制，將目前權限與原根目錄上限取交集；根目錄只可維持或縮小，其餘權限、模式／模型、預算及
完成條件固定。核准證據與唯一新任務在同一交易保存；來源及已撤銷的見證不變。既有共用介面均提供
這兩種操作，GUI Actions 另有授權審閱／建立命令，詳見[恢復指南](../../source/Zh/doc/ai_agents/agent_recovery_doc.rst)。
任務恢復不解除輸入隔離，也不重建應用狀態；技能與 trigger 使用上方獨立更新流程。

停止的任務可用 `manage_agent_recovery("preview", {"task_id": "..."})` 審閱來源收據與快照，
不接觸應用程式。有限 skill 提供剩餘動作及逐筆結果；外部 agent／本機模型任務則提供空白目標的
`review_template`，須由操作人明確填寫剩餘工作目標，不複製舊動作清單。明確 `create` 時提供
快照、經審閱的規格與註記，建立有來源關聯的新任務，重新觀察並從零收據開始；重複核准回傳同一
任務。執行模式、模型／端點、範圍、預算及完成條件固定，未知副作用須先人工核對；不移植舊
capture、索引、座標或已完成歷史。可用 `AC_agent_task_recovery`、MCP／REST、
`agent-task recovery preview|create request.json`，或「Agent 任務 → Actions → 審閱剩餘工作／
重新規劃／建立經審閱的新任務」。已移交的來源不能再恢復，須由新任務繼續。
登入與視窗狀態的恢復須明確宣告，不能推論：繼任任務（或任何任務）可列出 `resume_conditions`，只接受
`screen`、`browser` 與 `file_*` 條件（收據是歷史，不能證明現況）；第一個動作只在新觀察全部通過時
才被接受，任一不成立或無法判定就轉為 `waiting_user`，不會動作；有任何動作收據後此關卡即結束。

Android／iOS 內建受管 profile 仍未提供。內部遠端副作用防護會依實體裝置識別保存動作前／後確認；
本機 helper 結束但動作未確認時，仍保留隔離。恢復須在 writer 退出後取得可信裝置證據，並以
後續能使舊指令失效的世代證明安全。尚無內建 SDK 證據來源、裝置 profile 或原生驗收；
剩餘接合列於 `Progress.md`。
內部 Android 傳輸只連明確設定的既有 loopback ADB server，不呼叫 CLI、不管理 daemon、
不重試或退回舊 shell；shell-v2 的退出證據有封包／輸出上限，但不代表應用完成、實體裝置
身分或輸入已釋放。
內部 Android session 會核對指定端點、實體序號、boot 與預設顯示器焦點，並以原子方式固定
boot。有限輸入提案在命令連線內重驗身分／焦點，限制文字與結果；提案不授權輸入，仍須接合
輸入視窗、遮擋、鎖定／真人活動與自有 worker。
Android 檢查後提案會綁定目前的原生輸入視窗／佇列及 keyguard 證據，核對完整觸控路徑、
外部攔截與遮擋，並在命令連線內重驗摘要。舊 ANR／歷史紀錄不能證明目前狀態；真人活動、
全域監看器審閱仍須可信來源授權，內建受管裝置執行仍未開放。
內部 Android 動作協定 v2 區分完整前置拒絕、輸入失敗、輸入後拒絕與輸入返回。
缺少／錯誤階段或退出碼不符都維持未知；輸入返回不代表遠端輸入已清空或任務完成，也不授權重試。
內部自有遠端 SDK worker 會核對精確任務／擁有者範圍、重新授權與真人接回；可信主機 factory
建立前先啟動 parent 監看。持久化 begin 並收到 ACK 後才呼叫 SDK，相符裝置／世代的清理證據
通過後才送 end；缺證據維持隔離。可信裝置控制來源、WDA adapter 與受管 profile 仍待接合。
命令編譯器以一次帶標籤的擷取核對三個原生焦點欄位，接受六種順序，缺少／重複／空值仍拒絕。
前後身分與輸入安全檢查、原本動作期限均保留。自有 POSIX 假裝置減少 Git Bash 讀取程序且維持
原始檔案 bytes；有限階段／耗時診斷不含命令、參數或輸出。
內部 AndroidRemoteAdapter 已透過逐命令 AndroidCommandLease 接合 checked session 與 worker；
每個動作消耗一次新的身分／輸入路由／安全觀察，SDK 重新編譯有限命令後才透過 ADB 送出一次。
裝置端防護須在真人接回、取消或到期後阻止舊寫入；沒有預設 provider，標準 ADB 或停止本機
helper 不能提供這項保證。清理證據還須綁定新的隨機命令 ID、boot 及獨立輸入／佇列狀態。
可明確配置主機 hierarchy_reader，提供有界、限 app 的語義元素及經審閱的非敏感文字；未配置時
仍只有身分 metadata。XML 不授予文字權限；編輯／密碼值及受保護子節點持續遮罩，不發布原始
XML 或私有 freshness hash。公開觀察版本隨來源及動作更新；Android 元素參照須來自目前可操作
的語義元素。新的畫面讀回可確認已審閱文字出現，缺少／部分／遮罩內容不能證明文字不存在。
不新增 CLI／SDK 啟動或擷取備援；真實來源、受保護欄位值驗證、Unicode／IME 與受管 profile 仍待交付。

受管畫面完成驗證將內建桌面與 WebRunner 預覽視為部分文字證據；檔案目標與等待視窗階段沒有
語義畫面證據。已知安全文字可確認出現或推翻不存在條件，遮罩與明確隱藏的標籤不可作證。
組合條件缺少任一必要證據時保持未知，已知矛盾則判定失敗。精確 DOM／欄位值應使用明確的
瀏覽器完成讀回；未宣告覆蓋旗標的自訂 target 保留既有行為。

`lookup_agent_task("鍵", reviewed_spec)` 可選擇由目的地主機正規化規格，與原擁有者提交時保存的
不可變摘要比對；回覆宣告 `spec_match_contract=1`，並提供一致／不同／無法核對／查無紀錄。
CLI 可加 `--spec reviewed.json`；AC／MCP／REST／Builder 共用可選物件。DAG 檢視先查鍵，再於
目的地明確支援契約時核對已審閱的節點規格；舊端維持 `unverified`，本機來源 witness 不送到遠端。
鍵改指向別的任務會使舊快照失效；比對一致時仍須核對完成報告的種類、數量與通過結果。
節點比對不等於整張 DAG 拓樸／原批次批准，
`resume_permitted=false` 仍保留明確續接審閱。

`inspect_agent_dag(definition, timeout_seconds=30)` 可檢視本機／已登錄遠端主機的既有提交，
不提交、不暫停、不續跑。提供 `AC_agent_dag_inspect`、MCP、REST 動作、CLI
`agent-task inspect-dag reviewed.json`、Builder 與 DAG Actions。最多 100 節點、最長 300 秒；
遠端仍須主機管理權限，不傳送本機身分／資料庫路徑／來源 metadata，不回傳遠端路徑或原始錯誤。
`recorded_completion` 只描述查回的任務；節點規格可選擇核對，`resume_permitted=false` 仍表示尚未
授權整張 DAG 續接。查無紀錄不代表拒絕；GUI 在圖形編輯後捨棄舊檢視。

提交回覆遺失時，可用 `lookup_agent_task("原去重鍵")`、`AC_agent_task_lookup`、MCP、
`POST /agent/lookup`、CLI `agent-task lookup 原去重鍵` 或任務視圖 Actions 查詢。只讀取原身分及
使用者資料庫範圍，不提交、不續跑、不取得輸入控制權；`found=false` 只是當下快照，晚到請求仍
可能被接收。GUI 不會讓舊查詢回覆覆蓋後來選取的任務／鍵。DAG 檢視亦沿用此查詢；規格綁定及續接審閱仍待完成；
唯讀查詢仍須具任務存取權限。

既有 `run_dag`／`AC_run_dag`／MCP `ac_run_dag`、REST／CLI 動作檔、Script Builder 與 DAG
Actions 選單支援受管任務節點：以 `task` 取代 `actions`／`action_file`，內容包含 `spec`、必填的
`idempotency_key` 與可選的 `wait_seconds`。省略 `host` 使用明確啟動的本機服務；遠端使用管理員
已登錄的主機。該端須已配置有背景派送的授權 runtime，本功能不部署服務。規格限 skill 或明確
配置的本機模型模式，工具、目的地主機路徑及完成條件由該端驗證。
節點只提交一次，等待完成條件通過、持久完成契約及輸入釋放證據後才啟動下游。同一批次恢復
須保留去重鍵；不自動恢復暫停任務或重播副作用。停止、逾時或通訊／權限失敗時，已知任務 ID
才會提出有時限的暫停；未收到確證仍為未知。失敗結果保留 ID／去重鍵並阻擋相依節點，GUI
表格顯示任務 ID。本機身分、使用者資料庫路徑及來源 witness 不送到遠端。正式多機部署及原生／
裝置驗收仍分開追蹤。

DAG 型別與函式亦可由 `je_auto_control.api`／`je_auto_control.api.core` 匯入。

受管 HTTP 暫停／取消／停止全部／關閉服務使用獨立的每 IP 配額，與一般流量同為每分鐘 120 次、
突發 30 次；狀態查詢不會耗盡停止請求的配額。登入、即時角色、任務歸屬、稽核與有界輸入清理仍須
通過。共用客戶端也為 DAG 批次／節點暫停保留傳輸容量；`/agent/dag` 的控制標頭僅接受封閉的暫停
請求，其他帶標記的操作在派送前拒絕。自訂驗證閘門保留自己的契約；這不保證 OS／網路飽和時的優先權。

受管任務在確認輸入清理後才發布成功。清理失敗或仍忙碌時保留輸入租約並要求審閱；確認前
中斷仍需恢復。完成發布採條件式狀態轉換，不覆寫同時到達的取消要求。既有 GUI／API 任務
結果以 `metadata.input_released` 顯示釋放狀態；新成功紀錄保存 `completion_contract=1`，舊紀錄
維持零而不自動認證。成果報告依最終狀態更新，供後續 DAG 協調判定。

DAG 節點在執行緒池中保留呼叫者授權、取消與指令限制，自訂 runner 亦適用。每個節點執行前
重新讀取使用者權限；已刪除的使用者會使節點失敗，後續相依節點略過，各操作依更新後的角色
檢查權限。預設遠端節點在開啟主機通訊錄或動作檔案前要求 `manage_hosts`，避免透過主機憑證
擴大本機操作權限。管理員及受信任的直接 Python 呼叫仍可遠端派送。受管節點沿用上述完成
驗證與停止契約；正式多機部署及原生驗收仍待完成。

瀏覽器主機目標可透過可選的 `settings.helper_python` 指定已審閱且已安裝套件的 Python
環境（本機絕對直譯器路徑）。明確指定的 helper 使用 `-I`，從該環境載入已安裝套件；虛擬環境
直譯器的符號連結保留環境身分。任務選項不能指定直譯器。
主機管理者可使用 `manage_agent_target("probe", {"name":"reviewed-browser"})`、`AC_agent_target`、
MCP／REST、`agent-task target probe request.json` 或 GUI 主機目標的診斷操作。
診斷以獨立且有時限的自有 helper，透過 `je_web_runner` 檢查瀏覽器依賴後結束，過程不取得輸入
擁有權或啟動瀏覽器。結果可顯示 `python_dependencies_ready`；瀏覽器啟動及原生證據仍明確保持
`not_probed`／`not_recorded`。`last_probe` 僅為記憶體中的具時間診斷快照，不授予任務權限，
也不啟用停用的目標。桌面／裝置的原生診斷仍待完成。
已準備的隔離環境安裝兩個功能工作樹建置的 wheel；共用環境與正式工作樹保持原狀。正式服務
設定及實際瀏覽器驗收仍分開追蹤；所有瀏覽器自動化仍統一由 WebRunner（`je_web_runner`）提供。

桌面固定技能現在與瀏覽器技能共用工作階段連續性檢查。桌面 scope 或自有 helper 結束後，
沿用舊前綴前必須審閱，不能用歷史紀錄證明暫停後的表單／視窗狀態。未中斷的工作階段可正常
執行；檔案 adapter 仍以持久化產物處理復原。檢查在替代 helper 啟動前執行，既有續跑／狀態／
紀錄介面會顯示人工審閱結果。暫存表單／登入／視窗狀態恢復與可審閱的剩餘步驟重建仍待完成；
原生驗收維持暫停。

固定瀏覽器技能的已驗證前綴，現在必須保有原本仍存活的瀏覽器／helper 工作階段。
暫停、清理、helper 中斷或 runtime 重啟後，舊動作紀錄無法證明表單仍保有先前欄位值；
續跑會在啟動替代 helper 或送出下一動作前進入人工審閱。請明確檢視剩餘步驟並建立新任務。
尚無保留嘗試紀錄的暫停，以及已審閱為 failed／not_applied 的嘗試，允許全新開始。
外部擁有者仍可重新觀察新工作階段，再規劃授權範圍內的新動作；未中斷的固定技能沿用原
工作階段。登入及暫存表單狀態的恢復仍是未完成工作。

本機 runtime 的使用者及即時根目錄授權轉送，現在必須由明確的本機服務呼叫啟用。
一般具驗證的 HTTP 請求只帶指定的 Bearer token；runtime client 驗證 loopback 服務目的地與
路由後，才附上本機使用者／來源儲存庫／witness 資訊。版本化 `je_auto_control.api` 現在提供
所有已宣告的 `api.core` 名稱，包含受管瀏覽器命令、目標復原及技能；動作型別 stub 也涵蓋
所有出貨命令。未解析的延後專案型別沿用產生器既有的 `Any` 政策，避免產生無效名稱。
並行預算讀取改在資料庫獨佔交易內取樣時鐘，避免鎖取得順序不同造成任務誤判逾時；真正的
時鐘倒退仍會停止任務。GUI／MCP／REST／CLI 共用這些修正；正式工作樹及既有原生／瀏覽器／
裝置／24 小時驗收暫停維持原狀。

受管瀏覽器檔案命令 `browser_link`、`browser_download`、`browser_upload`（對應 `AC_browser_*`）
委派給 WebRunner 傳輸契約版本 1。上／下載授權必須具有明確的主機及任務根目錄；下載讓瀏覽器
Cookie 保留於自有 SDK／helper，核對完整長度及可選 SHA256，且不覆寫既有檔案；重用必須符合
指定 SHA256。上傳將最多 4 MiB 的單一一般檔案讀成核對過的不可變快照，驗證可選 SHA256 與
SDK 中繼資料，不自動提交表單。網路操作仍全部位於 `je_web_runner`。
瀏覽器 `download_archive` 預覽接受查詢頁 `url`、明確 `allowed_origins`、授權範圍內 `directory`，
以及具有單純 `name`、`url` 或連結 `selector`／可選 `frame` 的 `files`；每檔可用 `page_url` 覆寫
查詢頁。流程擷取新連結、下載每檔最多 16 MiB，並產生供獨立核對名稱／大小／雜湊的歸檔清單。
GUI Actions 只草擬檔案目標／流程／上傳範例，不啟動資源；MCP／REST／CLI／Builder／模型工具
共用命令，連結讀取仍需輸入控制權限。部署與實際瀏覽器驗收仍待完成，既有驗收暫停保持生效。

瀏覽器任務可固定完成條件，例如
`{"kind":"browser","operation":"value","selector":"#field","value":"expected"}`。
操作為精確的 `text`、`value`、`visible`（布林）或 `url`（不含定位）；必須明確授權
`AC_browser_read` 與任務 origins，完成條件不會增加權限。Finish 由同一個自有 helper 檢查
目前頁面位於允許的 HTTP(S) origin，再透過受控讀取命令獨立取得 SDK 完整值；既有 receipt、
有界預覽或模型停止訊號不能代替讀回。空白／不可用／範圍外頁面、被拒讀回或錯誤驗證回覆
保持未知；比較不符保持失敗。取消、權限撤銷及人工審閱錯誤保留原類型。
GUI Actions 可草擬不啟動資源的瀏覽器完成範例；API／MCP／REST／CLI finish 共用驗證器。
SPA URL fragment 會保留，origin 比對僅略去 fragment。實際瀏覽器／應用驗收及已審閱傳輸仍待完成。

受管瀏覽器啟動前，必須先確認 WebRunner 的 `ManagedBrowserSession.contract_version == 1`，
通過後才建立 policy 或開啟代理／瀏覽器。缺少、布林、文字、過舊或未知標記會保留可處理的
就緒錯誤。SDK 來源 `575e5d2` 提供完整 text／value 讀回：最多 8,000 個 UTF-16 code unit，
超限或無效 Unicode 就拒絕，不截短。AutoControl 對瀏覽器參數與流程預覽資料套用相同 Unicode
上限，在副作用前拒絕。跨來源契約透過真正的自有 helper 與替身 Chromium 驗證；部署與實際
瀏覽器／原生驗收保持分列。


`draft_agent_workflow("batch_form", config)` 與 `transfer` 可設定 `backend: browser`，
並提供明確的 `allowed_origins` 與已審閱 browser target。CSV／XLSX 來源仍受 roots 限制；
瀏覽器草稿只產生 `AC_browser_*` 動作，不退回桌面輸入。填表提供 `url`、CSS `fields`、
可選 frame／新增資料控制項、送出與確認 selector；每次填入都有獨立的精確 value 讀回。
可用 `confirmation_column` 從每列取得預期確認文字。轉填提供 `source_url`／`destination_url`，
擷取 text／value、套用白名單轉換、填入並讀回目的欄位，再驗證儲存；送出前拒絕陳舊確認。
`AC_browser_wait`／`browser_wait` 只輪詢 text／value，也支援稍後才出現的元素；`wait_seconds`
預設 5 秒，受 action budget 限制，逾時才回來的相符結果仍拒絕，不重播填入或點擊。
Python/core、共用 catalog／模型 schema、MCP、CLI／REST 任務操作、Builder 及 GUI 流程預覽
使用同一編譯器。瀏覽器讀回可作為獨立技能證據。實際應用驗收與正式上／下載設定仍待完成；
SDK 啟動前須通過完整有界讀回契約版本 1 的檢查。

受管瀏覽器 profile（`kind: browser`）統一委派給 WebRunner 的 `je_web_runner` SDK；
開發來源為 `D:\Codes\WebRunner`，整合來源位於其隔離的受管 session 功能分支。
Profile 必須提供精確的 `settings.allowed_origins`、瀏覽器專用工具，且不能授權桌面 app；
每項任務另須設定非空、較窄的 `options.allowed_origins`，每次啟用均重新核對兩層範圍。
註冊不啟動資源；helper 環境須明確安裝已審閱的受管 SDK 與 Chromium，缺少時就緒失敗，不自動安裝。
`AC_browser_navigate`、`AC_browser_click`、`AC_browser_fill`、`AC_browser_select`、`AC_browser_check`
及 `AC_browser_read` 共用 Python/core、executor、MCP 與 Builder 定義。命令只在受管 helper 中
運作，透過既有 task submit/observe/act 週期驅動。讀取操作為 `text`、`value` 或 `visible`；
WebRunner 拒絕秘密表單欄位。DOM 索引在目前 observation 內解析 selector／frame，再核對新鮮度。
失敗副作用保持不確定且需對帳；暫停／取消會結束擁有的資源。GUI Actions 可產生瀏覽器目標範例
供審閱；DOM 選取只編輯動作請求。專用 helper 跨就緒檢查保留同一個全新 session，正常清理先
取得瀏覽器 ACK，再結束自己的程序樹；符合完成審閱條件的來源則將原本已凍結的 context
移交 runtime 有界保管。瀏覽器任務不取得共用桌面輸入控制權。跨來源受控測試使用真正 SDK、
替身 Chromium、自有 IPC／loopback；實際瀏覽器／原生驗收、正式傳輸設定及其餘瀏覽器流程種類仍列於 `Progress.md`。

MCP 非同步呼叫會保留接受請求時的角色、session、原路徑政策與工具清單；session 或路徑政策
結束後，延遲分派會被拒絕。非同步無狀態呼叫仍使用固定 profile。外掛工具清單變更會送達所有
有效 HTTP session 串流；session 啟停只通知擁有者，並避免重複發送。串流註冊與 HTTP 標頭
共用鎖，避免提早送出的通知破壞 HTTP 回應。
純 metadata 的 `benchmarks/mcp_discovery.py --repeats 20` 量測工具數、JSON bytes、暖機後的
程序內交握、搜尋與啟用耗時。Windows／Python 3.14.4 的紀錄中，完整模式初始有 732 個授權工具、
358,029 bytes；逐步模式為 5 個、2,029 bytes，回應大小減少 99.43%。交握為 58.263／47.439 ms，
搜尋中位數為 16.243／19.718 ms；逐步啟用中位數為 42.486 ms。此本機量測不含冷啟動匯入及原生操作。
有日期的 JSON 紀錄位於 `docs/benchmarks/`；既有參數政策的涵蓋限制仍列於 `Progress.md`。

MCP 可選擇 session 逐步揭露：`je_auto_control_mcp --tool-mode progressive` 初始只提供五個
探索控制工具；`ac_mcp_tools_enable`／`ac_mcp_tools_disable` 只改變該 session。
不會更新工具清單的客戶端可使用 `--tool-mode static --tool-profile ac_screen_size,ac_list_windows`；
預設 `full` 保留不分頁的授權工具清單。逐步／固定模式的 cursor 不透明、只能使用一次，並綁定
快照與呼叫者；工具、角色或清單設定變更，以及 cursor 過期時，須重新執行 `tools/list`。
啟停只通知擁有者連線；session 結束會回收 cursor 並使尚在執行中的 metadata callback 失效。
HTTP／嵌入式使用 `MCPServer.configure_tool_disclosure(...)`；主機環境變數為
`JE_AUTOCONTROL_MCP_DISCLOSURE` 與逗號分隔的 `JE_AUTOCONTROL_MCP_TOOL_PROFILE`。
`plan_mcp_tool_profile(...)` 及 Diagnostics Actions 可預覽啟動參數，不會啟動服務。
無狀態協定使用不分頁的初始固定清單，不保留 session 啟用狀態。唯讀限制也涵蓋後續新增的外掛。
未驗證／共享 token 連線顯示 operator 工具，與既有呼叫上限一致；主機管理工具仍須已驗證身分。

MCP 工具探索提供 `search_mcp_tools(query, limit=10)`、`get_mcp_tool_schema(name)`、
對應 AC／MCP 指令及 Diagnostics → Actions。搜尋回傳有界摘要、分類與所需權限；完整 schema
須指定單一工具查閱。兩種查詢都重新驗證角色，並遵守 registry 的唯讀篩選；MCP 查詢使用該
server 的即時 registry，包含外掛變更。CLI 可執行
`je_auto_control_mcp --search-tools document --limit 5` 或 `--tool-schema ac_mcp_tool_search`。
完整模式仍為預設；各 session 的逐步揭露可依前述設定啟用。

Agent 工具呼叫經 `executor.execute_one(name, arguments)` 回傳原始結果，與動作腳本共用
授權、變數插值、取消及日誌邊界；拒絕私有 executor 參數。受管任務交付進度見 `Progress.md`。

輸入控制權會在分派及輸入確認前寫入持久紀錄。服務崩潰後，先手動放開按鍵與滑鼠按鈕，再以主機管理權限呼叫 `recover_agent_target(target, note)` 記錄審閱並恢復目標；任務未知結果仍須另外核對。工作區文件由輸入 helper 之外的程序啟動，指定的聚焦步驟會等待授權應用程式視窗就緒。

受管技能將已驗證的語義流程錄製為不可變候選。`manage_agent_skill` 可預覽具型別的參數、執行獨立驗證任務，並在明確審閱該候選的成功證據後發布編號版本。定位器修復會產生須重新驗證的候選；任務固定使用原版本與摘要。AC／MCP／REST／CLI 與 Agent Tasks 的 Actions 選單提供相同操作。

原驗證試跑的動作若已全部確認，可明確審閱／建立並完成獨立唯讀驗證任務，再以
`manage_agent_skill("accept", {...})` 提供原 `task_id` 與可選的 `completion_task_id`。
發布保留精確候選／試跑摘要與 pin，核對最多十六層真實唯讀復原鏈、即時權限及獨立完成／清理證據。
原試跑維持停止，動作不重播；Actions 選單可準備待審閱請求。發布紀錄在暫存 reader 證據到期後
仍保留歷史 ID／摘要；尚未發布的採認仍須有留存證據。

停止的原流程也可透過 `manage_agent_skill("record", request)` 明確提供 `completion_task_id`。
`task_id` 仍指原流程，草稿保留其已確認語義動作，另採認唯讀 reader 的私有獨立完成證據。
錄製不重播動作、不改來源狀態；來源／證據檢查與草稿寫入共用交易，並重驗即時權限。
`provenance.completion_review` 在 reader 保留期後只是歷史紀錄，不授予當前權限。
草稿與新增驗證條件仍須自己的新驗證試跑，不能直接發布；Actions 選單只準備錄製請求。

原驗證試跑只執行部分動作時，先呼叫 `manage_agent_skill("review_execution", request)`，
提供 `candidate_id`、原 `task_id` 與另一個最終 `execution_task_id`；再以相同 ID、返回的
`execution_review`、`expected_version` 及非空 `note` 明確 `accept`。最多十六層真實可執行復原鏈
必須確認完整原語義計畫；不同的剩餘流程即使成功也不足。比對包含 JSON 型別、capture 值、預期結果
與 grounding，但不恢復舊 capture 或重建歷史 UI 狀態。各任務保留原限制與獨立批准；當前 caller、
全部 owner 及實際建立審閱者都須持續有權限。版本、發布及歷史 `publication.execution_review`
共同提交或回滾，寫入後再查證據與權限。原試跑維持停止並保留 `publication.task_id`，不補造子任務
為 validation trial。可選 `completion_task_id` 必須驗證最終可執行任務的效果，其證據巢狀存於
execution 審閱紀錄；過期證據不能批准未發布候選。兩個 Actions 範例只準備審閱／接受請求，
`agent_skill_execution_review.json` 與 `agent_skill_execution_accept.json` 可編輯後使用。

受管任務保留來源路徑政策：移除根目錄後，後續動作、事件觸發及技能驗證會受阻。MCP 客戶端根目錄依連線階段隔離，來源授權結束後撤銷；主機設定的固定政策則在明確更換前保留。服務停止會取消實際執行中的工作，包含取得輸入前的模型初始化，尚未啟動的派送則持續保存。

實驗性的[受管 Agent 任務](../../AGENT_TASKS.md)提供擁有者範圍內的提交、觀察、動作、驗證、
暫停、恢復、取消、控制權世代、持久化回執、WorkQueue 派送與本機 Ollama 推論。
Python、AC、MCP、REST、CLI 與 Agent 任務面板共用背景服務，明確執行
`je_auto_control agent-task start` 才啟動；新流程不強制依賴外部服務。
四條可預覽範本涵蓋下載歸檔、CSV/XLSX 填表、跨應用轉移與工作區準備；
使用 `agent-task draft` 或 Actions 的「預覽工作流程」檢查後提交。
持久化間隔、Cron、檔案與事件綁定會保留核准範圍，每次觸發重新授權並去重；
提交識別碼避免重試與重啟時建立重複任務。
提供擁有者範圍內的回執與結果不明對帳，連結執行歷史、journal 及逐筆報告；
服務快取預設保留 30 天，保留使用者輸出與外部 journal。
證據快取以完整資料庫路徑及持久資料庫身分綁定於 `.agent-evidence-cache/`。
還原的資料庫與舊版快取保留原歷史參照；下次動作或報告建立新的自有 journal 分段，
不讀取或搬移歷史檔案。任務 metadata 的 `artifact_cache_state` 為 `owned` 或 `historical`。
保留清理只移除目前資料庫可辨識的自有快取檔；歷史檔案保留，留存的私有根目錄禁止成果匯出。

Linux 上的 helper 程序可改由選用的 [owner 服務](../../../native/owner_service/README.md) 執行：
root guardian 把每個 helper 放進它自己的 cgroup v2 樹，helper 帳號無法離開；關閉 channel 會
結束整棵樹（含逃離的後代），guardian 重啟後會清理崩潰留下的程序。root 擁有的
`/etc/je_auto_control/owner_service.json` 綁定檔只讓完全列出的 helper argv 經由服務啟動；
驅動桌面或瀏覽器的 helper 一律以本機程序執行，因為受保護的 helper 以獨立 ID、空環境執行，無法存取顯示；
沒有綁定檔時 helper 仍以本機程序執行，`agent-task status` 在 `helper_containment` 回報模式。
Python 套件不會建置、安裝或啟動服務，且在審閱後的版本開啟閘門前，建置出的服務拒絕受保護啟動。

`agent-task readiness`（`agent_runtime_readiness`、`AC_agent_runtime_readiness`、MCP 工具及 Agent 任務面板的
Actions 選單）回報桌面輸入與擷取、真人在場來源、Android 與 iOS 控制、瀏覽器和本機模型各自的狀態：
`unsupported`、`missing_dependency`、`unauthorized`、`not_probed`、`not_recorded` 或 `measured`。它只讀環境變數、
`PATH` 與已安裝套件，不連線裝置、不啟動 helper、不要求權限，所以不會回報 `measured`，每一項的
`native_evidence` 都是 `not_recorded`；已安裝的工具只算 `not_probed`，不代表可用。

部署或回復前須比對來源與成品雜湊，不能只憑相同版本號判斷私有快取相容性。
不具此私有根目錄保護的舊程式不得沿用新版資料庫／快取。經審閱的回復須使用相符的升級前狀態
及其原記錄位置，先取得自有輸入退場確證，並從所有舊版任務根目錄排除留存的新版私有檔案；
保留不明 journal，不重播副作用。無法核實時維持相容版本。

Windows USB 列舉明確以 UTF-8 輸出及解碼，PowerShell 子程序維持隱藏。
Python UTF-8 模式開啟或關閉時，Unicode 裝置名稱與診斷均完整保留；列舉仍為唯讀。
原生呼叫使用專屬 helper，支援取消、逾時、輸入記錄清理與跨資料庫的桌面排他控制。
Windows 共用桌面的持續來源跨 runtime／任務／helper 共用，監看開始後須重新累積解鎖閒置 60 秒。
僅支援已確認的作用中本機 console；遠端、shadow 及不明 session 一律拒絕。
每個 helper 在輸入 ACK 前後即時查核同一主機租約；來源／reader 失效會暫停輸入，
未確認的按住輸入清理仍保持隔離，須明確重試。關閉一個 runtime 不會停止其他 runtime 的來源。
目標說明只公開粗略 `presence` 狀態與 `native_evidence=not_recorded`，不啟動探測。
`agent-task stop-all` 停止可見任務。
其他共用桌面須有可信活動 adapter。原生平台驗收與其餘待辦列在 `Progress.md`。

Linux 內部 presence_peer_linux 以不可繼承的 pidfd 保留原始 Unix stream 或 seqpacket 連線者，
查核帳戶、程序建立時間、namespace 與存活狀態，不另依 PID 開啟程序。程序身分不代表桌面或輸入權限。

內部 LinuxListener 與 LinuxChannel transport 擁有受保護的 Unix endpoint、socket 與 peer。
每個有界 JSON 封包須有仍存活的原始 writer 的核心憑證與 pidfd；額外、遺失、負值或截斷的控制資料
直接拒絕，收到的描述元在交付前釋放。排隊與 I/O 共用同一期限；取消撤銷交付，尚未完成或失敗的
清理維持未確定。未知檔案系統物件保留不動。路徑權限不能隔離同 UID 的敵對程序，使用者空間的有界
等待也不保證核心 syscall 的硬即時完成。

X11 與 macOS 已有真人活動來源。X11 只計入真實裝置的 XInput2 raw 事件（XTEST 從屬裝置一律排除），
並從 logind 讀 `Active`／`LockedHint`；沒有 logind 或 `XDG_SESSION_ID` 時視為鎖定。macOS 用唯讀的 session
event tap（需要輔助使用權限）；只有程序從非 HID 來源狀態送出的事件才算注入，有疑義時讓任務等待而不是接手。
Wayland 沒有可信來源。Linux 的 presence broker、worker 與 server 已改經此 transport：自有 worker 綁定
全新的私有 endpoint 並在 bootstrap 回覆中回報，broker 只採用該 endpoint，連線時先核對 listener 即其所列
程序，再做 presence challenge。macOS 尚無 presence transport；原生驗收前 runtime 仍拒絕非 Windows 共用
桌面任務；此 transport 不是完整 Linux 應用或原生輸入驗收。

[![PyPI](https://img.shields.io/pypi/v/je_auto_control)](https://pypi.org/project/je_auto_control/)
[![Python](https://img.shields.io/pypi/pyversions/je_auto_control)](https://pypi.org/project/je_auto_control/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../../LICENSE)
[![Documentation](https://readthedocs.org/projects/autocontrol/badge/?version=latest)](https://autocontrol.readthedocs.io/en/latest/?badge=latest)

**AutoControl** 是一套開源、跨平台的 **computer-use 與 GUI 自動化框架**，面向 AI agent、Python 應用程式與自動化測試。它能驅動滑鼠與鍵盤、透過樣板比對、OCR、作業系統無障礙樹或視覺模型找到 UI 目標、錄製與重播流程，並以 JSON 動作檔執行——支援 Windows、macOS、Linux（X11 與 Wayland）、BSD、Android 與 iOS。

每項能力都以三種形式提供：**Python API**、可在 JSON 檔／CLI／伺服器使用的 **`AC_*` 動作指令**，
以及 **GUI 分頁**。沒有任何功能只存在於 GUI。

**[English](../../../README.md)** · **[简体中文](../../../README/README_zh-CN.md)**

---
