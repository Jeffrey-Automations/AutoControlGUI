# Completion evidence and handoffs

[README](../../../README/README_zh-TW.md) · [Documentation](../../README.md)

## Local DAG 完成證據的明確移交

其他 caller 持有的既有復原子任務，可透過明確且可撤銷的移交，向原 local DAG 提供完成證據。
以 `manage_agent_recovery` 的 `review_handoff` 提供最終 `task_id`、`batch_id`、`node_id`，
有權管理者再用相同 ID、將返回的 `handoff_review` 填入 `review`，並附非空 `note` 執行
`create_handoff`。接收者由服務依真實原始 admission 決定。在 `review_continuation` 的 successor
決策中，除 `node_id`、`action`、`task_id` 外明列 `handoff_id`，再審閱並批准整份 continuation。
最多支援十六層真實復原鏈，包含經私有 admission 的永久唯讀最終驗證者；一般任務歸屬維持原樣。

`get_handoff`／`revoke_handoff` 使用 `handoff_id`；`list_handoffs` 使用 `batch_id`、`node_id`。
建立與採認時重查實際 owner、建立審閱者、簽發 session 的來源根限制、當前接收端限制、固定 scope、
效果快照、獨立完成及資源退役。批准、開始及後續相依驗證都重查同意；撤銷或證據遺失會阻止採認。
期限不超過最早終止見證既有的三十天保留期限。公開回應只含有限 ID、摘要與狀態，不含私有參數、
capture 或 principal 資料庫路徑；不授予一般任務讀取／輸入權、不移轉歸屬或重播。
跨主機及非 DAG 的移交契約仍列於 `Progress.md`。

Agent Tasks 的成果移交頁提供操作選單與 JSON 編輯器；Actions 只準備審閱、建立、撤銷請求，
不自動派送。五個可編輯的 `agent_handoff_*.json` 範例涵蓋 review/create/get/list/revoke。
Python、AC、CLI、具名 MCP、REST、Builder 共用這些 recovery 操作。本次證據涵蓋契約及自有檔案
流程；暫緩的原生桌面、瀏覽器、裝置及二十四小時驗收仍須各自提供證據。

## 明確續授權唯讀完成驗證

原來源的 origin 參照過期或不可用時，明確呼叫
`manage_agent_recovery("review_completion_authorization", {"task_id": "<source-id>"})`。
審閱服務產生的 `verification_spec`、保留／替換／當前 origin 限制，再以相同 `task_id`、返回的
`snapshot`、`authorization_review` 及非空 `note` 呼叫 `create_authorized_completion`。
可選 `owner_policy="source_owner"` 在建立時另須返回的 `ownership_review`；不能自行提供新驗證
規格。仍有效的舊限制保留，新根目錄與原上限、前一讀者上限及當前 session 取交集。
已重新授權的讀者不能改用一般完成審閱來移除這些限制。

子任務永久唯讀，依真實已確認的原效果獨立檢查當前條件，不輸入、不重播、不恢復 capture，
也不修改舊見證。來源／效果快照、實際 owner／reviewer 及原 DAG admission 都會重查。
建立任務與最終完成各自在自己的 SQLite writer 內寫入後重驗，變更時共同回滾。
最多支援十六層真實復原鏈；已退役且成功的讀者可再次明確續授權，但保留前次較窄上限及所有仍有效
的繼承限制。來源／效果證據已改變時仍拒絕，不能藉由 scope 續授權默默修復舊證據。

歷史 `get` 保留 succeeded 狀態；新授權失效時，當前 `completion_contract` 為零、
`completion_authorization` 為 unavailable，DAG 採認與後續相依驗證會拒絕這份證據。
新的唯讀標記損壞／遺失時，在 helper 啟動前拒絕。以 `completion_task_id` 錄製時沿用原語義動作及
已審閱的限縮 scope，但草稿仍須自己的新驗證試跑。此流程不發布過期候選，也不續授權已發布技能；
既有技能重新授權流程維持分開。

Python、AC、CLI、具名 MCP、REST、Builder 共用兩個操作；Recovery 頁的兩個明確 Actions
沿用所選任務、owner policy 與請求編輯器。可編輯範例為 `agent_completion_authorization_review.json`
與 `agent_completion_authorization_create.json`。remote 唯讀來源、跨主機移交、
實際應用狀態重建，以及暫緩的原生／裝置／瀏覽器／二十四小時驗收仍列於 `Progress.md`。

## 明確移交已續授權讀者的完成證據

既有 `review_handoff`／`create_handoff` 現在可明確將已重新授權、永久唯讀讀者的完成
證據交給實際原 local DAG。指定該讀者的 task ID 與原 batch／node，由服務推導證明；不能自行提供
policy、擁有者覆寫或授權 bundle。一般成果移交沿用既有規則。

預覽的 `evidence.completion_authorization` 顯示完成任務／審閱、固定的審閱摘要、根目錄數量及
替換／保留／當前 origin ID，不含私人 principal 路徑、動作參數或 capture。建立時以最上層返回的 `handoff_review`
作為請求的 `review`，並提供非空 `note`。每個真實任務都保留已審閱的上限與所有仍有效的歷史限制；不可用的
參照須明確審閱替換，發出移交當下額外的 session 限制也持續有效。移交沿用讀者已實際驗證的相同
根目錄；交集改變時須重新審閱及執行唯讀完成驗證，接收者的 session／profile 限制也會持續套用。

最多十六層真實復原鏈可混合先前已審閱的可執行子任務及私人讀者。成功的中間讀者必須具備實際
私人歷史 scope 與退役證明，一般已成功來源沒有這個例外。發出或採認移交時不啟動 helper、不重播
輸入；舊來源狀態、見證、收據及所有任務擁有者維持原樣。原擁有者只取得有限完成投影，不能因此
一般讀取其他 caller 的任務。撤銷或授權失效會阻止採認及後續相依驗證。

原 accepted-request hash、原始提交見證、私人 admission、graph、owner／reviewer、整條來源／子任務
快照與最後讀者的續授權都固定在證明內。讀取與寫入後重驗使用同一個 SQLite writer，包含尚未提交
的變更；發現變動即回滾任務／移交建立。繼承的 `dag_batch` 選項不等於 admission，必須沿有界真實
復原鏈找到原請求及實際授權身分，不補造 admission。舊的一般完成 binding hash 保持相容；各歷史
任務各自審閱限制，不能藉由合併歷史繞過正常十六個有效 origin 上限或原根目錄界線。

相同有效重試沿用原 note 與 ID，已撤銷 ID 不會重新啟用；重啟與採認保留最早終止見證的三十日期限。
origin 失效後仍可查 get／list 歷史與 revoke，但歷史不代表可用完成證據或輸入授權。Python、AC、
CLI、具名 MCP、REST、Builder 共用五個既有操作，Handoffs Actions 與 JSON 編輯器／結果區可顯示
明確續授權審閱，不自動派送同意。跨主機移交、remote 讀者、實際應用／裝置
來源及暫緩的原生／瀏覽器／真機／二十四小時驗收仍列於 `Progress.md`。

## 明確移交任務來源的完成證據

既有五個移交操作也接受真實非 DAG 來源任務：

- `review_handoff` 提供 `source_task` 與實際最後證據的 `task_id`。
- `create_handoff` 再以最上層返回的 `handoff_review` 作為 `review`，並填寫非空 `note`。
- `list_handoffs` 提供 `source_task`；`get_handoff`／`revoke_handoff` 仍使用 `handoff_id`。

任務來源與 DAG batch／node 欄位互斥，服務依實際保存的 grant 判定儲存類別。真實 DAG 祖先仍須走
原 batch／node 路徑，不能藉由已移除 `dag_batch` 的唯讀讀者繞過，也不補造 DAG 節點或 admission。
一般任務不必虛構提交見證或 idempotency key；實際存在的原請求須固定並在同一 SQLite writer 重驗。

既有技能操作明確選擇 `handoff_id`。`record` 以 `completion_task_id` 採認獨立讀者，建立的 draft
仍須自己的新驗證 trial；`accept` 使用完成讀者時，仍保留原 candidate 的真正驗證任務。
`review_execution` 與對應 `accept` 可選實際 `execution_task_id`；最後證據是獨立讀者時，再提供
`completion_task_id`。服務核對原本完整語義動作計畫、真實執行 ID 及獨立完成條件，不能把讀者
當執行任務或替代驗證 trial。

grant 只提供私人有限證據視圖，原擁有者、來源狀態與收據維持原樣，一般 get／list／observe／act／
resume 權限不擴大。發出或採認時不啟動 helper、不重播輸入。真實快照、可選原請求、實際 owner／
reviewer、退役輸入與有效歷史 origin 均持續核對；新錄製的 draft 保留發出與接收 session 上限。
失效限制須經真實私人完成續授權，不能靠相同 hash 或自填 scope flag 替代；唯讀採認也不會續授權
已發布技能原本的輸入權限。

來源祖先與後續移交鏈合計最多十六條真實復原連結。期限沿用最早終止證據的三十日，改錨定較新的
讀者不會延長舊祖先。DAG 與任務 grant 的 INSERT 後及相同重試都重驗撤銷墓碑；來源／請求／角色／
origin／撤銷變動會回滾 grant、draft 或發布。已撤銷 ID 不重啟，origin 失效後的 get／list／revoke
歷史只顯示有限 ID／hash，不代表持續有效的完成證據或輸入授權。

Handoffs 頁可明確選原本機 DAG 或原任務來準備 JSON；三個技能 Actions 準備帶 grant 佔位符的錄製、
發布與執行審閱，不自動同意或發布。Python、AC、CLI、具名 REST／MCP 與 Builder 共用相同操作及
真實 caller。`examples/` 提供 `agent_task_handoff_review.json`、`agent_task_handoff_create.json`、
`agent_skill_recording_handoff.json`、`agent_skill_completion_handoff.json`、
`agent_skill_execution_handoff_review.json` 與 `agent_skill_execution_handoff_accept.json`。

跨主機移交、remote 讀者、實際應用／裝置來源、暫緩的原生與二十四小時驗收，以及未解的
HTTP409／bootstrap 問題仍列於 `Progress.md`。

wheel 與原始碼發行套件包含 REST Dashboard 和 Swagger 的 HTML、CSS、JavaScript 資源。
安裝後的套件沿用相同的本機 REST 路由與授權規則；提供靜態頁面不授予任務或桌面輸入權限。
