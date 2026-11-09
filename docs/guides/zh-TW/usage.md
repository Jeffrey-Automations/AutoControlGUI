# Automation usage

[README](../../../README/README_zh-TW.md) · [Documentation](../../README.md)

## 為什麼選擇 AutoControl

- **一套 API，七個平台。** `wrapper/platform_wrapper.py` 在匯入時挑選後端；同一份腳本在
  Windows、macOS、X11 與 Wayland 上都不需要改寫。
- **不寫 Python 也能腳本化。** 911 個 `AC_*` 指令涵蓋全部功能，因此一個 JSON 檔能做到函式庫
  能做的任何事——包含迴圈、分支、try/catch、巨集與變數。
- **預設無頭執行。** `import je_auto_control` 絕不會載入 Qt。GUI 是選用套件，包在同一個無頭核心之外。
  公開匯出項目在被存取時才載入來源模組。`__all__` 與 `dir()` 可列出名稱，不必載入全部功能；
  萬用字元匯入會要求所有名稱。尚未解析的名稱不會出現在 `vars(je_auto_control)`。
  X11 的一般套件匯入不開啟顯示連線或輸入裝置，也不啟動鍵盤監聽。
  桌面操作在呼叫時才取得資源。讀取 `keyboard_keys_table` 或呼叫
  `get_keyboard_keys_table()` 會解析實際伺服器鍵碼，因此需要 X 連線。
- **四種定位方式。** 樣板比對、OCR、無障礙樹、視覺語言模型——可透過錨點定位器與自癒後備串接組合。
- **相依基線輕薄。** REST 伺服器、JSON Schema 驗證、JWT、TOTP、WebSocket 框架、ACME 用戶端、
  USB/IP 協定與 Prometheus 指標全部以標準庫實作；較重的相依都是選用。


## 如何選擇自動化層

AutoControl 不需要取代所有自動化工具；應該選擇最符合介面的那一層：

| 需求 | 適合工具 |
|---|---|
| 穩定的瀏覽器 DOM／API 自動化 | Playwright／Selenium |
| 簡單的 Python 滑鼠鍵盤腳本 | PyAutoGUI 或 AutoControl |
| 原生桌面應用程式自動化 | **AutoControl** |
| 無障礙樹 GUI 自動化 | **AutoControl** |
| OCR GUI 自動化 | **AutoControl** |
| 截圖／視覺模型 GUI 定位 | **AutoControl** |
| Self-healing 跨平台 GUI locator | **AutoControl** |
| AI agent 操作真實桌面 | **AutoControl + MCP** |
| 確定性的 JSON GUI workflow | **AutoControl** |

AutoControl 的差異在於把 **真實電腦輸入 + 語意／視覺定位 + self-healing + agent/MCP 整合** 放在同一個跨平台自動化介面。


## 60 秒上手

**1. 當成 Python 函式庫**

```python
import je_auto_control as ac

ac.set_mouse_position(500, 300)
ac.click_mouse("mouse_left")
ac.write("Hello World")
ac.hotkey(["ctrl_l", "s"])

x, y = ac.locate_image_center("save_button.png", detect_threshold=0.9)
ac.click_text("Submit")                       # OCR
ac.click_accessibility_element(name="OK")     # 無障礙樹
ac.click_by_description("the green Submit button")   # 視覺模型
ac.screenshot("shot.png", screen_region=[0, 0, 800, 600])
```

**2. 當成 JSON 動作檔** — `flow.json`

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
je_auto_control run flow.json --dry-run     # 只列出步驟，不會真的動滑鼠
```

**3. 當成桌面應用程式**

```bash
pip install je_auto_control[gui]
python -c "import je_auto_control; je_auto_control.start_autocontrol_gui()"
```

錄製一段流程、在視覺化 Script Builder 裡編輯，然後存成 CLI 能直接執行的同一種 JSON 格式。
（`python -m je_auto_control` 是舊式的動作檔執行器——`-e`、`-d`、`-c`、`--execute_str`——不會開 GUI。）

---

## 能力總覽

每一列都能無頭執行。「GUI 分頁」是同一功能在桌面應用中的位置；分頁的指令都放在視窗的
**Actions** 選單裡。

| 能力 | Python API | `AC_*` 指令 | GUI 分頁 |
|---|---|---|---|
| 滑鼠 | `click_mouse`（`clicks=2` 就是雙擊）、`set_mouse_position`、`mouse_scroll`、`tween_drag`／`drag_path`（以 `step_delay_s`、`settle_s` 控制節奏） | `AC_click_mouse`、`AC_tween_drag`、`AC_drag_path` | Auto Click |
| 鍵盤 | `write`、`write_secret`、`hotkey`、`type_keyboard`、`keyboard_key_name`（鍵碼 → 標準鍵名；Windows 也收 `ctrl`、`esc`、`enter` 等別名） | `AC_write`、`AC_write_secret`、`AC_hotkey` | Auto Click |
| 螢幕與像素 | `screenshot`、`screen_size`、`get_pixel` | `AC_screenshot` | Screenshot |
| 影像比對 | `locate_image_center`、`locate_and_click` | `AC_locate_and_click` | Image Detect |
| OCR 文字 | `click_text`、`wait_for_text`、`read_text_in_region`、`ocr_status` | `AC_click_text`、`AC_wait_text`、`AC_ocr_status` | OCR Reader |
| 無障礙樹 | `find_accessibility_element`、`click_accessibility_element` | `AC_a11y_find`、`AC_a11y_click` | Accessibility |
| 視覺模型定位 | `locate_by_description`、`click_by_description` | `AC_vlm_locate`、`AC_vlm_click` | VLM |
| 錨點定位 | — | `AC_anchor_click`、`AC_anchor_locate` | — |
| 自癒定位器 | `self_heal_run`、`self_heal_locate`、`self_heal_click` | `AC_self_heal_click` | Self-Healing |
| 自然語言規劃 | `plan_actions`、`run_from_description` | `AC_llm_plan` | LLM Planner |
| Computer-use agent | `AgentLoop`、`run_agent` | `AC_run_agent` | Computer Use |
| 錄製與重播 | `record`、`stop_record` | `AC_record`、`AC_stop_record` | Record |
| JSON 腳本 | `execute_action`、`execute_files` | 全部 911 個指令 | Script、Script Builder |
| 變數與流程控制 | `execute_action_with_vars` | `AC_set_var`、`AC_loop`、`AC_for_each`、`AC_try`、`AC_retry` | Variables |
| 資料驅動執行 | — | `AC_for_each_row`（CSV／JSON／SQLite／Excel） | Data Sources |
| 斷言 | `assert_text`、`assert_image` | `AC_assert_text` 等 21 個 | Assertions |
| 測試套件 | `run_suite` | `AC_run_suite` | Test Suites |
| 排程（間隔 + cron） | `default_scheduler` | — | Scheduler |
| 全域熱鍵 | `default_hotkey_daemon` | — | Hotkeys |
| 事件觸發 | `default_trigger_engine` | `AC_email_trigger_add` | Triggers、Webhooks、Email |
| 視窗管理 *(Windows、macOS、X11)* | `list_windows`、`focus_window` | `AC_focus_window`、`AC_snap_window` | Window Manager |
| 剪貼簿（文字 + 影像） | `get_clipboard`、`set_clipboard`、`get_clipboard_image`、`set_clipboard_image` | `AC_clipboard_get`、`AC_clipboard_set`、`AC_clipboard_get_image`、`AC_clipboard_set_image` | — |
| 遠端桌面 | `RemoteDesktopHost`、`RemoteDesktopViewer` | `AC_start_remote_host`、`AC_remote_connect` | Remote Desktop |
| USB 列舉與直通 | `list_usb_devices`、`enable_usb_passthrough` | `AC_usb_*`（16 個指令） | USB Devices、USB Share |
| 機密保險庫 | `default_secret_manager` | `AC_secret_set` + `${secrets.NAME}` | Secrets |
| 報表（HTML／JSON／XML） | `generate_html_report` | `AC_generate_html_report` | Report |
| 執行歷史 | `HistoryStore`、`manual_history_scope` | `AC_history_list`、`AC_history_capture` | Run History、Script Executor、Script Builder |
| 動作日誌 | `execute_journal_run`、`inspect_journal` | `AC_journal_capture`、`AC_journal_read` | Run History、Script Builder |
| 指標與追蹤 | `default_metric_registry`、`render_metrics_text` | — | — |
| 系統診斷 | `run_diagnostics` | `AC_diagnose` | Diagnostics |
| 測試碼產生 | `generate_code` | — | — |

自癒定位器會在後備或點擊前原樣傳遞取消。稽核記錄在寫入或回傳記錄前遮蔽本次執行已解析的秘密值；回傳的定位結果保留原值，讀取時不改寫既有紀錄檔。

即時 image／VLM 自癒現在共用一次延遲邏輯截圖及實際裁切原點，兩條路徑的 `screen_region` 均為 `[左, 上, 右, 下]`。Schema-v2 記錄增加 run／step 身份、內容與設定版本、frame hash、策略／截圖耗時及實際 backend／model，仍相容舊記錄。未設定驗證的點擊僅記錄已送出或失敗，驗證維持未知。GUI 提供區域輸入與所選記錄證據，Script Builder 保留結構化區域 JSON。舊 `healed`／`heal_rate` 統計定位候選，獨立的操作指標需要明確驗證。

實驗性 `self_heal_run(SelfHealRequest(...))` 預設只定位。明確選擇 `operation="click"`，再透過 `VerificationRequest(verifier=...)`（Python bool callback）或 `VerificationRequest(description=...)`（已設定的 VLM）於輸入送出後驗證條件。VLM 驗證使用新擷取的邏輯影像，可能產生 API 費用。`verified` 分為真、假及未知；`found` 與 `issued` 本身不代表操作通過驗證。例外與取消原樣傳遞，不重試點擊。`AC_self_heal_run` 和 MCP `ac_self_heal_run` 接受巢狀 `request`；明確驗證失敗使指令／CLI 失敗，或回傳含結構化結果的 MCP `isError`。GUI **Self-Healing** 提供選填的操作後條件，Script Builder 可編輯 JSON 請求。獨立 VLM 擷取也改用相同的記憶體邏輯原點／Retina 正規化。Framework assertion 會中止定位後備。

已擷取的自癒紀錄新增可選的 `journal_path`，搭配 run／step ID。實驗性 `inspect_heal_source(path, run_id, step_id)`、`AC_self_heal_source` 與 MCP `ac_self_heal_source` 只讀取原始步驟經清理的生命週期快照。在 **Self-Healing** 選取紀錄後，使用 **動作 → 檢視原始步驟** 開啟背景讀取器；切換目標時會等待舊讀取停止並保留請求者脈絡，關閉則取消待處理工作；Run History 讀取器也可選填步驟 ID。先篩選 run／step 再套用輸出上限，整份日誌仍會驗證，進度通知前後重查路徑根目錄，取消不回傳部分結果。舊紀錄或未經動作日誌擷取的操作沒有來源連結；查閱不會重播指令。

實驗性因果同步提供 `CausalBucket`、`CausalConfigStore`、`SyncActor`、保留衝突的 entry 版本與持久化本機 `SyncOutbox`。獨立且經驗證的 `GET/PUT /config/{user_id}/causal` 第三版協定，在保存重送收據的同一個 CAS 交易內驗證裝置註冊、確認、退休／完整同步 epoch 與刪除回收。回收後保留永久的最小刪除憑證；舊版寫入不能覆蓋已升級帳號。私有 `AC_config_store_get`／`AC_config_store_commit` 與對應 MCP／Builder 命令可讀取及提交帶明確 `_actor` 的因果 JSON；純資料合併／peer 與私有 outbox 命令仍可使用。明確的 `CausalSyncClient` 與 `AC_config_causal_fetch`、`AC_config_causal_commit`、`AC_sync_outbox_flush`（含 MCP／Builder）已提供第三版 HTTP 投遞：結果不明時重送固定請求，只有明確的過期版本才在有界預算內重合併。`CausalReceipt` 在 outbox 原子確認原收據與最新完整快照；命令憑證使用即時的 `options.secret_env` 參照。`CausalSyncClient.control` 與私有 `AC_sync_peer_control`／`ac_sync_peer_control`／Builder Data 命令可持久化註冊、確認、回收、退休與完整重同步。`SyncControlRequest(operation_id=...)` 讓已完成 RPC 的重試保持冪等；完整重同步須明確提供 `discard_pending=True`，收到收據後才原子採用新世代並封存待送舊編輯。本機 `status` 不讀取憑證或網路。`python -m examples.causal_peer_control` 提供暫存 loopback 工作流；明確的本機資產版本可透過 `AssetManifest`、`DirectoryAssetTransport`、`build_asset_manifest`、`sync_assets` 與私有 `AC_sync_asset_manifest`／`AC_sync_assets`（MCP／Builder）操作。全部資產先暫存並通過 SHA-256／大小驗證，再一次發布完整目錄；受損快取拒絕使用，腳本保持未執行。`python -m examples.sync_assets` 只使用暫存目錄。七種實驗性 adapter 已將明確選定的腳本、locator、熱鍵、觸發器、通訊錄、JSON 設定與已保存的原生 GUI 偏好設定保存為持久化因果 profile。`SyncBindings` 將明確指定的秘密與機器值換成具名參照；`materialize_sync_profile` 發布完整且未啟用的原生格式版本。私有 `AC_sync_adapter_snapshot`、`AC_sync_adapter_apply`、`AC_sync_adapter_resolve`、`AC_sync_profile_materialize` 與對應 MCP／Builder 命令提供相同流程。`python -m examples.sync_adapters` 僅使用暫存檔。私有絕對路徑綁定接受高熵目錄名稱，仍拒絕可辨識的憑證格式。原生數值定義會在儲存前以分類錯誤拒絕超出範圍的值，包含超大 JSON 整數。`WorkspaceSettingsSyncAdapter` 僅讀取原生 GUI INI 的主題、字級、導覽顯示／寬度，並發布未啟用的 `workspace.ini`；明確複製為獨立工作檔後，才能交給新 GUI 使用。`python -m examples.sync_workspace` 不匯入 Qt。`SyncWorkspace` 已整合明確來源、持久離線捕捉、因果 HTTP、精確衝突檢視與完整重同步來源基準。私有 `AC_sync_workspace`／`ac_sync_workspace`／Builder Data 共用 status／capture／sync／review／resolve／preferences／materialize 與明確 peer 控制，全部需要 DRIVE；網路憑證使用 `options.secret_env`。`python -m examples.sync_workspace_http` 以兩組暫存來源與 loopback 示範衝突解決、重啟及退休編輯不重播。接收資料保持未啟用。引用資產傳輸見下方；明確的原生工作副本載入見下方，`ConfigSyncClient` 保留時間戳合併。參閱[因果／outbox 指南](../../source/Zh/doc/causal_sync/causal_sync_doc.rst)與 `python -m examples.causal_sync`。

延遲建立的 **工作區同步** 分頁透過 **Actions** 提供本機狀態／擷取、網路同步與裝置控制、精確因果檢視／解決衝突，以及完整未啟用發布。貼上明確的私人工作區設定，憑證只填環境變數名稱。同步不會自動套用收到的偏好設定。選取 `workspace`、檢視目前版本後，再執行「套用已檢視的 GUI 偏好設定」，才會更新目前視窗的主題、字級及導覽面板。`SyncWorkspace.preferences(observed=change_ids)` 與既有 AC／MCP／Builder 的 `preferences` 操作，僅在已檢視版本完全相符且無衝突時回傳四個標準值；缺少或刪除的值採安全預設。Worker 保留呼叫者 context、重驗 DRIVE 權限，支援取消並在關閉後捨棄舊結果。畫面顯示修訂版、待送／衝突／參照數與最近成功同步版本；開啟分頁不會啟動連線。

明確的原生載入使用 `load_sync_profile(directory, target_root, expected_digest=...)` 與 `LoadedSyncProfile`，並提供私有 `AC_sync_profile_load`／`ac_sync_profile_load`／Builder Data。以已發布的 `files` 資料夾及精確檢視的 manifest 摘要建立全新可編輯工作區，先驗證全部 bytes、標準原生檔案及封存 heads 一致，再原子發布。載入的熱鍵及每個觸發器節點都是停用的原生物件；定位器與通訊錄 handle 使用工作副本。型別化資產參照及原生熱鍵／觸發器路徑依工作根目錄解析，腳本字面文字保留原意，秘密維持 placeholder。在「工作區同步」發布後，資料夾／摘要欄位會填入結果；選擇工作副本存放資料夾，再執行「載入已檢視的原生 profile」。其他明確 Actions 可檢查所選原生類別、在 Builder 開啟已載入腳本快照，或套用其偏好快照。每次操作都重驗目前呼叫者與擷取擁有者的權限；開啟腳本後仍須明確執行 Run；Builder 將匯入的命令名稱與位置參數顯示為字面文字。`python -m examples.sync_profile_load` 使用七種暫存來源與真實 PNG，不呼叫網路或裝置。

資料夾鏡像改以 SHA-256 內容比對，不再依賴修改時間遞增：只改時間不重送，時間相同或較舊的內容修改仍會送出。FolderSyncEngine 重啟時保留待送與離線修改，逐檔檢查停止要求，並持續擁有尚未結束的傳送工作。傳輸擁有者可在發布檔案後明確呼叫 record_received(path)，避免回送收到的內容。原生 GUI 的固定內容收據處理見下文。

檔案傳送現在會等待每個 DataChannel callback，將緩衝資料限制在 1 MiB，並將通道失敗回報給呼叫端。可選的 `cancelled` 判斷會停止排隊寫入；宣告的位元組數可偵測來源截短或增長。原生資料夾工作綁定授權、引擎、viewer 與 peer connection，擁有權變更時停止。收件匣下載移至事件迴圈之外，透過每個通道最多 32 筆請求的佇列依序傳送。預設手動模式接受資料不代表遠端發布完成；確認模式見下文。GUI 重連交接見下文。

原生檔案接收器現在會在關閉、檔案／控制通道關閉、連線進入終止狀態、更換通道或撤銷檔案權限時清除未完成內容。已關閉的接收器拒絕延遲資料；具體 peer／通道與授權檢查會保護替換後的傳輸，也會拒絕 viewer 在驗證前接收檔案。狀態清理先於使用者 callback，避免舊失敗影響 callback 建立的新連線。檔案／稽核／狀態 callback 保留原始取消及強制中斷物件。清理會嘗試關檔及刪除暫存檔，檔案系統失敗寫入日誌。既有 Remote Desktop 控制自動使用此生命週期；已完成的目標與原有線上格式仍可使用。

本機 `FileReceiveReceipt(path, sha256, size)` 現在會在原子發布後固定原始接收內容。`FileTransferReceiver.handle_message(on_receipt=...)` 與原生 host／viewer 的 `set_file_receipt_callback()` 提供收據，不必重讀已發布檔案。`FolderSyncEngine.record_receipt()` 避免回送並保留後續本機修改；既有 `record_received(path)` 則明確快照當前內容。GUI 資料夾開關綁定接收收據的引擎及 viewer，並在存取監看目錄前重新驗證原始授權。相對收件匣／監看路徑綁定建立時的工作目錄，既有路徑通知使用絕對路徑。這些本機收據供下文的原生確認模式使用；GUI 重連交接見下文。

原生 `FileTransferSender.send`、viewer 的 `send_file` 與 host 的 `push_file` 現在接受僅限關鍵字的 `require_commit=True`。確認模式會先探測已驗證的原生對端，再讀來源中繼資料／內容；以第二版 begin／end 中繼資料傳送，並在原子發布後核對傳輸 ID、不可預測的結束 nonce、SHA-256 及位元組數。相對來源路徑會在交換前固定。每個檔案都重新確認支援與權限，等待有時限；取消、通道／事件迴圈替換或撤銷權限都保留失敗狀態。GUI 資料夾傳送一律要求此模式，因此只接受但遺失的資料不會推進投遞狀態；不確定的傳送會由同一引擎重試。手動傳送仍預設使用原有線上格式。GUI 資料夾投遞要求兩端都支援確認傳輸；不支援時會在送出檔案內容前失敗。GUI 明確重連／恢復見下文。

GUI 重連時會為每個面板保留一份記憶體內的資料夾基準。重新連線後再按開始同步：相同的已驗證 host 指紋、絕對監控路徑與本機使用者，會透過新授權的 sender 接續失敗／離線修改。缺少或更換 host 指紋、路徑或使用者時建立新基準；舊工作仍在執行時拒絕交接，待它退出後才能重試。明確關閉資料夾同步會重設基準；停止／重連 viewer 則保留，關閉應用程式後清除。指紋沿用既有已驗證 host 中繼資料的信任模型，沒有新增密碼學身份保證。SDK 可先停止 FolderSyncEngine，待工作確實退出後匯出 checkpoint()，將不可變的 FolderSyncCheckpoint 傳給路徑／遞迴設定相同且 sender 已明確授權的新引擎。基準包含初始略過檔案與收到的內容，並非遠端確認清單。

TCP／WebSocket 剪貼簿傳輸沿用明確的 SDK 呼叫與 GUI 推送剪貼簿按鈕。收到的文字／圖片不會自動傳回或廣播；使用者仍可明確重複傳送相同內容。Viewer／host 在讀到緩衝訊息後，會重新檢查原始連線、驗證及完整控制權限，再套用剪貼簿資料。Viewer 會在編碼前固定原通道，拒絕改送至替換後的連線。GUI 排隊中的傳輸保留具體 viewer 與連線發起使用者，寫入本機剪貼簿、明確讀取及送出前都會重新檢查權限與擁有權。過期或撤銷的工作會被略過或回報權限錯誤；一般 provider／callback 錯誤仍受控，原始取消與強制中斷物件繼續傳播。文字／圖片 JSON 格式及既有 API 不變。Callback 註冊只以弱引用綁定一次原始 viewer，避免斷線 viewer 自己保留自己及 Qt 面板直到循環垃圾回收；實際排隊資料仍保留原始 peer 與權限，直到處理或丟棄。受控本機協定、loopback 與 offscreen 測試替換原生剪貼簿 provider；真機與付費 API 驗收仍暫緩。

實驗性引用資產使用 `SyncAssetBlob`、`SyncAssetReference`、`SyncAssetStore` 與 `SyncAssetHTTPClient`。明確的 `SyncBindings.assets` 別名將選定檔案封存為不可變 SHA-256 參照；只改資產也會建立新的因果版本。`SyncWorkspace` 在準備新定義請求前上傳已驗證分塊，支援中斷續傳，並在完整且未啟用的發布前下載引用內容。既有私有 AC／MCP／Builder 工作區／profile 命令共用這些欄位。`asset_cache_path` 選取 client cache；signaling 的 `--asset-store`／`AUTOCONTROL_SYNC_ASSET_STORE` 選取獨立 server 資料庫。具驗證的第一版資產路由使用 256-KiB 分塊、每檔 64 MiB 上限，每帳號預設限制 256 MiB、8,192 塊與 4,096 筆 blob 收據。超過配額會明確失敗；不可變歷史不自動回收。原生輸出路徑相對於 generation 根目錄。`python -m examples.sync_referenced_assets` 經暫存 loopback HTTP 傳送真實 PNG 與腳本，不執行腳本或改目前工作區。

實驗性持久化設定使用 `ConfigStore.commit(..., base_revision=..., operation_id=...)` 與第二版 signaling PUT envelope。SQLite 交易讓 bucket 與重送收據在重啟後保留；過期版本或 ID 改配其他內容會衝突。`ConfigSyncClient` 預設條件寫入；舊版盲寫須在 client／server 明確開啟。`--config-store` 選取延後開啟的資料庫。私有 `AC_config_store_get`／`AC_config_store_commit` 與對應 MCP 工具共用 Script Builder 的明確 Data 命令。只儲存資料，不執行腳本或啟用觸發器；因果合併與離線 outbox 另行交付。參閱[持久化設定指南](../../source/Zh/doc/config_store/config_store_doc.rst)與 `python -m examples.config_store`。

實驗性日誌產碼候選支援 `generate_candidate_from_log(path, run_id=...)`、`AC_generate_candidate_from_log` 與 MCP `ac_generate_candidate_from_log`。它會整合開始／完成快照，保留已記錄的控制來源與重試證據，並將不完整重建標示為已觀察路徑。失敗／未完成呼叫、未知命令及遮罩輸入均列為排除項目，不捏造平行順序。Python／pytest／Robot 產物經靜態、命令及不發送輸入的乾跑檢查。`codegen --from-log run.jsonl --run-id selected` 輸出 JSON 審閱包；`-o review.zip` 或 `write_candidate_archive` 可將程式、動作與來源資訊一起原子匯出。Recording Editor 與 Script Builder 的 **動作 → 審閱日誌候選腳本** 提供程式／差異／來源／警告；Builder 匯入為獨立操作，拒絕覆蓋審閱期間的編輯變更。產生與匯入均不執行候選。參閱[候選指南](../../source/Zh/doc/journal_candidates/journal_candidates_doc.rst)與 `python -m examples.journal_candidates`。

實驗性候選樣板版本提供 `create_template_candidate`、`preview_template_candidate`、`verify_template_candidate`、`accept_template_candidate`、`revert_template_candidate`，以及對應 `AC_template_candidate_*`／`ac_template_candidate_*` 操作。新的不可變 JSON 版本包保存原始位元組及依目標 PNG／JPEG／BMP 格式編碼的候選；預覽回傳有界縮圖。驗證在本機資料集比較兩個固定版本；接受須有已標註命中、期望 miss、全部已標註案例正確，並提供已預覽版本的 SHA-256。接受時重驗資料集，只原子替換仍符合的原始內容；回復精確還原原始位元組，拒絕覆蓋後續修改。未知樣本與原生操作結果分開呈現。驗證使用記錄的門檻；啟用影像不修改腳本門檻。**Self-Healing → 候選樣板** 提供五個動作、背景工作、取消與 JSON 證據。執行 `python -m examples.template_candidates` 可跑只使用暫存檔的範例。

實驗性固定影像比較支援 `evaluate_locators`、`evaluate_healing_manifest`、`AC_self_heal_evaluate`、MCP `ac_self_heal_evaluate` 與 **Self-Healing → 版本比較**。報告分別呈現已標註正確率、誤判、未知與已驗證恢復，包含 p50／p95 及來源，可由 `write_healing_report` 或 GUI 動作匯出 JSON／HTML。本機資料集入口不會截圖、點擊或自行選擇網路 backend。參閱[資料集、統計母體與限制](../../../benchmarks/self_healing/README.md)。

除了這張表，`utils/` 底下還有 311 個無頭套件，涵蓋斷言、韌性、資料品質、i18n 稽核、遮蔽、
治理、可觀測性等等。完整的逐模組地圖在 **[architecture_explore.md](../../../architecture_explore.md)**。

---

實驗性的結構化日誌已從 `je_auto_control` 匯出（也可透過 `utils.action_journal` 使用）：`journal_scope` 記錄現有 executor 呼叫，`execute_action_with_journal` 隔離一次執行。本機 loop／parallel／DAG 步驟保留 parent ID，並區分失敗、取消與 dry-run。既有 history 擁有者會自動連結明確擷取，包含本機 parallel／DAG worker 開啟的 journal；`HistoryStore.journals_for_run` 可查詢非擁有式連結，清理 history 不會刪除日誌檔。CLI 支援 `run script.json --journal run.jsonl [--journal-run-id ID]` 與 `journal run.jsonl [--run-id ID] [--limit 100]`。查閱會按附加順序顯示遮罩後的生命週期快照，預設最多 100 筆，上限 10,000 筆。`AC_journal_capture` 接受具名參數，在擁有者 executor 上執行巢狀 `body`，保留原變數範圍；`AC_journal_read` 與 CLI、公開的 `inspect_journal` 共用遮罩後的有界查閱。兩個指令皆可在 Script Builder 編輯。擷取會在 history 連結、開檔及動作執行前拒絕含有當次執行已知秘密的識別碼或目的地。MCP 的 `ac_journal_capture` 與 `ac_journal_read` 提供結構化結果、進度與合作式取消。擷取的日誌根目錄限制與 observer 會保留至巢狀擷取及本機 workers；查閱可在逐筆驗證時取消。Python 可透過 `JournalRunOptions` 與 `execute_journal_run` 使用相同控制。

手動執行可透過 `manual_history_scope`、`AC_history_capture`、CLI 的 `run --history [--history-db PATH]`，或 Script Executor／Script Builder 的 **記錄至執行歷史** 選用紀錄。GUI 的選填日誌路徑也能獨立使用；GUI／CLI 保留原本的結果 JSON 與變數範圍，指令則回傳 `history_id`、`record`、`failed_actions`。既有與巢狀擷取都會連結到新的手動歷史列。CLI 預覽以 `cli.preview` 標示，一般執行使用 `cli.run`。

Run History 提供唯讀日誌檢視。使用 **操作 → 使用所選執行的日誌** 選擇來源連結，或用 **選擇日誌** 指定外部檔案；設定執行 ID 與快照上限後，使用 **讀取日誌**。起始／完成快照保持分離，選取後會顯示完整的遮罩資料。**取消讀取日誌** 與關閉檢視會在逐筆邊界提出取消要求；檔案解析在背景 worker 執行，單純選取連結不會開檔。

`${secrets.NAME}` 解析後的值會在 executor 執行期間的應用程式診斷中遮罩，包含巢狀動作及本機 parallel／DAG。CLI／REST／MCP 請求與排程、trigger、hotkey、email 執行會將遮罩保留到錯誤處理及 audit／history 寫入完成；報表紀錄保存遮罩後的快照。DAG 會將擁有者的遮罩保留到 node 診斷完成，包含獨立呼叫與自訂 local runner。watchdog、observer 與 callback executor 會將遮罩保留到最後的錯誤處理；獨立規則彼此隔離。CLI stderr 會遮罩，API 結果、拋出的例外與 CLI 結果資料保留原始值。遮罩於擁有者的請求或執行結束時清除。中止的 history 記為 `error`，journal 步驟維持 `cancelled`，不再擷取錯誤截圖。取消會穿過非嚴格執行、復原／重試、回呼與本機 worker；history 結算失敗也不會取代原始硬中止訊號。

## 命令列介面

每次 `je_auto_control run`（包括 `--dry-run` 與未帶 `--var`）使用獨立變數範圍。頂層 `run_from_description` 與 `StateMachine.run()` 也會隔離變數，同一次執行內的動作與狀態仍可共享；巢狀呼叫沿用已有的執行範圍。自行建立的 `Executor()` 保留自己的變數。

```bash
je_auto_control run script.json [--var name=value] [--dry-run] [--allow-package NAME]
je_auto_control validate script.json          # 別名：lint
je_auto_control fmt script.json [--check]
je_auto_control list-commands [--filter mouse] [--json]
je_auto_control record out.json [--duration 5]
je_auto_control codegen script.json --target pytest -o test_flow.py
je_auto_control failure-bundle failure.zip --error "login timed out"
je_auto_control list-jobs
je_auto_control start-server --port 9938      # TCP socket 伺服器
je_auto_control start-rest   --port 9939      # REST API
je_auto_control version
```

`--var name=value` 會盡量以 JSON 解析（`count=10` 會變成整數），否則視為字串。
`run` 只要有任何動作失敗就以 1 結束（仍會跑完整份腳本），CI 步驟會跟著失敗。舊版 `python -m je_auto_control -e file.json` 進入點仍然可用，它的 `-e`、`-d` 與 `--execute_str` 旗標也同樣在有動作失敗時以 1 結束。由 [TestPioneer](https://github.com/Integration-Automation/TestPioneer) 啟動時（它會設定 `TEST_PIONEER_ARTIFACT_DIR`），以相對名稱要求的 HTML、JSON、XML 報告會寫到該目錄底下。

---
