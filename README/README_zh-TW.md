# AutoControl

[English](../README.md) | [繁體中文](README_zh-TW.md) | [简体中文](README_zh-CN.md)

AutoControl 是用來操作桌面應用程式的 Python 自動化框架。你可以控制滑鼠與鍵盤、擷取畫面，並透過圖片、OCR 或無障礙 API 尋找介面元素。支援 Python、JSON 動作檔、桌面 GUI 與 MCP 用戶端。

## 開始使用

需要 Python 3.11 以上版本。

```bash
python -m pip install je_auto_control
```

先讀取螢幕尺寸，這個範例不會送出鍵盤或滑鼠輸入：

```python
import je_auto_control as ac

print(ac.screen_size())
```

要使用桌面介面，安裝 GUI 套件後啟動：

```bash
python -m pip install "je_auto_control[gui]"
python -c "import je_auto_control; je_auto_control.start_autocontrol_gui()"
```

視窗開著時，程式會關閉自動回收，改由 GUI 執行緒上的計時器回收 Python 的循環垃圾，結束時再打開。這是為了不讓 worker 執行緒碰到 PySide6 6.12 會延後刪除的 Qt 物件；那條路徑在 Windows 上曾讓程序 abort。只 `import je_auto_control` 的腳本不受影響。

## 可以做什麼

- 操作滑鼠、鍵盤與視窗。
- 用圖片比對、OCR、無障礙 API 或選配的視覺模型尋找控制項。
- 將重複工作儲存為 JSON 動作檔。
- 透過 MCP 連接 AI 用戶端，或透過 REST 與 Python 整合。
- 在選配 GUI 中使用錄製、排程與遠端桌面工具。

TCP socket 伺服器（`je_auto_control start-server`，連接埠 9938）現在需要驗證。每條連線先送 `AUTH <token>`，收到 `AUTH_OK` 後指令才會執行。token 依序取 `--token`、`JE_AUTOCONTROL_SOCKET_TOKEN`，都沒有則隨機產生，並以僅擁有者可讀的方式寫入 `~/.je_auto_control/socket_server_<port>.token`（`--token-file` 可改），伺服器停止時刪除。RBAC 下只接受使用者的 token：執行動作需要 `drive_input`，`quit_server` 需要 `manage_hosts`。每條連線有 10 秒與 3 次機會，失敗依位址限流。`ac.send_socket_command([["AC_screen_size"]])` 會替你讀 token 並完成驗證。既有客戶端必須先送 `AUTH` 那一行，或以 `--no-auth` 啟動伺服器；後者會記錄警告：此時任何本機程序都能執行任何指令。詳見[整合說明](../docs/guides/zh-TW/integrations.md)。

影像偵測分頁在背景執行比對，並有自己的滑鼠按鍵選擇。
Actions 選單可停止待完成的搜尋；關閉分頁會丟棄晚到結果，重新開啟會重設輸入欄位。
取消可阻止後續移動與點擊步驟，但無法中斷已進入的原生呼叫。

自動點擊、錄製與腳本執行分頁各自持有控制項與背景工作；關閉會停止本頁工作，重開會建立新的輸入欄位。共用錄製器不隨分頁關閉，重開後會讀取後端狀態，不支援查詢時顯示未知；此狀態不代表原生掛鉤健康檢查。Ctrl+4 仍可停止腳本與自動點擊。

啟動時開著的三個分頁只先建立 Record；Script Builder 與 Remote Desktop 在第一次被選取時才建立，啟動時間與記憶體約減半。

View → 執行詳情（Ctrl+Shift+D）可展開右側詳情。診斷分頁會提供實際進度、停止、結果與錯誤狀態，其他在背景執行工作的分頁（模型請求、USB 列舉、廣播、DAG 執行、日誌讀取）也會：執行中、停止中，然後是完成、已取消或錯誤，工作有回報進度時一併顯示。尚未執行過工作的分頁會明確顯示沒有詳情。背景停止失敗時（頁面放開的連線、錄影或主機）會被保留而不只記錄日誌：診斷分頁列出每一個及其錯誤，Actions › 重試失敗的停止 會以排入時的權限再次執行。切換或關閉分頁會斷開其更新。嵌入程式可將 TabRegistry 傳入 WorkspaceShell；AutoControlGUIWidget(parent) 仍可使用。

每個分頁開頭都有標題與一行用途說明，控制項依用途分組在卡片上；核取方塊與選項按鈕以主題強調色繪製，深色主題下也看得清楚。控制項會隨視窗縮小，不再撐寬頁面：下拉選單不再以最長項目決定寬度，表單欄位放不下時標籤移到欄位上方，長說明會自動換行。空的表格、清單或樹狀清單會顯示「目前沒有內容。」，直到第一筆資料出現，不再只顯示空白格線。頁面標題下方的橫幅會說明該頁上次執行失敗（下次執行時清除），GUI 在 RBAC 範圍內執行時也會說明目前角色無法執行該頁的哪些指令；橫幅附有關閉連結。視窗會依寬度重新排列：1,200 px 以上，導覽與執行詳情並排在分頁兩側；較窄時詳情改為覆蓋在分頁上的抽屜；800 px 以下導覽縮成窄圖示欄，按其選單鈕或 Ctrl+K 以抽屜開啟功能清單（Escape 或點擊旁邊即關閉）。因寬度隱藏導覽不會改動已儲存的偏好。

在 RBAC 範圍內，每個分頁執行特權指令前都會像 executor 一樣檢查角色，被拒時在分頁中說明原因；未啟用 RBAC 時行為不變。遠端桌面、Quick Connect、WebRTC 與 REST 頁面的 token 與密碼欄預設遮蔽，可切換顯示。Quick Connect 核准對話框按 Enter 或 Escape 都是拒絕。密碼庫指令、外掛載入、設定匯出入、稽核紀錄讀取、資料來源載入與 Trace Replay 影格都在背景執行緒進行，Trace Replay 也會拒絕錄製資料夾以外的影格檔。DAG、Flow、Script Builder 與錄製編輯器、執行紀錄、測試套件、自我修復、REST 使用者面板、USB ACL、管理主控台，以及遠端桌面的信任清單、通訊錄與已知主機，其檔案與儲存操作也都在背景執行；分頁會顯示忙碌狀態，錯誤就地回報。遠端桌面畫面與結果圖片在各檢視自己的執行緒解碼（只解最新一格），TLS 憑證在連線或啟動的工作執行緒載入。

WebRTC 統計輪詢在背景啟動，停止後會捨棄晚到的樣本。

Windows、macOS、X11 與 Wayland 使用不同後端，實際功能取決於系統權限與選配依賴。Windows ARM64 另有限制，部署前請先閱讀安裝文件。

Wayland NORMAL 輸入透過受管理的子程序執行 libei 與 portal 呼叫。逾時、取消或回覆不確定時會退役該程序，不重播輸入或自動切換供應者。直接使用 `LibeiBackend` 仍在呼叫端程序內執行；子程序退役不代表合成器已釋放輸入，原生驗收仍待執行。

受管理的 Agent 任務與跨主機傳輸包含實驗性功能；採用前請查看實作紀錄與專案進度中的驗收狀態。

主機選定的語意 target 支援 `semantic` 完成條件，以新讀回核對已記錄的目標身分及期望欄位。此條件不授予記憶體存取權，也不啟用原生 target。詳見[語意完成驗證](../docs/process_memory_contract.md#semantic-completion)。

## 文件

- [安裝、平台支援與設定](../docs/guides/zh-TW/setup.md)
- [Python、JSON 與命令列用法](../docs/guides/zh-TW/usage.md)
- [AI Agent、MCP 與伺服器整合](../docs/guides/zh-TW/integrations.md)
- [完成驗證與證據移交](../docs/guides/zh-TW/evidence.md)
- [開發與相關資源](../docs/guides/zh-TW/development.md)
- [實作紀錄](../docs/guides/zh-TW/implementation-notes.md)
- [Documentation index](../docs/README.md)
- [Examples](../examples/README.md)
- [Progress](../Progress.md)

## License

[MIT](../LICENSE) © JE-Chen. [Third-party licenses](../Third_Party_License.md).

關閉 Remote Desktop 會釋放頁面；重新開啟會建立新控制項，不自動接回共用連線。Registry 的 TCP／WebSocket 連線仍可供腳本使用；頁面擁有的 WebRTC 連線與音訊在背景停止。待處理核准會拒絕，延遲回呼會丟棄。已在傳送中的檔案傳輸會在頁面關閉、連線被放掉或上傳取消時於下一個區塊停止，主機會丟棄未完成的檔案（TCP、WebSocket 與 WebRTC 皆同）。

WebRTC host/viewer 的 `stop()` 最多等待三秒完成軟體清理。`PeerStopPending` 保留同一個尚未完成的操作；明確重試只會繼續等待。`PeerStopFailed` 保留清理失敗的資源供明確重試，成功前禁止重新啟動。Multi-viewer host 保留失敗的 session 與共用來源。`FolderSyncEngine.stop_confirmed()` 在原工作執行緒仍存活時回傳 `False`。這些結果不代表原生裝置已釋放；頁面銷毀後的復原仍需持久資源保管與重試整合。

主機檔案請求會保留原傳送工作，直到工作執行緒退出，重複停止也不會提前釋放所有權。停止會通知取消並等候原工作；無法中斷的後端操作仍可能讓停止維持待完成。

MCP 唯讀標記不授予 viewer 存取權。已審查的即時畫面與呼叫者資料運算使用 `read_screen`；檔案、裝置資料及未知工具需要 `read_data`。別名共用標準名稱的權限，較強的明確設定優先。提供影像來源、從環境變數讀取設定欄位或規劃開啟本機檔案時需要 `read_data`。Anchor locator 的 accessibility／OCR 允許觀測即時畫面，影像範本需要 `read_data`，VLM 請求需要 `drive_input`。唯讀呼叫拒絕擷取產物及 VLM 分支，目錄排除可自選 ADB 執行檔的工具。MCP CI annotations 只回傳格式化文字，不寫入 stdout。未審查的 plugin 與 WebRunner 初始化工具不列入唯讀目錄，等待相依版本的個別審查。

MCP 的 `tools/call` 以可停止的執行進行，列為 `mcp-…`。`notifications/cancelled` 會停掉它：`ac_execute_actions` 的動作清單在下一個動作前停下，`ac_wait_for_image`／`ac_wait_for_pixel` 在輪詢中途醒來；該次呼叫以 `-32800` 回覆。`ac_stop_execution` 與其他停止請求以同樣方式結束它，回報為工具錯誤。已經進到後端的單一指令仍會先跑完；例外的是擷取輸出的 shell 指令（`ac_shell`、`AC_shell_to_var`），它的行程樹會被結束；HTTP 請求（`AC_http_request`、`ac_http_request` 與其他走共用 HTTP client 的呼叫），它的 socket 會被關閉；以及一次範本比對、OCR、VLM 定位請求或唯讀無障礙樹走訪，呼叫不再等它（原生運算或請求在背景跑完、結果丟棄）；這些呼叫都隨即結束。單一手勢內的節奏等待也會醒來：`click_mouse` 連點之間的間隔、補間拖曳的每步與穩定停頓（按鍵在游標停下的位置放開），以及擬人移動與擬人打字的每步、每鍵延遲。

影像搜尋無法使用輸入時拋出 `ImageSearchInputException`：範本不存在或讀不出、範本是單一顏色、門檻超出 0–1、是 NaN 或不是數字，或 OpenCV 無法比對的影像。`ImageNotFoundException` 現在只代表搜尋跑過、範本不在畫面上。兩者是兄弟而非父子，所以 `AC_assert_image` 加 `present: false`、`AC_wait_image_gone` 與 `AC_if_image_found` 的 `else` 分支遇到打錯的範本路徑會失敗，不再通過；用這種範本的影像觸發器會被停用並記錄，觀察者規則、狀態機守衛與 anchor locator 則會拋出例外。原本攔 `ImageNotFoundException` 來處理錯誤路徑的程式碼，必須同時攔 `ImageSearchInputException`。

指令拋出框架家族以外的錯誤（`cv2.error`、`sqlite3.Error`、外掛自訂的例外類別）時，不再中止整份動作清單：它被記成該動作的失敗，包成 `AutoControlForeignException`（原例外是它的 `original` 與 `__cause__`），`AC_try`、`AC_retry`、`AC_loop` 與 `AC_parallel` 都把它當成一般的失敗動作。`raise_on_error=True` 時拋出的是這個包裝。從不收納的有：斷言失敗（`AutoControlAssertionException` 與外掛自己的 `AssertionError`）、`AC_break`／`AC_continue`、停止請求、取消、`KeyboardInterrupt` 與 `SystemExit`。

在 MCP 的 HTTP 傳輸上，`resources/subscribe` 屬於送出它的 session（`initialize` 回傳的 `Mcp-Session-Id`），`notifications/resources/updated` 經該 session 常駐的 `GET` 串流送達；沒有串流開著時到達的更新會被丟棄。結束 session 會釋放它的訂閱。沒有 session 的請求沒有可送達的串流，會以 `-32600` 拒絕。stdio 傳輸不變。

REST 主機資料讀取與對應 MCP 權限一致：排程、遠端 session、USB passthrough 狀態、loopback／remote 裝置清單及診斷需要 `read_data`。對應已註冊的狀態指令、`AC_probe_capabilities` 與 `AC_diagnose` 會在執行提供者之前檢查權限。唯讀標記不授予 viewer 存取權；operator／admin 仍可使用。USB 列舉／事件、保留的 inspector 統計與程序 metrics 也需要 `read_data`；`AC_list_usb_devices`、`AC_usb_recent_events`、`AC_inspector_recent`、`AC_inspector_summary` 同樣檢查此權限。Dashboard 各面板分別顯示缺少的權限並清除舊資料；session 重新整理成功後也會清除先前的錯誤狀態。未列入權限表格的 executor 指令仍屬另一項審查範圍。

語音指令（`AC_voice_register`）與 macro（`AC_define_macro`）保留註冊者的權限：觸發或呼叫時，每個步驟必須註冊者與目前呼叫端都有權執行才會執行，因此存下的動作清單不會借用 admin 的權限，也不會在 GUI 或 Python 觸發時不經檢查就執行。只有 macro 的擁有者或受信任的本機程式碼可以重新定義它。匿名 MCP session 以受限的 operator 身分執行，所以即使 RBAC 關閉也適用；沒有 RBAC 且不經 MCP 時行為不變。每個具名 executor registry（`AC_cas_put`、`AC_dedup_check`、`AC_idempotency_begin`、`AC_bulkhead_run`、`AC_sequence_observe`、`AC_outbox_enqueue` 背後的 store、window、bulkhead、tracker 與 outbox）最多保存 1,024 個名稱（`MAX_REGISTRY_NAMES`）：既有名稱照常運作，新名稱會拋出 `RegistryFullError`，名稱只在程序結束時釋放。`AC_generate_sop` 與 `AC_generate_code` 會代換已知的 `${var}`，但 `${secrets.NAME}` 與尚未綁定的名稱（例如迴圈變數）照原樣寫出。`AC_resolve_ref`／`AC_resolve_refs` 取得的 `env://` 值仍回傳給呼叫端，但在該次執行剩下的期間，日誌、journal 與 MCP 稽核中都會遮罩，記錄的結果與 Script Builder 結果窗格也會遮罩。

主機唯讀模式對外部提供的目錄及後續註冊套用相同限制，接收請求及重新核對身分後的呼叫都檢查混合用途參數。MCP 設定的失敗截圖需要可寫入的工具及重新核對後具輸入操作權限的呼叫者；唯讀呼叫與 viewer 不會觸發截圖。這不表示所有相依套件或診斷讀取均無初始化副作用。

內部 Windows 行程記憶體準備工作新增映像檔量測，透過保留的唯讀 handle 執行有界雜湊並保留失敗清理供重試。這只是觀測到的檔案證據，不是已載入程式碼或 fixture 的身分證明；原生驗收尚未完成，且不提供任意位址記憶體工具。詳見[契約](../docs/process_memory_contract.md)。

主機管理的 fixture profile 透過既有目標管理 API 與 GUI JSON 編輯器，將固定 worker 綁定到已審閱的設定路徑與摘要。註冊不會取得資源；bootstrap 與 configure 都核對部署綁定。明確呼叫 probe 時，會由有時限的背景 helper 檢查靜態產物，回報 `static_artifacts_ready`、`fixture_execution=not_run` 與 `native_evidence=not_recorded`。runtime 關閉時，會保留所有權直到診斷 helper 完成回收。fixture 僅在受管 readiness 中取得。設定與映像檢查不證明 Python 原始碼或 DLL 可信。原生執行仍暫停；私有交付格式與限制記載於同一契約。

WebRTC peer 也會保留媒體建構與清理失敗的原始資源，觀測即時停用完成，並將延後協商綁定原 peer。媒體 producer 關閉會回報待完成或不確定的清理結果，並保留原始資源。音訊與錄影不會透過不安全的 close／flush 重播宣稱成功；LAN close 可明確重試。應用程式 caretaker 與 GUI 整合仍待完成。詳見[清理契約](../docs/media_retirement_contract.md)。

HostBrowser 亦會拒絕晚到發布，並保留未完成的執行緒與關閉所有權；對話框整合仍待完成。

MultiViewerHost 可回傳含原始 session 清理物件的 offer，延後清理不會停止替換後的連線或畫面來源；GUI 接入仍待完成。

主機選定的語意 adapter 可透過既有觀察 API 回傳多來源報告。fixture 結合受審閱的記憶體讀取與自有唯讀 IPC snapshot，並在提交前重新核對兩者。報告版本 3 由主機程式固定必要欄位，分別保留有效欄位與各欄位的失敗原因。缺失來源、衝突與 best-effort 擷取不能授權操作或確認完成。版本 1 與 2 會被拒絕。

獨立自有 UI 觀察 fixture 可透過 `test/fixtures/native_memory/build_fixture.py --kind uia` 建置，靜態 manifest 維持 schema 2。內部 launcher 將啟動訊息綁定保留程序與視窗擁有者。限定範圍的 UIA reader 核對該視窗、程序與根節點身分，限制樹狀走訪並保護密碼欄位。唯讀受管 adapter 延遲建立 COM，透過共用觀察 API 保留部分欄位結果。

注入呼叫與隱藏 Python helper 已涵蓋限定範圍讀取、報告與逾時回收。原生部署信任、DOM 整合與桌面驗收仍待完成，尚未執行原生 UI fixture，也未證明不干擾桌面。

內部自有 UI target 在 attestation 前保留啟動器及兩個獨立映像租約擁有者；
清理會嘗試全部資源並保留失敗項目供重試。發布鎖防止關閉後存入晚到的來源。
原生 factory 僅建立擁有者；原生部署信任及原生驗收仍待完成。

主機管理可註冊 `uia_fixture` profile，`allowed_tools`、`roots`、`apps` 都為空，
設定只接受 `config_path`／`config_sha256`。固定隔離 worker 在取得資源前核對部署、profile
與目標 pin，兩端都拒絕命令。外部任務只有在沒有預排動作時可使用空工具集合；
仍須提供完成條件，空計畫不能證明完成，UI partial／best-effort 報告仍只供診斷。
註冊與 probe 不取得資源；probe 回傳 `not_supported` 與 `native_evidence=not_recorded`。
既有目標 API、CLI 與 GUI JSON 編輯器可傳遞此 profile。注入及隱藏 helper 測試不代表原生信任成立。

主機選定的程序內服務 adapter 可使用封閉的 `service_state` 完成條件：
`{"kind":"service_state","tool":"AC_service_start","state":"running"}`，或 STOP／stopped。
判定須有對應操作的確認回條，以及同一資源擁有者在接受後取得的新 SCM 查詢。
通過只表示 SCM 回報該狀態，不證明原子完成、健康或桌面不干擾。這些工具名稱只屬於
adapter 範圍，不是全域 executor 指令。既有任務 API 與 GUI JSON 編輯器可傳遞此條件。
主機審閱的 `service` profile 固定 `config_path`、`config_sha256` 及 `service_key`。
非 ASCII 的鍵以 Windows 本身的 NT upcase 表做大小寫折疊，不用 Python 的大小寫對應，
因此 SCM 視為同一服務的各種寫法共用同一把鎖。
固定 worker 核對部署的服務與操作上限後才接受任務範圍。註冊、重載與 probe 不讀取部署檔
或存取 SCM；原生驗收仍待完成。
所有固定路徑（各 profile 的 `config_path` 及部署指定的映像檔）都必須是本機磁碟路徑：
UNC 共用、`\\.\pipe\` 名稱、`\\?\` 裝置路徑與 `..` 片段一律拒絕，註冊 profile 不能讓主機把認證送到其他機器。
browser profile 也可宣告主機審閱的 `semantic_fields`：最多 64 筆 `{name, selector, frame?, property}`，property 為 `text`、`value` 或 `visible`。之後每次瀏覽器觀察都會附上共用 observation report 格式的 `semantic_report`。來源綁定受管瀏覽器 context，新 session 即為新的目標生命週期；元素不存在回報 `not_found`，SDK 拒絕讀回的值（密碼、隱藏、檔案或 `data-secret` 欄位）回報 `protected`，讀取期間換頁則整個來源為 `inconsistent_snapshot`。擷取編號與時間不列入，頁面未變時動作前的指紋維持相同。selector 必須唯一，因為 SDK 遇到不唯一的 selector 會讓 session 退休。DOM 讀取沒有 revision，維持 best-effort；實際瀏覽器驗收仍待完成。
`android` 目標 profile（設定 `serial`、`physical_id`、`package`，可選 `adb_port`、`user`、`idle_seconds`；單一 app；工具 `AC_android_tap`／`AC_android_swipe`／`AC_android_key`）經裝置端 helper 操作一台裝置，helper 須已安裝並執行。真機驗收仍待完成。
Wayland portal 拒絕或撤銷後，`reset_native_input()`（`AC_reset_native_input`、`ac_reset_native_input`、Diagnostics → Actions）會退休快取的輸入工作階段，讓下一次輸入重新請求同意；它本身不要求任何授權。
iOS 模擬器可用 `use_ios_simulator(udid)`（`AC_ios_use_simulator`）把安裝、檔案、剪貼簿與錄影改經 `xcrun simctl`；`list_ios_simulators()` 列出已開機的模擬器。
fixture 映像執行前，租約還會拒絕其他帳號能變更的位置：從磁碟根目錄往下的每一層都必須是實體目錄
（不能是 junction 或 symlink），且只有 SYSTEM、Administrators、TrustedInstaller 與目前使用者能改名、刪除、
改 ACL 或新增檔案；租約檔案的最終路徑也必須等於設定的路徑。請把 fixture 部署在 `%LOCALAPPDATA%` 這類受保護目錄；
授予 Authenticated Users 修改權限的磁碟根目錄（次要磁碟常見）或共用的 `%TEMP%` 會被拒絕。
fixture 在自己的目錄啟動，只帶最小環境變數：僅含系統目錄的 `PATH`，不帶主機的任何 token 或金鑰。
