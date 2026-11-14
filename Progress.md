# Progress

## 維護規則：實機驗收固定置頂

依使用者 2026-11-10 指示，所有實機驗收待辦固定放在本檔上方，先於一般開發規劃、重構與相依套件待辦。
後續新增或更新原生桌面、實際瀏覽器、實體裝置、真實應用／API、跨主機與長時間驗收時，
一律加入下方「實機驗收與必要前置工作」區，不得散放到一般開發區或在驗收區之前插入開發規劃。
混合實作與驗收的段落保留必要前置工作及限制；新增段落應把實作待辦和實機驗收分開，互相連結。
只有原始需求中的驗收條件與實際證據都完成，才能移除待辦；完成紀錄依既有規則寫入 `docs/updates/`。
本次只調整文件排序，不解除任何暫緩、不啟動驗收，也不把 CI、mock 或隔離測試視為實機通過。

## 實機驗收與必要前置工作

以下集中列出未完成的實機驗收，以及與驗收不可分的缺口與前置實作。
各段原有的 `TODO`／`WIP`／`BLOCKED`／`DECIDE` 狀態與暫緩條件維持有效。
原生桌面、實際瀏覽器、Android／iOS 真機、WebRunner 原生雙向 bridge 與完整 24 小時驗收仍暫緩；
真機與付費 API 驗收須待使用者明確恢復後執行。文件置頂不代表取得執行或付費授權。

## 輸入、視窗與擷取修正：還沒在真的桌面與 Jeffrey_RPA 上驗過

### 行程記憶體自有 fixture 原生驗收

`TODO` — 原生執行仍暫緩。須先完成 Windows provider 的可信應用身分核對、自有 fixture 與受管權限整合，
再驗證 ASLR、32／64 位配置、跨區段／guard／不可讀頁、程序退出、PID 重用、權限拒絕、
取消及 handle 回收。以 fixture 的已知狀態比對語意結果，獨立觀測前景、焦點、滑鼠與輸入事件。
目前 injected-provider 測試不算原生通過；設計見 [記憶體觀察契約](docs/process_memory_contract.md)。

### 桌面行為驗收

`TODO` — 原生桌面與正式批次升級前的行為驗收暫緩。

- **正式批次升級前的桌面行為驗收**：需核對 `_gui_control.py` 對下列行為的實際依賴：
  `write()` 大寫與 `is_shift` 在 Windows／X11 生效、`"\r\n"` 只按一次 Enter、`mouse_scroll` 預設方向改為 `scroll_up`
  （X11／Wayland 上 `mouse_scroll(3)` 由往下變往上）、小數座標四捨五入、`focus_window` 在 Windows 沒拿到前景會丟例外、
  `list_windows` 不再列出 DWM cloak 與零面積視窗、`post_key` 對可列印字元只送 `WM_CHAR`。
- **混合 DPI 座標與樣板**：需實測各螢幕上的舊版座標、`screen_region`、視窗版面與樣板，
  包含縮放不同的副螢幕、負原點與多螢幕排列；必要時重新錄製，不能以推導代替驗收。
- **舊版存的視窗版面檔要重存**：`save_window_layout` 改存 `GetWindowRect`，舊檔還原會偏右 7 px、縮小 14×7 px。
- **Win32 行為的實測（U-20261113-01，Windows 11、單一 1920×1080 螢幕）只涵蓋自有的原生 `EDIT` 視窗**：
  `post_key` 每個字只到一次、DWM cloak 過濾與最大化視窗的還原都已驗；還沒驗的：另一個 DPI 的螢幕上的還原（只有一個螢幕）、
  工作列在左或上時最大化視窗存下的還原矩形（工作區座標換算只有單元測試，U-20261113-05）、
  WinUI（新版記事本）／Chromium 等非原生編輯控制項、零面積過濾（有標題列的視窗被系統夾到 202×56，到不了零）。
- **X11／Wayland**：大寫與 Shift 標點的判斷假設 `keysym_to_keycode` 把大寫字母對到小寫的 keycode，沒有對著 X server 跑過；
  `post_key_to_window` 依 keymap 的 Shift 層加 `ShiftMask`（U-20261113-04）也只對 stub keymap 測過。

---

## Wayland 生命週期與驗收

`TODO` — 下列上游行為與原生桌面互動仍需驗證。

### 還沒有答案的

- **`eis_device_pause()` 在 libeis 1.3.901 對 sender client 沒有送出任何東西。**
  對兩個 live device 呼叫 pause 再 dispatch,client 端的 ei fd 4 秒內完全沒有可讀資料。
  所以 `LibeiBackend._on_event` 的 `DEVICE_PAUSED`／`DEVICE_REMOVED` 分支**仍然沒有
  peer 可以驅動**。`eis_verify.py` 把這件事寫成「要嘛有反應,要嘛根本沒被通知」,
  若哪天 libeis 開始送了,client 忽略它就會當場失敗。真的合成器上會不會不一樣,未知。
- **`ei_device_start_emulating()` 的 sequence number 沒有被送到對面。**
  刻意送 4242 過去,server 讀回來是 0。我們這邊的計數本身符合標頭檔的約定
  （每次呼叫至少 +1）,所以不影響正確性,只是從對面驗不到。
- **同意對話框「長什麼樣子、真人要按多久」。** portal 這一層現在驗到的是對話框
  *產生的東西*:准（Response 0）、拒（Response 1）、以及一直不回答。三種我們都在真的
  bus 上跑過,三種都得在自己的時限內收斂。至於真的 mutter 對話框長什麼樣、真人猶豫
  三十秒會不會撞到別的東西,那是 mutter 的事,CI 裡沒有人可以去按它。

## macOS 的修正：CI 驗到一半，其餘要一台真的 Mac

`TODO` — 要一台真的 Mac（Retina，最好接第二個螢幕）

還沒驗的：

- **應用程式是否把 `click_mouse(clicks=2)` 認成雙擊**：只確認了欄位的值，沒有對真的應用程式送事件。
- **`grab_logical`**（`utils/monitor_layout/macos_frame.py`，點座標、逐螢幕擷取後拼接）完全沒在 macOS 跑過。三個假設要實機確認：
  `screencapture -R` 接受含負值的全域點座標、Pillow 的 `scale_down=True` 給出點尺寸的影像、`CGDisplayBounds` 與 Quartz 滑鼠事件同一個座標空間。
  每一格要為每個螢幕各開一次 `screencapture`。CI 的 runner 是 1x 單螢幕，測不到 Retina 與副螢幕。
- **`list_windows` 在真的桌面上的成本與誤列**：沒加 AX 逾時，沒回應的 app 會拖慢列出；同一行程裡與最小化視窗同原點或同標題的螢幕外輔助視窗可能被誤列。

---

## 行動裝置（Android／iOS）：完全沒有在裝置上跑過

`BLOCKED` — 需要 Android 模擬器或實機、iPhone 與 WebDriverAgent；這台機器連 `adb` 都沒有

U-20261009-18 的每一個裝置面呼叫都只對假的 ADB／uiautomator2／WDA 測過。方法名稱與簽章已對 SDK 原始碼核過
（uiautomator2 3.7.1、facebook-wda 1.5.4，U-20261112-04）：全部存在、參數相符；沒有一個在裝置上執行過。還沒驗的：

- uiautomator2：對話框按鈕的 resource id（`ACCEPT_BUTTONS`／`DISMISS_BUTTONS`）是裝置與 OEM 的資料，原始碼驗不到。
- facebook-wda：`orientation` 只回 `PORTRAIT`／`LANDSCAPE`（原始碼的 docstring），`UIA_DEVICE_ORIENTATION_*` 兩個值是否真的會回來未知；
  `app_state` 的 `value` 依 `XCUIApplicationState`（4 是前景），SDK 的 docstring 寫成 1–3，以 Apple 的列舉為準，沒在裝置上看過。
- 旋轉方向：螢幕截圖以面板自然方向回來時，`landscape_left` 轉 270°、`landscape_right` 轉 90°，是從文件推的，沒看過。
- Android：`input draganddrop` 是否存在、`monkey` 啟動輸出、`pidof`／`pm path` 的結束碼、`dumpsys activity activities` 的格式、`pkill -INT screenrecord` 能否收尾 MP4。
  ADBKeyBoard 的送達無法由裝置確認，是從 IME 被選取推定的。
- 已知限制：iOS 捏合忽略 `x`／`y`／`span`；iOS 滑動忽略 `duration_s`（WDA 的 drag duration 是按住時間，不能設移動時間）；iOS `app_state` 不會回 `not_installed`；iOS 的安裝／檔案／錄影沒有 adapter（只有 `MobileExtension` 協定與註冊點）；
  Mobile 分頁的 probe／run 已由 TabTask 在背景執行；真實 SDK 的逾時、取消與裝置回應仍待實機驗收。`AC_android_shell` 刻意不做成 MCP 工具，**請維護者確認**。
- 沒有 `examples/` 的實機腳本以外的 smoke；Xcode／WDA 的建置與簽章只寫成前置條件。

---

## GUI：留下的缺口

`TODO` — U-20261009-27、-28、-34、-36、-38、-40 之後還開著的

- **Windows UIA 後端的執行緒模型**已對真的 COM 驗過一次（U-20261113-01，comtypes 1.5.0 裝在暫存目錄、Windows 11）：MTA 工作執行緒上的 UIA
  讀取可用、焦點事件不需要 message pump、第一次 `import comtypes` 現在依執行緒的 apartment 初始化。還缺的：CI 仍沒有同時有 `comtypes` 與桌面的 job，
  `comtypes` 也不是宣告的相依；`AC_wait_for_focus_change` 被 stop 叫醒的路徑沒在真的 COM 上跑過；`utils/system_volume` 自己的 `comtypes` 匯入不經這條路。
- **Script Builder 的一次性值**：一次執行最多保留 200 個（`MAX_ONE_TIME_VALUES`，留前面的）。
  結果裡內嵌的動作清單以「參數」規則遮蔽，那些欄位不提供一次性顯示。
  對話框從未在真的螢幕上顯示過，真的系統剪貼簿（`QClipboard.clear()`／`text()`）在測試裡是假物件。
  `AC_approval_request` 的 `token`（請求編號）在結果畫面保持可見，但在 log 裡仍被遮蔽。
- **stop 還叫不醒的**：已經進到後端的單一指令（一次影像搜尋、OCR、HTTP 請求、shell 指令）、單一手勢內的節奏 sleep；
  非腳本分頁已傳遞協作取消；尚未檢查 token 的後端呼叫仍只能丟棄晚到結果，須逐一接合。
  ChatOps 的 Slack bot：`/run` 現在在工作執行緒上跑，`/stop` 的反應受輪詢間隔限制（預設 5 秒）；卡在不可中斷的後端呼叫裡的執行仍停不掉，`stop()` 逾時後回 `False`；在輪詢執行緒上的指令 handler 裡呼叫 `stop()` 也會等到逾時。沒對真的 Slack workspace 跑過。
  新轉成可停止的等待裡，`AC_handle_file_dialog`、`AC_wait_until_app_idle`、`AC_wait_for_composition_commit`、`AC_wait_for_unlock` 與行動裝置的 `wait_for_app` 只對假探針測過。
- **WebRTC**：LAN 廣播的註冊與取消已移出 GUI 執行緒，但真的 zeroconf 的時間與名稱衝突行為只對假物件測過。
- **切換主題後那幾個事件迴圈回合內**，以被暫存的頁面為 parent 的 `QMessageBox` 會相對於隱藏的暫存 widget 定位（只影響位置）。
  系統匣路徑在 offscreen 下沒有 tray，`_on_tray_open` 是直接呼叫測的。基準（`benchmarks/gui_*.py`）CI 仍不設門檻。
- **把 Python 建的 widget 放進分頁列在結束時崩潰**：已查明觸發條件——分頁列按鈕上接了 Python callable、又有排隊中的 `deleteLater()`、而行程經 `os._exit` 離開；
  先把 deferred delete 沖掉就不會。機制（Qt 在行程結束時釋放那個 slot）是推論，沒有 C 堆疊可看。`_tab_close_icon.py` 沒有改回自訂按鈕。
- **Qt binding 與 stub 的差異**：`QImage.fromData(x, "JPEG")` 的 5 處仍保留 `# type: ignore[arg-type]`：
  stub 要 bytes，實際的 binding 對 bytes 丟 `ValueError`。
- 遠端桌面的輸入改成佇列送出後，`AC_remote_send_input` 回的 `{"sent": True}` 意思是「已排入」；`SO_SNDTIMEO` 的 POSIX 包法與經 TLS socket 的行為沒在這台機器上驗過。
- 沒在 macOS／Linux 上看過新的關閉鈕、捲動與重設樣式；沒在真的多螢幕桌面試過視窗位置還原；PyBreeze 沒有對這一版跑過；各語系新增的字串（日文、簡體中文）沒有母語者看過。

---

## 這一輪修正留下的後續

`TODO` — 下列整合、安全與平台驗證仍未完成。

- **Intel Mac 安裝要編譯 `cryptography`**：下限拉到 50 之後 `macosx_10_9_x86_64` 沒有 wheel（探測：最新只到 48.0.1），
  `pip install je_auto_control` 在 Intel Mac 需要 Rust 工具鏈。沒有在 Intel Mac 上實際編過。
- **簽章分離擋不住能寫檔的人**：能執行寫檔指令（shell、檔案類指令）的人仍能換掉公鑰檔本身，保護那個檔是作業系統權限的事；
  私鑰支援選用通行碼加密，未設定時仍是明文 PEM（0600，Windows 上沒驗權限位元）；遷移模式開著時 HMAC 簽章會被接受。
- **RBAC**（`JE_AUTOCONTROL_RBAC_USERS`，預設關閉）：
  - `ac_list_plugins` 的外掛 factory，以及 `ac_web_list_commands`／`ac_web_current_url` 的實際相依版本初始化契約尚待審查；目前不列入唯讀目錄，完整目錄仍要求 `read_data`。本機 sibling 原始碼不代表部署版本驗收。
  - `ac_diagnose` 的預設 audit-log 初始化可能建立固定目錄及 SQLite schema；全域零寫入診斷與外部 SDK 初始化副作用仍未驗證。
  - 尚需完整審查未列入 `COMMAND_CAPABILITIES` 的 executor 指令；未列指令目前仍依賴提交入口授權，不能把已核對的指令視為完整分類。若改為執行時預設拒絕，須同時處理預檢中的動作清單與一般資料串列，避免誤拒正常資料。
  - 沒對真的 client（Claude Desktop、VS Code、內建 dashboard）試過；回送測試的 SSE、無狀態、`subscriptions/listen` 與 TLS 結果不代表真實客戶端通過。
- **MCP 路徑根目錄**（`JE_AUTOCONTROL_MCP_PATH_ROOTS`，預設關閉）：`path-or-other` 已檢查
  `ac_open_path`／`ac_plan_open`／`ac_file_association`／`ac_act_in_view` 的 `target` 與 `ac_handle_file_dialog` 的 `path`，
  限於可辨識的絕對路徑、已存在的相對路徑及 `file:` URL；保留原字串，不代表能限制應用程式自行解讀的路徑或尚不存在的相對路徑。
  仍管不到執行動作清單的工具、`ac_launch_process`／`ac_shell` 的 `argv`／`command`、
  自由格式物件裡的路徑（`ac_run_suite` 的 `spec`、`ac_run_dag` 的 `definition`、`ac_assert_all` 的 `specs`）與沒標註的外掛工具。
  檔案 symlink 的跳脫在這台機器上建不出來（只跑了目錄 junction）；POSIX 的 `:` 分隔與 `~` 沒在 Linux／macOS 跑。
  `roots/list` 來的根目錄要另外開 `JE_AUTOCONTROL_MCP_PATH_ROOTS_FROM_CLIENT` 才算數——這是實作時定的，請維護者確認。
- **USB passthrough 實機驗收**：仍須對真的舊版 host、WebRTC 通道與 USB 裝置驗證長時間 transfer、
  裝置逾時、通道 ERROR、晚到回覆與重新連線。現有 fake channel／backend 測試不能代替這項驗收。
- **變數範圍**：free-threaded 原生執行緒繼承與同時存取範圍的行為尚未實測。
- **遠端桌面的擁有者模型**：Quick Connect 沒有狀態列，它的連線被取代時視窗只是關掉；主機的 Stop 會停任何擁有者開的 host（刻意的）；
  只用假的 viewer／host 測過，真的 viewer 被擠掉時會不會觸發 `on_error` 而多跳一個警告框，沒看過。

---

## 雜項

`TODO` — 小項目，各自獨立

- **free-threaded**：呼叫者身分、綁定的裝置、自愈的執行標記與 stop token 都改成只在設定它的執行緒上有效（`utils/thread_bound.py`）。
  這台機器沒有 free-threaded 直譯器：驗證用的是模擬繼承與真的 `-X thread_inherit_context=1`（3.14.7，GIL 開著）；`free-threaded-scope` job（3.14t）是第一次真的跑。
- **Windows 的版面鍵名**（`slash` 等 8 個）只在美式配置上實際呼叫過。

---

## Computer use 的預設還是 beta 的 `computer_20251124`

`TODO` — 在 `claude-opus-5`（兩種形式都接受）上實測 GA toolset 後，把它設成所有模型的預設

驗收入口：`utils/agent/backends/anthropic_computer_use.py` 與 `_computer_toolset.py`。
需驗證多呼叫回覆、toolset 名稱、截圖尺寸、座標換算與 zoom；未取得真實 API 證據前，
其他模型的預設切換仍待完成。

---

## Agent 的歷史壓縮還沒對真的 API 跑過

`TODO` — 需要付費實機跑一次多步驟任務；離線測試只驗得到請求的形狀

需驗證 `utils/agent/backends/anthropic.py`、`anthropic_computer_use.py` 的 beta／GA 路徑，
以及 OpenAI 歷史剪裁在真實 API 上的行為：

- 重開的歷史在強制 thinking 綁定的帳號（Opus 5.5／Fable 5.1）上是否被接受。
- 模型只憑摘要能不能接著做——上限是 3，大約每 3 張截圖就壓縮一次，摘要最多列最新 60 個動作、每個截到 240 字元。
- 真的桌面 PNG 的請求大小離 32 MB 多遠。
- 兩個後端都沒送 `cache_control`，所以現在本來就沒有 prompt cache；要開的話是另一個請求形狀的改動。

---

## libei 半開交握的原生資源回收尚待驗證

`TODO` — D2 預設輸入路徑已有具有限 IPC／期限／取消的獨立 EI helper；仍需原生驗收，
不能直接移除 `linux_wayland/libei.py::_teardown` 的半開保護。

直接使用 `LibeiBackend` 的路徑仍在呼叫程序內；半開交握失敗仍可能留下 context／fd。
須在支援的原生環境驗證預設 helper 結束後的 context／fd 回收、原生按鍵釋放與其他擁有者不受影響。
合成子程序的退出、ACK 與 cleanup 回覆不等於合成器已釋放輸入，也不能解除未知輸入結果。
`docker/libei_verify.py` 與 `docker/eis_verify.py` 保留原生故障／成功邊界檢查；
裝置暫停與序號回讀、真實合成器權限流程仍待對應環境驗證。

---

## `test_usb_acl_prompt.py` 讓 Python 3.10 的 headless 測試間歇 segfault

`TODO` — `test/unit_test/headless/test_usb_acl_prompt.py::test_bridge_remember_persists_acl_rule`
在 Python 3.10 的 Linux／macOS `coverage run -m pytest` 中仍有間歇 SIGSEGV（exit 139）紀錄。
需在對應環境開啟 `faulthandler` 重跑並定位原生呼叫；單次重跑通過不足以證明已修復。
2026-11-02 起不再支援 Python 3.10，CI 不再跑 3.10；同一機制（分配時觸發循環回收）在 3.11 也存在，改看 3.11 的方格。

---

## PySide6 6.12：headless 測試跑完後直譯器結束時崩潰（全平台）

`TODO` — 維護者 2026-11-14 決定全面固定回 PySide6 6.11.2（U-20261114-03；dependabot 忽略 6.12.0），待之後的 6.12.x 或找出 closure 後再升級並重驗。先在容器看到（U-20261114-01：`docker.yml` 4 次 3 次 SIGSEGV）；到 `1d372dba`（PR #552，2026-11-14）已是**每一格**：全部測試通過後，Ubuntu 3.14 exit 255（glibc `malloc_consolidate` abort）、macOS 3.11 `Fatal Python error: Aborted`、Windows 3.11／3.14 access violation、3.13 `Aborted`，Windows 3.12 在 `test_gui_offthread_sites.py` 中段 abort。本機 Windows 3.14 的完整套件沒有重現。
- Ubuntu 的 gdb 堆疊（dev run 43484575781）：`destroyQCoreApplication` → `visitAllPyObjects` → 某個 QObject 的 `~QObject` 釋放接在它訊號上的 Python 函式 → `func_dealloc` → closure cell → 一個 widget 的 wrapper 歸零 → `~QWidget` → `~QScrollBar` → `free()` 重複釋放；前一行是 `shared QObject was deleted directly`。即 closure 握有最後一個參考的 widget，在結束時被 shiboken 與 Qt 各刪一次。是哪個 closure 還不知道。
- 試過把分頁關閉鈕的 lambda（握住頁面）換成 bound method，或改用 Qt 內建關閉鈕：`test_gui_lazy_registry.py` 的探針在 `os._exit` 10／10 崩潰（HEAD 13／13 正常），已還原；這條路徑本身就是「把 Python 建的 widget 放進分頁列在結束時崩潰」那一項。
- 兩次在測試全部跑完後的直譯器結束：`Py_FinalizeEx` → `PySide::runCleanupFunctions` → `destroyQCoreApplication`
  → `BindingManager::visitAllPyObjects` → `QObject::~QObject`，前一行是 Qt 的 `shared QObject was deleted directly`。
- 一次在測試中段（約 46%）主執行緒的 `Shiboken::BindingManager::runDeletionInMainThread()` → QtWidgets。
- 不是 Python 3.12 或容器映像特有（每個平台與版本都有）；還不知道是哪個測試留下了被兩邊刪除的物件。
  上游查無相同回報。`docker.yml` 現在以 gdb 跑、`-X faulthandler`、`-v`，下次中段崩潰會有測試名稱。
- 升級回 6.12 前要做的：在 PR 上跑完整矩陣（含 `docker.yml`）確認結束時不再崩潰；或先找出握住 widget 的 closure（上面的分頁關閉鈕實驗顯示改動它會改變崩潰點，不是單純移除）。

---

## Agent 電腦接管與任務自動化

`WIP` — **依使用者恢復目標繼續交付；個別原生／真機／24 小時驗收仍暫緩。**
個別原生／真機／24 小時驗收也維持暫緩，不能因恢復一般開發而一併啟動。
完整交付契約：`docs/superpowers/plans/2026-10-23-agent-runtime.md`。
以下僅列未完成的實作、設定與驗證步驟；本批收尾不代表 P0–P9 全部完成。
目前驗證紀錄：docs/updates/2026-10-e.md #U-20261030-58；原40項與暫緩驗收仍未結案。
功能開發位置：`D:\Codes\AutoControlGUI\.worktrees\agent-runtime`，分支 `feat/agent-task-runtime`；
WebRunner 對應位置：`D:\Codes\WebRunner\.worktrees\agent-managed`，分支 `feat/managed-browser-sessions`。
WIP（整合，2026-10-30 起）：將 AutoControlGUI `dev` 快轉至 `feat/agent-task-runtime`，WebRunner `dev`
合入 `feat/managed-browser-sessions`。順序：完整 headless 套件與文件計數測試在分支上通過 → 確認
Jeffrey_RPA 未執行、通知同儕 session → 主工作樹舊的 Progress 鏡像備份後由分支版本取代 → 快轉並跑
Jeffrey_RPA 的 test_je_facade → 推送 `dev`（會觸發 je_auto_control_dev 發布）前先經使用者確認。
整合不等於部署：正式服務、受管 Chromium 與 Jeffrey_RPA 批次的部署／回復仍依下列 P4。
接續第 5 組 browser／remote reader、第 3 組非 Windows helper 與第 6 組跨主機剩餘驗證，
並核對第 4 組裝置來源及第 8 組正式交付。

1. **P4：瀏覽器與正式環境接合**
   - 選定正式服務專用 helper Python、AutoControl／WebRunner 套件版本與受管 Chromium 安裝；
     以已審閱的主機 profile 明列工具、來源與產物根目錄，再驗證正式服務載入該環境。
     隔離候選、固定套件鎖、實際標準 helper IPC 與逐檔比對見 stage104；仍須選定穩定路徑、
     審閱實際工具／來源／根目錄並安排部署，不能直接採用暫存候選或宣稱瀏覽器已啟動。
     Python 相依與介面驗證不能代替受管 Chromium、實際登入／頁面及原生證據。

   - 核對既有瀏覽器呼叫者各自的環境是否已安裝相容 `je_web_runner`。舊 bridge 依賴呼叫環境的
     SDK，不會自動使用受管 helper；缺套件時應保留明確失敗，不能退回其他瀏覽器引擎。
   - `DECIDE`：部署／回復計畫已寫成 `docs/superpowers/plans/2026-11-01-deployment-rollback.md`（未執行）；
     其中標「待決定」的回復方式、helper 直譯器、套件鎖、Chromium 與主機 profile 待維護者批准。
     正式變更前仍須依該計畫安排主工作樹、既有 Jeffrey_RPA 批次與服務的部署／回復；不能直接將
     功能工作樹當作已部署版本，也不能替換共用 `.venv` 或自動重啟正式服務。
     舊版回復須先取得輸入退場確證，審閱相符的升級前狀態及原位置，並從全部舊版任務根目錄
     排除留存的新版私有檔案；不能讓不識別新私有根的舊程式沿用新版資料庫／快取。
     須比對來源／成品雜湊，不能只看相同版本號；保留不明 journal，不重播副作用。
   - 瀏覽器統一使用 WebRunner（`je_web_runner`），來源 `D:\Codes\WebRunner`。
     真實頁面驗收尚缺登入狀態、目前頁面身分、表單讀回、獨立 DOM 完成條件、來源限制、
     上／下載權限與摘要、非預期視窗／對話框、逾時／取消及 session 清理證據。

2. **P4／P2：四條流程的實際應用驗收**
   - 查詢／下載／歸檔：真實來源、完整下載、命名衝突、取消、摘要與獨立檔案清單驗證。
   - CSV／Excel 批次填表：資料驗證、逐筆新紀錄切換、讀回、提交前舊確認值拒絕、成功／失敗／
     待確認清單與中斷後人工審閱。
   - 跨應用欄位轉移：來源擷取、轉換、指定目的地填入、提交／儲存及獨立成果確認。
   - 工作區準備：指定程式／文件、視窗排列、就緒檢查、未知對話框與未儲存內容暫停。
   - 覆蓋外部 agent、本機模型及固定 skill 的完整路徑；模型停止或舊收據不能取代完成證據。

3. **P1／P7：跨平台桌面與真人接回**
   - Windows：實測持續來源的注入事件排除、鎖定、
     真人接回、明確恢復與閒置 60 秒條件。原生 HWND／PID、遮擋、縮放與輸入清理仍缺實測。
     原生驗收解除暫緩前，仍缺 Raw Input 實體／注入／觸控涵蓋、
     真實本機 console／鎖定轉換、來源／helper 崩潰與輸入清理的實測證據，
     不可用虛擬來源、受控原生後端或局部 IPC 成功取代。
     歷史固定版本的 DAG 同目標提交 HTTP409 原因仍未明；後續完整執行沒有拒絕回應
     不構成該次原因已修復。保留 stage117 原始失敗及後續實際拒絕內容的追查，
     不放寬既有提交／等待／清理期限，也不重播已完成效果。
   - macOS、X11：真人活動來源已實作（`presence_quartz.py`、`presence_x11.py`，U-20261101-06），
     由 `presence_platform.py` 依平台選用並由既有來源迴圈與 60 秒閒置狀態機執行；仍缺：
     macOS 的 presence transport（Linux 的 worker／broker／server 已改經 `presence_pipe_linux.py`，
     U-20261101-13；reader 已接可信 Linux endpoint，原生執行未驗證）、觀察目標身分、
     視窗範圍輸入、自有 helper 隔離與非 Windows 對話框／未儲存 gate，以及以真實實體輸入
     驗證「實體／注入」判定的原生驗收（CI 只能證明注入事件不被誤計）。
     Wayland：一般 client 看不到全域輸入，也無法區分 libei／uinput 注入與真人，目前沒有可信來源；
     須另定可信來源（例如受權限保護的 evdev 讀取或 compositor 協定）後才能實作。
     目前不能解除不支援平台的共用桌面拒絕保護。
     Linux：presence_channel_linux 已接入自有 worker 啟動與可信 endpoint 傳遞（worker 經自有 bootstrap 回報
     endpoint，broker 只採用它，連線時核對 listener 程序），並沿用既有 presence challenge／lease；
     核對實際 helper 世代、故障退場與完整應用接合，不能以獨立元件 IPC 取代這些證據。
     程序／逐訊息身分及受保護路徑不代表桌面權限，也不能隔離同 UID／特權敵對程序；
     使用者空間有界等待不能冒稱核心 syscall 的硬即時完成，未知清理仍不得移交控制權。
     POSIX 本機 channel 已在 SIGCHLD 被忽略時拒絕啟動，且只在未回收的 leader 仍保有群組 ID
     時才送出 killpg；leader 已被他處回收時拒絕送訊號並保留未 retired（stage147，WSL 實測）。
     仍缺：以 setsid 等方式離開群組的後代無法由本機 channel 觸及，送出訊號、主程序退出或單次
     錯誤碼均不足以證明全部後代已退出，須靠 owner 服務的 cgroup 退場；涵蓋既有環境探測、
     桌面／瀏覽器及遠端 helper 呼叫者的實際驗收亦仍待執行。
     正式繫結仍須核實取消發生於 native spawn 期間的所有權、失敗清理、群組與逸出後代退場，
     並補受支援版本／架構驗證；隔離原型與直接子程序驗收不等於正式 helper 已接合，安裝前仍須比對。
     不得把原始逾時改稱 registry 死鎖，也不得放寬原始 10 秒期限或改動跳過政策。
     presence_worker 已接平台 source／pipe／security；broker 已把 inherited nested grant
     傳給每個 source 的 owned channel。仍須建立可信登入／seat 權限與來源環境，
     並驗證真正登入、鎖定與實體活動來源；服務的空白環境不提供 DISPLAY／XDG_SESSION_ID。
     已安裝固定模組的未支援回覆及正常 EOF 退場不能證明實體來源或完整後代退場。
     不得替換空白 initializer 或偽裝 Wayland session 取代完整應用驗證。
     獨立 owner 核心仍須完成每筆記錄的啟動、取消、句柄發布、執行緒回收與服務端持續所有權；
     失敗 clone 的輸出暫存值不得當成擁有的 fd，晚到成功必須接管後清理，啟動確認遺失亦不得漏失。
     須涵蓋建立執行緒回傳前 worker 已完成、建立失敗、記憶體配置失敗、失去通知及句柄重用。
     每個 nested helper 仍須獨立受保護子樹；關閉來源保留 broker 與 sibling，關閉父程序則等待
     所有後代啟動解決、子樹清空與精確目錄移除。mkdir 成功但 open 失敗仍須保有清理責任。
     stage150 已在 WSL distro 內以 root 佈建並執行受保護驗收（連續三次 13 項全過）：payload
     帳號無能力且無法遷出、以 setsid／雙重 fork 逃離的後代仍被 cgroup 收回、guardian 與服務
     崩潰後冷復原收回孤兒程序；並行 session 互不影響，受保護父程序也能以 fd 4 授權開啟子 lease
     並在其容器內啟動子 helper；START 後立即關閉的競態循環皆退場且無殘留（連續三次 18 項全過）。
     仍須核實 clone 瞬間的確定性取消、多層
     nested 與其他核心／發行版；單一 distro 的結果不代表所有部署。
     stage138 已於隔離 staging 實作 native_service（guardian 授權握手、逐封包 sender 驗證、
     lease 發行／關閉、scope owner 生命週期與 drain），但僅有 peer/lease 證據；正向 bootstrap
     未執行（此環境無服務擁有的 delegated cgroup2）。獨立審查的發現已全數回應（nested 授權、
     子程序 fd／訊號／能力設定、namespace、START 重驗、服務入口）。stage139 已讓 nested
     capability 經 worker 私有 bootstrap pipe（fd 4）只交付給該紀錄自己的子程序，並以 fixture
     驗證；受保護路徑「payload 發布後才交付」仍未實際執行。stage141 已加入 worker 擁有的應用程式中繼（fd 0／fd 1、各 64 KiB、
     OP_WRITE／OP_READ），以 fixture 子程序與閘門下的紀錄驗證；stage142 加入 OP_OBSERVE，並以
     _Static_assert 固定 C 與 Python 兩側的封包配置。guardian 有持久 journal（stage144）與程序
     （stage145）；stage149 改由 guardian 擁有 listener、驗證 client 的帳號與 namespace 後才把
     連線交給服務（依 2026-10-29 決定）。stage150 依實測修正 cgroup 配置（委派者只能在共同祖先
     的 cgroup.procs 可寫時搬移程序：epoch-N 為委派根、service-N 為 root 擁有的葉節點、records
     為授權給服務的錨點），服務以 guardian 給予的 ambient CAP_SETUID／SETGID／SETPCAP 執行，並在
     WSL 完成受保護端到端驗收（實際 client、受保護 payload、RETIRED 回報、未列帳號被拒、冷復原）。
     正式入口在安裝版本仍維持關閉，開啟前仍須獨立審查；僅 `NO_PROTECTED_ACCEPTANCE` 驗收建置
     開啟。
     位置：`.worktrees/agent-tools/stage138/`（todo.md、review.md）、`stage139/`、`stage141/`
     至 `stage150/`。
     OwnedChannel 的 close 已不再等待 request 鎖，另一執行緒可中止等待中的請求，close 開始後
     不再交付任何回覆（含已排入佇列者）。`helper_owner_linux.py` 以相同介面經 owner 服務運作
     （每個 channel 一條連線與 lease、OPEN／START 以固定 nonce／request ID 重送、依 nonce
     略過過期回覆、close 只等待單一呼叫並在服務觀察到 helper 結束後才標記 retired）；已在 WSL
     對實際 C 服務端到端執行（僅 acceptance build 以未受保護的 fixture 紀錄代替閘門後的受保護
     啟動，因此 close 正確地拒絕宣稱 retired）。nested helper 已能讀取 fd 4 並以 OPEN_CHILD 開啟
     子 lease（stage146，對實際服務只觀察到閘門下的拒絕）；presence broker 的入口尚未呼叫讀取。
     5 類呼叫者已改經 `owned_channel` 取得 channel：
     Linux 若有主機安裝的 root 擁有綁定檔，只能經服務啟動清單中完全相符的 argv，不退回本機程序。
     已決定（2026-10-29）：Linux 無綁定時繼續以本機 channel 執行 helper，runtime status 回報
     not_configured。Linux presence 已有私有 socket 傳輸及 owned-launch endpoint 經 broker／pool／host
     傳入 helper 的路徑；標準桌面准入仍限 Windows，Linux seat／真人活動與 nested grant 的完整接合仍待完成。
     Linux-only socket 端到端測試尚未本機執行：既有 WSL validation distro 的 ext4.vhdx 遺失，
     啟動回報 Wsl/Service/CreateInstance/MountDisk/HCS/ERROR_PATH_NOT_FOUND；不以 Windows IPC 或 mock 通過代替。
     parent_watch、輸入 journal／lease 與本機 pipe 執行緒退場仍須接合。
     owner 服務原始碼依 2026-10-29 決定已進入 `native/owner_service/`（src、manifest 範本、build.sh、
     tests 與兩個驗收執行器，不進 wheel），每個 client 帳號的 lease 配額已實作。
     現況：經四十一輪獨立審查（處理紀錄見 docs/updates/2026-10-e.md，U-20261029-23 起），第二十三輪
     審查 U-20261030-36 未發現 MAJOR 或 MINOR；第二十四輪審查 U-20261030-38（補齊先前延後的測試與
     載入檢查）、第二十五輪（U-20261030-39）與第二十六輪（U-20261030-40）亦未發現 MAJOR 或 MINOR，其 NOTE
     分別於 U-20261030-39、-40、-41 處理（-41 只動測試與文件）。第二十七輪審查 U-20261030-42（epoch 私有
     暫存根目錄與已安裝主機驗收）的 MAJOR／MINOR 於 U-20261030-43 處理；第二十八至四十一輪無 MAJOR，其
     MINOR 分別於 U-20261030-44 至 -57 處理；第四十二輪無 MAJOR 亦無 MINOR，判定路徑隱藏檢查
     已無剩餘缺陷（唯一 NOTE 為措辭，已於 -57 修正）。
     正式閘門另因下列項目關閉。
     驅動桌面／瀏覽器的 helper 一律以本機程序執行，owner 服務只承載不需顯示的 helper（探測、遠端裝置）；
     遠端 helper 與實體裝置的通訊屬暫緩的實體裝置驗收。
     已知限制（未寫進服務 README）：清除只依使用者 ID 判斷，隔離區保留其他 ID 擁有的內容；NSS 服務中斷
     而回報 ENOENT 時，manifest 的 payload ID 會被當成「未配置」；同一檔案系統上的 bind mount 只在清除
     自己的 namespace 中卸下。
     WSL 主機的兩項未滿足需求（core_pattern、/mnt 可寫）經使用者決定維持為已記錄的主機發現，不調整發行版
     設定（U-20261030-58）；正式部署主機須依服務 README 滿足全部主機需求。
     TODO（使用者決定暫緩，與原生／真機驗收同列）：其他架構／libc／核心的相容性驗證（需 WSL 以外的
     環境）才能開啟正式閘門；不能匯入時下載或暗中部署服務。
   - Wayland 接既有改版 D1／D2：portal session 關閉／恢復、compositor 重啟、觀察擁有者 context、
     helper／半開交握回收與取消／停止生命週期，避免兩條實作各自接管相同原生資源。
   - 驗證相同實體桌面在不同 profile、資料庫、服務及 DAG 節點間仍只有一位輸入擁有者；
     未知 worker／按住輸入／清理失敗時不得移交或竊取租約。

4. **P7：Android／iOS 受管裝置**
   - `WIP`：裝置端 helper 依使用者 2026-11-01 決定自建，於 CI 建置與測試（`native/android_helper/`，
     U-20261101-11、-12）。第 1、2 階段已完成：`FenceLedger`／`ProtocolHandler`（JVM 測試）與
     instrumentation app（只服務 shell／root 對端、注入器在柵欄後釋放輸入；CI 建出 debug APK）。
     `TODO`（第 3 階段，使用者 2026-11-01 決定）：把受管 Android 的送出路徑從主機端 ADB session
     （`dispatch_checked`）改為經 helper 的 begin／settle，舊的 adb input 路徑不再用於受管任務；
     並重驗本項列出的六種順序／重複拒絕、ACK 前拒絕、撤權與真人接回。同時寫主機端 provider、
     `getevent` 實體輸入來源與第 4 階段 CI 模擬器測試；真機驗收仍暫緩。排在非 Windows 在場服務鏈之後。
   - 為 `utils/agent_runtime/android_adapter.py` 實作並審閱真實 `AndroidControlProvider`／
     `AndroidCommandLease` 來源；須有裝置端執行機制，在真人接回、取消／逾時後阻止舊寫入，
     並提供逐命令 ID／boot／epoch 相符的輸入釋放、遠端佇列清空與舊 writer 退出證據。
     主機 lock／context manager、結束本機 ADB helper、shell 返回或 Android 階段都不能替代。
     補可信真人活動、已按下輸入、閒置條件與全域監看器的即時審閱；沒有來源時保持拒絕就緒。
     提案／證據的 `input_authorized=false` 不得當作批准，只有完整前置拒絕證明此命令未呼叫輸入；
     返回／後置拒絕仍不授權重試或清除未知 journal。
     WDA 還須實作 `RemoteDeviceAdapter` 與同等來源；真實 provider／SDK 契約確認後才接
     `target_config.py`／`target_factory.py`。內部橋接與模擬裝置都不代表已可正式受管執行。
     在實際 SDK 重驗合併焦點擷取的六種順序／重複拒絕、原期限、ACK 前拒絕、begin 後取消／逾時、
     錯誤裝置／世代、撤權、真人接回，並確認原生診斷仍不含敏感參數；
     亦須驗證唯讀路徑禁止輸入與清理失敗隔離；不得重播、更換 helper 繞過或代送桌面釋放事件。
     數字 transport ID、shell-v2 的退出碼或本機 socket 結束都不足以證明裝置／輸入安全。
     為 `android_hierarchy.AndroidHierarchyReader` 接入真實、限 app／window 的來源與安全文字授權，
     核對 SDK／服務的身分、完整度、生命週期與不干擾其他無障礙擁有者的契約；不可直接貼上
     要求的 snapshot 當作來源證明，也不能默用會建立 UiAutomation 的 dump CLI 或重啟服務。
     無 reader 的 metadata、遮罩值、部分文字及 SDK import 成功均不能宣稱完整畫面／原生可用。
     補受保護輸入欄位值的有限比較／獨立驗證、豐富欄位狀態條件、Unicode／IME，以及旋轉／縮放／
     多顯示器、版本／OEM 格式核對；不能把有限 ASCII／現有單視窗解析當作完整裝置輸入支援。
   - 為 ADB／WDA 各自建立可信的實體裝置識別、舊 writer 退出與清理／世代證據來源；核對真實
     SDK 契約，證明新世代能使所有舊指令失效且不重播。沒有可信來源時維持拒絕恢復。
   - 部署時明定每台裝置唯一的權威服務與受保護資源位置。預設使用者目錄內的 OS lock 只協調
     同帳號的本機程序；跨作業系統帳號／主機須共用可信協調端，不能各自取得同一裝置。
   - 將現有 ACK／耐久 journal／未知副作用隔離測試延伸到實際 SDK 的重連、重試、app scope、
     跨資料庫競爭、權限撤銷及主機崩潰路徑；SDK 模擬通過後仍須另排解除暫緩的真機驗收。
   - 建立以裝置及 app 身分固定的主機 profile、有限工具集與 scope；接既有 ADB／WebDriverAgent
     路徑，不把任意 shell、主機或執行參數交給模型。
     接合前核對 SDK 的實際裝置身分、重連／重試與清理契約；ADB 不得誤啟動或終止共用 daemon，
     亦需遮蔽逾時／例外中的命令參數。WDA 未提供的世代／閒置保證不可自行假定。
   - 接合觀察版本、元素參照、app／裝置身分、敏感內容遮罩、動作後讀回與完成驗證。
   - 以實體裝置身分協調互斥，處理斷線、app 切換、連線／helper 世代及權限撤銷。
   - 遠端動作逾時或 ACK 遺失須保存未知副作用；本機 helper 結束不等於裝置停止。
     補清理確證、資源隔離／保留及具證據的人工恢復後，才可允許另一任務接管。
   - 加入服務／API／AC／MCP／REST／CLI／Builder／薄 GUI、能力診斷與無真機回歸，
     最後才安排已解除暫緩限制的真機驗收。

5. **P5／P9：中斷狀態恢復與技能驗收**
   - 安全恢復策略已交付：任務可宣告 `resume_conditions`（只接受 screen／browser／file_* 新觀察條件），
     第一個動作須在新觀察全部通過後才被接受（`resume_gate.py`，U-20261101-08）。仍缺下一點的實際應用驗收，
     以及由操作人為各流程寫出合適的條件；關卡本身不會自動推斷登入或視窗狀態。
   - 將經審閱的新任務流程延伸至實際登入／欄位／視窗狀態重建與四條應用流程驗收；為舊 capture／
     指標步驟提供可信新來源與語義轉換，不能把舊索引／座標或歷史欄位值直接移入新 session。
   - 補實際應用的語義錄製、參數化、候選修復、驗證 trial、人工接受／版本發布及執行中固定版本
     的完整驗收；持續拒絕沒有完整動作確認或獨立完成證據的試跑，不能僅憑舊收據發布。
   - browser 仍須完成實際登入／欄位／視窗狀態重建、原 helper／SDK context 的完成讀回、
     永久輸入／網路退休與技能的真實應用驗收；受控模擬頁面／IPC 證據不能取代原生驗收。
     remote 完成審閱／驗證／技能發布仍缺真實 SDK／裝置世代、永久唯讀來源、清理確證與
     舊 writer 結束證據；接入既有私有完成預覽／建立／執行與 API／GUI，不以旗標、另開 reader、
     舊動作收據或重播輸入替代。網路結束後的即時 DOM 不能當作新伺服器回應；未知隔離不可解除。

   - 針對新增平台／裝置及恢復路徑重驗服務重啟、WorkQueue 去重、事件／排程重新授權、
     journal／history／產物關聯及 30 天保留／清理，不擴大既有權限。

6. **P8：多 agent／多機的剩餘接合**
   - 單機的角色邊界稽核與提示注入回歸已交付（`docs/AGENT_TASKS.md` 的 Role boundaries 表、
     `test_agent_role_boundaries.py`，U-20261101-10）。仍缺：在實際多主機部署上重驗跨節點的角色證據
     （目前只有回送／模擬主機的測試），依下方部署項目一併進行。
   - 為實際主機配置受保護的 runtime 端點、背景派送、主機憑證與相容完成契約；明確記錄遠端
     目錄／目標設定、部署／回復方法（多主機步驟見上述計畫第 6 節，主機與憑證待決定）。
     受管任務 DAG 不會自動部署遠端服務。
   - 跨主機成果移交仍須完成實際受保護端點、跨實體主機與正式環境交付；
     各有限來源／接收／採認案例的
     驗證不能取代實際遠端部署及目前來源／接收端的應用狀態證據。
     核對讀寫權限、當前來源／接收身分、原始提交與私有完成授權、摘要及目的端發布；
     本機路徑、匯入收據或協調端摘要不得冒充遠端檔案／完成證據，也不得轉送本機權限。
     核對兩／三主機故障矩陣：原 host／token／帳戶／origin 變更或撤銷、來源到期、讀者同意、
     冷重啟與晚回覆、發布／取消交錯、舊派送 schema、多次續行 origin、精確產生者退出、
     未知暫存與清理失敗、未決批次、配額回收及重啟後仍固定的來源／目的端／證據期限。
     保留原有本機 DAG admission／憑證與跨程序 host binding 核對；實際本機祖先不能因 wire grant
     省略、變更 tags 或補造提交列而繞過。standalone 與真正遠端節點沿各自實際接受憑證處理。
     技能契約須核實來源主機的真實動作、原 trial／版本及當前權限；規範未要求補造協調端外國任務。
     歷史 D 磁碟 2／3 秒協調與 HTTP 準備逾時的原因／部署影響仍須追查；C 預設暫存的完整成功
     不代表所有磁碟上的相同期限均已根治。舊失敗與階段觀測保留於本次月誌及 stage74–104。
     真正受保護端點、跨實體主機與正式環境驗收仍依第29／31項完成；不得直接部署功能工作樹。

   - 實際多機驗證斷線／晚到回覆、主機重啟、憑證撤銷／變更、協調端中斷及同資源序列／
     獨立資源並行；未知清理不得讓下游成功或搶走遠端控制權。

7. **P3／P6／P7：能力、模型及共用介面驗證**
   - 被動就緒診斷已交付（`agent_runtime_readiness`，U-20261101-05）：桌面輸入／擷取、真人在場來源、
     Android／iOS 控制、瀏覽器與本機模型各自回報 unsupported／missing_dependency／unauthorized／
     not_probed／not_recorded。仍缺「實測成功」（measured）：只能由受保護的原生驗收紀錄提供，
     須待原生驗收解除暫緩後接入；在此之前診斷不得回報 measured，也不主動探測原生 API 或連線裝置。
   - 為自訂／外部 target 補經審閱的語義觀察與遮罩覆蓋契約；沒有能力旗標的舊 target 仍沿用
     既有判定，不能因此宣稱已證明完整畫面或遮罩內容的不存在。深化部分證據的計數／狀態／
     變動判定與受保護欄位比較，目前缺少充分證據時仍為未知。
   - 本機 Ollama 模型／端點尚未設定（使用者2026-10-28確認）；待明確配置已安裝的
     工具／視覺模型與本機端點後，補模型不符、拒絕連線、逾時、取消、預算與完成驗證的
     端到端證據；不可自動下載或切換外部服務。
   - 新增／深化功能須同步公開 API、命令目錄、MCP／REST／CLI／Builder、薄 GUI Actions 及語系，
     並重驗匿名／具名權限、來源限制、GUI 關閉／重開、服務獨立生命週期與跨 session 隔離。

8. **P0–P9 最終交付核對與檢查**
   - 每條交付契約整理實作、無頭回歸與原生／真機證據對照；補新平台／多機／恢復情境的漏洞，
     區分已實作、尚缺實作與只缺實測，不能用模擬目標取代原生驗收。
     歷史證據檔不自動認領或刪除。

   - 於整份規範最後固定提交重跑完整 headless 與 coverage run -m pytest、跨功能／故障恢復回歸；
     後續平台／恢復修正亦須納入完整 coverage 及新成品逐檔比對；
     後續修正不得沿用較早提交的完整驗證；來源、測試、設定與文件須重新固定並核實。
     目前功能工作樹完整成功的來源範圍與133項跳過原因見本次月誌，不能替代尚缺的原生／裝置驗收。
     歷史原因仍須追查：stage74 的管理員 host binding 與 retention uncertain／phase 前置失敗；
     stage85 的 default_connection_discovery_change、expired_origin_can_be_replaced_only_for_never_dispatched_scoped_work
     及 retention queued_child／executing／fresh_delivery；stage88–93 的3秒來源匯出／匯入準備逾時。
     C／D 儲存尾延遲對照不構成所有磁碟的根治；保留原始失敗與收據、逐案確認實際耗時／未知狀態，
     不放寬2／3／15秒期限、不改 WAL／耐久性、不重播已完成效果、不以局部通過抵銷舊失敗。
     test_dag_managed_loopback 的完整執行曾遇提交 HTTP409／限流，尚缺最初拒絕原因；
     stage71 matching_grant_digest 的首次 observe 曾耗盡15秒 bootstrap，仍缺啟動堆疊／耗時原因。
     共用 pytest-current 的 WinError5 權限／生命週期問題仍未修復；不得刪除共用連結、改共用環境
     或將自有新 basetemp 成功視為清理問題已消失。原始計數與檔案位置已保留於本次月誌。

   - 重跑三平台型別、Ruff／Bandit、檔案／函式／複雜度及文件計數，檢查新增 lint 問題；
     AutoControl 全套 Pylint 仍有既有問題，不能把局部模組通過當全套零問題。
     WebRunner 既有全套 mypy／flake8／嚴格 Sphinx 債務見其 `Progress.md` #23，不能標示全綠。
   - 完成最終 wheel／隔離安裝／依賴一致性、嚴格文件建置，以及三語 README、Sphinx、架構、
     範例與公開契約一致性核對；避免舊說明把已支援的 browser profile 說成不支援。
     初次隔離安裝驗證留下的自有暫存目錄
     `C:\Users\USER\AppData\Local\Temp\autocontrol-wheel-stage72-mbpvem9h` 尚未清理；
     刪除操作遭自動審核拒絕（僅回覆 `blocked by policy`），保持原樣，不改用其他工具繞過。
   - 功能分支到正式環境的整合／部署仍未執行；正式工作樹與既有批次須保持可回復。

**仍暫緩的驗收**：原生桌面、實際瀏覽器與 Android／iOS 真機驗收；WebRunner `Progress.md` #20
的原生雙向 bridge 驗收，以及 #21 的完整 24 小時驗收。只有使用者明確恢復後才可啟動，24 小時
驗收須用新的 attempt 目錄與固定來源，短測／中斷紀錄不能代替完整結果。
**範圍限制**：不新增付費依賴及收費功能；保持瀏覽器統一走 `je_web_runner`。
**安裝前比對（使用者 2026-10-26 指示）**：任何安裝／升級前，先核對本紀錄與當前工作樹／
環境，並比對已安裝版本、依賴、來源及待安裝內容；把差異與預期變更寫入紀錄後再處理安裝。
本專案封裝還須比對來源提交、wheel／sdist 內容與檔案雜湊；安裝後再核實實際來源及依賴一致性。
這項要求不授權變更共用環境、付費依賴或正式部署；本輪僅在全新自有 C 暫存目錄
隔離安裝已逐項比對的套件。正式工作樹、共用環境、服務與瀏覽器均未變更。
本輪執行全程背景，不切換前景、不移動使用者滑鼠或注入桌面輸入。Tripo 使用專用持久登入設定檔、
螢幕外瀏覽器及 DOM 操作；AutoControlGUI 僅作必要唯讀觀測。登入狀態與 DOM 結果須分別驗證。

## 跨平台與 GUI 全面改版

`TODO` — 重設 UI、重寫並優化 GUI、修正 Wayland 與函式庫問題、跨機器同步、
深化全套 mypy、補齊 iOS／Android、自愈定位器量測、動作日誌 codegen、
完整範例與文件。涉及 `gui/`、`linux_wayland/`、`android/`、`ios/`、
`utils/{config_sync,remote_desktop,mcp_server,self_healing,codegen,executor}/` 與型別／文件驗證。
核准設計：[跨平台自動化與 GUI 改版](docs/superpowers/specs/2026-10-02-platform-gui-modernization-design.md)。
實作計畫：[分階段交付計畫](docs/superpowers/plans/2026-10-02-modernization-index.md)，待審閱。
現有 `[Answer]` 決策沿用。

`TODO` — 真機與付費 API 驗收暫緩，待明確恢復後執行；其餘目前缺環境的實驗先略過，相關項目保留未驗證。

`WIP` — 改版仍缺以下內容；原生平台與正式環境驗收缺口另列於後。
計畫 D1 仍缺 portal session 關閉／恢復、compositor 重啟的狀態與原生驗收、
擷取結果與擁有者 context 的接合，以及原生 session 的重試／取消／停止控制。
D2 仍缺原生半開交握資源回收與合成器釋放證據；D3 的錄製／全域停止／Windows 原生崩潰證據仍缺，詳見計畫與下方生命週期待辦。
計畫 E 已有裝置 context、輸入／畫面、應用生命週期與共用命令入口；
仍缺真實 SDK 契約核對、iOS 擴充 adapter 與裝置驗收，不能以 fake backend 測試結案。
H 已有三平台型別 gate 與真實相依型別檢查；仍缺嚴格型別深化、完整範例／文件及最終固定來源總驗收。
F 還缺：

- **F2 GUI 重製（`WIP`，維護者 2026-11-14 決定：全面視覺改版；窄視窗時導覽與詳情改為浮層）**：
  設計系統、視窗斷點（U-20261114-02）與 51 個分頁的版面重排（U-20261114-04）已交付，`WIDE_PAGES` 已清空。仍缺：
  - 已在本機真實桌面（Windows 11、單一螢幕 1920×1080、150% 縮放）審閱（U-20261114-05）；混合 DPI／多螢幕與 Linux／macOS 字型仍只有 offscreen 截圖。
- **F3** 還缺 backend timeout／cancel 傳遞與關閉生命週期遷移（Quick Connect 與 Viewer 分頁的啟停／中斷連線已移出 GUI 執行緒，
  U-20261114-32；傳送中的檔案傳輸會在下一個區塊停止，U-20261114-33；同頁 session generation 已隔離，U-20261114-34）。分頁的背景工作已全部改走共用 `TaskController`
  （`TabTask`，U-20261114-13～26），GUI 內除兩個 controller 本身外已無 `start_worker` 呼叫。
- **F3 關閉失敗恢復**：`gui/_slow_op.py` 的 StopQueue／stop_each 目前只記錄停止失敗，
  尚未保留失敗資源的明確重試所有權。須接上應用程式生命週期的資源保管、原授權下的 Diagnostics 查詢／重試，
  並遷移一般停止及頁面銷毀後的 discard 路徑，包含 `_drop_offer` 與廣播清理；不能把背景排程等同原生資源已釋放。
  GUI 廣播／錄影呼叫端仍須保留 `MediaRetirementError.owner` 和取消訊號附帶的清理擁有者；
  不可吞掉未確認結果、清掉失敗子物件或只因 `has_output` 就顯示已儲存。`HostBrowser` 對話框的持續所有權與背景清理仍缺整合。
  仍缺授權撤銷後可安全執行、只封閉本機准入且不等待原生鎖的獨立操作；不能用完整 stop 代替。
  媒體狀態查詢可能等候原生清理所持的鎖，Diagnostics 須讀取保管者快照，不能在 GUI 執行緒同步查詢。
  傳送器已進入無法中斷的後端呼叫時仍可能持續待停止；
  強制中斷、行程結束及原生資源回收尚未驗收。媒體清理缺口已用假資源重現，未執行原生／裝置／網路驗收。
- **F4** 啟動／記憶體基準對照與功能對等測試已交付（U-20261114-30）；仍缺 mixed-DPI 驗收（需要第二台不同縮放的螢幕）。
- **F3 Windows 原生釋放驗收**（`BLOCKED`：等 CI 再次發生）：`test/unit_test/headless/test_remote_desktop_host_id.py` 的 freed-thread-state abort
  尚缺 Windows 原生堆疊與獨立根因確認。CI 的 Windows 工作現在會把 `python.exe` 當掉時的 minidump 存進
  `native-<os>-<python>` artifact 的 `dumps/`（U-20261114-31）；本機 Python 3.14.7 連跑二十次未重現，
  最近的 Windows 3.11／3.14 CI 也未再出現。下次 CI 發生時以該 dump 判讀根因。

**只記未完成的事。** 完成的工作記在 [docs/updates/](docs/updates/README.md)（每月一個批次檔，
索引與查詢指令在它的 README），相容性變更寫進 [CHANGELOG.md](CHANGELOG.md)；完成的項目
從本檔移除，同一個 commit 在 `docs/updates/` 補一筆 `#done` 條目，不在這裡累積歷史。

狀態標記：

| 標記 | 意思 |
| --- | --- |
| `TODO` | 已決定要做，尚未開始 |
| `WIP` | 進行中，工作樹已有部分成果 |
| `BLOCKED` | 卡在外部條件（硬體、第三方、上游套件） |
| `DECIDE` | 需要維護者拍板才能往下走 |

---


## 一般開發規劃與相依問題

實機驗收新增項目請放在上方驗收區；下列規劃中的驗證條件尚不代表功能已交付。

## 下一步擴充：以記憶體觀察支援 UI、作業系統與應用程式背景操控

`TODO / 規劃` — 2026-11-01 使用者要求。此節只制定擴充順序，尚未實作或完成驗收；
不解除下列既有原生／真機／24 小時驗收暫緩，也不啟動服務、改動正式環境或讀取現有應用程式記憶體。

### 目標與可交付範圍

讓 agent 能取得指定程式的內部狀態，結合 UI、OS 與應用程式介面完成
「觀察 → 判斷 → 背景操作 → 獨立讀回」的完整任務。先以 Windows 為第一個實作平台，
逐一擴充應用與操作覆蓋；「整個電腦」是覆蓋目標，不能宣稱任意程式都能靠讀記憶體直接操控。
讀取位元組不會執行操作，也不會自動產生按鈕、文件、工作流程等語意；每種程式仍需已知資料格式或正式介面。

將三種資料來源明確分開：OS 公開查詢取得程序／視窗／服務資訊；UIA、DOM、應用程式 API
取得語意狀態；跨行程記憶體讀取補足前兩者沒有提供的特定欄位。現有
`utils/agent_memory/agent_memory.py` 是 SQLite 任務經驗記憶，不是行程記憶體讀取器。

全程背景是硬條件：不切換前景、不移動使用者滑鼠、不注入桌面鍵盤／滑鼠事件；
UIA 僅作必要唯讀觀測，不以 Invoke、SetValue、選單或焦點切換代替背景操作。
瀏覽器沿用 WebRunner 的專用持久登入設定檔、螢幕外瀏覽器與 DOM 操作。
沒有符合條件的命令介面時回報不支援，保留缺口；不自動退回桌面輸入。

### 現有架構與擴充位置

下表的程式路徑均相對於 `je_auto_control/`；新模組名稱為提案，尚不存在。

| 責任 | 現況／預計接點 | 擴充內容 |
| --- | --- | --- |
| 任務與資源所有權 | `utils/agent_runtime/target_config.py`、`target_factory.py`、`native_target.py` | 沿用 profile、工具範圍、helper 與取消生命週期；新增受管觀察／背景操作能力，不另建繞過 policy 的總控入口。 |
| UI 觀察 | `utils/agent_runtime/targets.py`、`utils/accessibility/` | 現有 DesktopTarget 以指定前景應用為範圍；新增明確 PID／視窗身分的唯讀觀察，不直接放寬現有前景輸入檢查。 |
| 瀏覽器 | `utils/agent_runtime/browser_target.py`、`browser_commands.py` | 沿用受管 WebRunner session、來源限制與 DOM 驗證，不以掃描瀏覽器記憶體取代。 |
| 記憶體觀察 | 新增 `utils/process_memory/` | 擁有唯讀行程 handle、區段查詢、受限讀取與版本化解碼；原始位址及 bytes 不流入 agent 公開工具。 |
| OS／應用背景命令 | 在 `utils/agent_runtime/` 接入專用 adapter | 使用正式 API、受限 CLI、IPC／COM 等支援介面；每個動作列明資源範圍、背景副作用與完成條件。 |
| 能力診斷 | `wrapper/capabilities.py` 與 runtime profile | 現有 capability 主要為 input／capture；擴充時保留「能力存在不等於已授權」語意，按平台／程式／操作分別回報。 |

執行資料流：既有 runtime 檢查任務與 profile → adapter 讀取受限狀態 → 產生有來源及版本的觀察
→ runtime 再驗目標與命令範圍 → 背景命令 → 重新取得完成證據。
記憶體 reader 只擁有讀取資源，既有 runtime 仍是任務、操作 journal 與取消的唯一擁有者。

### 呼叫方式與介面草圖

以下是待實作的契約草圖，不是現在可呼叫的 API。應用呼叫者只指定目標、欄位及目的；
位址、版本配置與 OS handle 留在 adapter 內部。

```python
view = await target.observe(StateQuery(fields=("document_id", "job_status")))
receipt = await target.perform(
    BackgroundCommand("export_document", document_id=view.fields["document_id"]),
    expected=view.ref,
)
proof = await target.verify(receipt, CompletionQuery("export_file_matches"))
```

另外兩個使用情境：OS adapter 讀取指定服務狀態後執行該服務支援的管理操作，並重新查詢；
browser adapter 從受管頁面取得欄位、透過 DOM 提交，再驗證新回應或產物。
兩者都不必知道記憶體位址，也不能只靠命令回傳成功判定完成。

- `TargetIdentity`：主機／登入 session、PID、程序建立時間、執行檔身分與架構；視窗／文件／瀏覽器
  context 另帶各自身分。PID 或 HWND 相同不能單獨證明還是同一目標。
- `ObservationRef`／`Observation`：目標、adapter 與 schema 版本、觀察序號、擷取起訖時間、
  來源、欄位、完整度／截斷及一致性結果。過期、部分讀取、未知與權限拒絕不能表示成空值或正常狀態。
- `MemoryProbe`：profile 中登記的 probe ID、版本化 schema、欄位清單、位元組／區段／時間上限；
  內部 `read(probe, identity, deadline, cancellation) -> ProbeResult`，沒有寫入或任意執行介面。
- `observe(query) -> Observation | ObservationFailure`：僅回傳有界、經欄位白名單篩選的語意資料。
  `perform(command, expected) -> Receipt | Refused | EffectUnknown`：操作前重驗身分與必要狀態；
  不能原子比較並執行的介面必須揭露競態，不能把舊快照當作鎖。
- `verify(receipt, query) -> Verified | NotSatisfied | Unknown`：以新讀取、服務回應或產物驗證；
  `EffectUnknown` 先查明結果，不盲目重送。reader 的觀察不授予任何操作權限。

### 實作順序與各階段完成條件

`WIP` — 內部 `utils/process_memory/` 已有不可變身分／probe、區段與位元組預算、
序號一致性檢查、語意欄位白名單及失敗 handle 保留重試。契約與 fixture 協定見
[process_memory_contract.md](docs/process_memory_contract.md)。M0／M1 尚未完成，
已有自有 fixture 的固定緩衝區與有界管線控制協定，測試僅驗證本機資料配置及背景子程序通訊。
bootstrap 的 PID、位址、來源雜湊與 launch nonce 都是未驗證自報資訊，不能充當 OS 出生身分或可信 resolver。
typed Windows provider 已有有界查詢／讀取、原生身分事實與保留 handle 的注入測試；
應用身分仍須由明確受審的 attestor 提供，沒有預設信任或由期望身分反填的實作。
仍缺實際載入映像與啟動關係綁定、受審 runtime／固定程式碼交付、可信 executable／version attestor、
ASLR resolver、fixture 的原生身分核對與頁面故障注入、runtime grant／helper
生命週期及公開入口；M2 也仍缺實際應用版本 adapter。原生驗收固定列於本檔上方。

1. **M0：能力盤點與範圍契約。** 先列 Windows 的 UI／OS／應用操作矩陣，每項記錄
   讀取來源、執行介面、權限、是否全背景、支援版本、驗證方式與不支援原因。
   第一個目標採自有 fixture 程序，之後選一個提供正式背景介面的應用；不能先承諾任意軟體。
   完成條件：profile、上述結果型別及禁用桌面輸入的路由規則具體可審閱，既有桌面路徑不被暗中改寫。
2. **M1：Windows 唯讀記憶體 reader。** 實作明確型別的原生呼叫、handle 所有權、
   `VirtualQueryEx` 區段檢查及 `ReadProcessMemory` 有界讀取；僅取得必要的查詢／讀取權限。
   限定已選程序和已知欄位，不做全機掃描或任意位址的 MCP 工具。處理 32／64 位架構、ASLR、
   guard／不可讀頁、短讀、讀取期間程序退出或區段變更；未知架構／版本回報不支援。
   完成條件：fixture 公布的已知 buffer 能精確讀回；非法範圍、PID 重用、權限拒絕、逾時／取消
   都有可區分結果，handle 與 helper 可確認回收。原生 fixture 驗收仍受既有暫緩約束。
3. **M2：版本化語意解碼。** 每個 probe 綁定程式版本／模組識別與資料結構，不保存跨重啟絕對位址。
   用目標提供的序號／快照協定驗一致性；無此機制時只能標示 best-effort，重複讀到同值不代表原子快照。
   把 probe、UIA 唯讀及 DOM 結果整理為上述 Observation，保留來源衝突與部分缺失。
   完成條件：版本變更、錯誤長度／指標、混合世代及未知欄位被拒絕；解碼器不能把錯誤 bytes 當成成功狀態。
4. **M3：接入受管 runtime 與診斷。** 將讀取能力接到 profile、helper、取消、稽核與既有工具註冊；
   先在已支援 target 下附加 reader，只有不同資源所有權確實需要時才新增 target kind。
   每次讀取有上限，原始記憶體不寫入 AgentMemory、一般日誌或模型上下文；只輸出允許的語意欄位。
   完成條件：撤權、過期觀察、目標重啟、helper 崩潰、並行 session 不串資料；所有公開入口使用相同契約，
   關閉功能後既有任務仍可運作。
5. **M4：UI／OS／應用背景操作。** UI 先完成必要唯讀結構／欄位觀察；網頁操作用既有 DOM。
   OS 從指定程序／檔案／服務的正式管理介面開始；應用從讀文件、設定指定欄位、儲存／匯出等
   可確認全背景的 API／IPC 操作開始。各動作沿用 runtime policy，不透過任意 shell 或記憶體寫入繞過。
   完成條件：每類各有一條「讀狀態 → 操作 → 獨立驗證」流程，重試不重複副作用；
   即使 API 呼叫成功，仍須另驗未改變使用者前景／焦點／滑鼠及未注入桌面輸入。
   不符背景條件的操作維持不支援，不能只因名稱叫 API／COM 就列為已支援。
6. **M5：跨應用任務閉環。** 接回既有四條工作流程：查詢／下載／歸檔、CSV／Excel 填表、
   跨應用欄位轉移、工作區準備。先完成來源讀取、轉換、目的地操作、產物比對的窄流程；
   工作區準備中會搶前景或排列使用者視窗的部分維持停用。
   完成條件：目標在觀察後被使用者修改、未知對話框、取消發生於提交期間、回覆遺失與重啟，
   均能保留已完成效果並明確區分失敗／待確認；任務結束與背景不干擾各有證據。
7. **M6：擴充平台與交付。** Windows 的垂直流程通過後，再盤點 macOS／Linux 的合法讀取來源、
   權限與應用介面，按能力回報 supported／unsupported／unverified；不把 Windows 的實作當成跨平台保證。
   完成支援矩陣、操作文件、資源限額與長時間 handle／記憶體成長觀測、停用及版本回復方案；
   真機／24 小時驗收解除暫緩前，這些欄位保持未驗證。

**第一個可交付增量：M0 契約＋M1 reader 與自有 fixture 的驗證設計。**
先完成 headless 解碼／政策測試與原生驗收腳本，原生執行另依既有暫緩安排；
不先整合所有應用、不更動正式服務。速度與記憶體預算先量測再訂門檻，不能預填改善比例。

### 驗收矩陣與已知邊界

| 面向 | 必須保留的證據 |
| --- | --- |
| 正確性 | 自有 fixture 的期望值、實際讀回、版本及身分；過期／部分讀取明確失敗；實際效果另有讀回。 |
| 全背景 | 實際 DOM／API 完成證據，另列前景視窗／焦點／滑鼠／輸入事件觀測；前後座標相同不足以排除期間干擾。 |
| 故障與生命週期 | 退出、重啟、撤權、取消、區段變更、逾時與 helper 崩潰；關閉完成須驗資源退場，未知狀態不重送操作。 |
| 資料範圍 | 只解碼 profile 指定欄位；不擷取密碼、登入 token 或跨應用資料；錯誤與紀錄不得帶出 raw bytes。 |
| 覆蓋 | 每個 OS／程式版本／操作獨立記錄已實作、已測、尚未驗收及不支援；不可由一個 fixture 推論整台電腦。 |

讀取受 OS 權限與程序保護限制；不把需要管理權限當成預設提升理由，也不納入核心驅動、
任意記憶體寫入、DLL 注入或繞過保護的通用控制方案。UI 語意缺失、程式私有結構改版及純影像介面
都可能留下覆蓋缺口；需增加正式應用 adapter 或維持不支援。

設計取捨：比較「記憶體 reader 統一解碼所有程式」與「受管語意 adapter 搭配限定記憶體 probe」。
採後者，讓呼叫者不必了解指標、版本及原生 handle，並沿用既有操作所有權；採納前者的
嚴格身分、版本化解碼與資源限額。接受逐程式接合成本，換取可驗證的背景行為與失敗邊界。
不另建全機狀態資料庫、第二套任務排程器或通用 UIA 操作入口。實作若改變上述結果契約，
須同步更新此節，不以新行為反推原規劃已完成。

本次規劃核對：兩個候選均收斂到限定 reader 與獨立背景操作；另經獨立交叉審閱，未發現需修正的重大問題。
文件差異檢查通過，原有進度段落保留；此結果只驗證規劃文件，不代表功能或原生驗收通過。

技術依據（2026-11-01 核對）：Microsoft 的
[ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory)、
[VirtualQueryEx](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualqueryex)
與 [Process Security and Access Rights](https://learn.microsoft.com/en-us/windows/win32/procthread/process-security-and-access-rights)
分別定義讀取、區段查詢及程序權限；
[UI Automation Control Patterns](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview)
說明 UI 語意介面。這些 API 的存在不代表目標程式已支援、已授權或已通過本專案背景驗收。

---

## 750 行上限的既有豁免清單

`CLAUDE.md` §Size and complexity limits 規定:超標檔案只能列在這裡,列不進來的就是缺陷。
清單上的檔案**可以改、可以變短,但不得再變長**——要再長就得先拆。
行數以 `len(text.splitlines())` 量測；檔案縮短時，上限跟著往下走。
**這張表現在有測試在守**：`test/unit_test/headless/test_file_length_budget.py` 比對本表與樹，
超標未列、列上的檔案變長、或已經縮到線內卻還留著的列，都會紅。

| 檔案 | 行數 | 為何還沒拆 |
| --- | ---: | --- |

**本質豁免（flat data tables）**：`utils/mcp_server/tools/_factories.py`、
`utils/executor/action_executor.py`、`gui/script_builder/command_schema.py`、
`je_auto_control/__init__.py`、`je_auto_control/_export_bindings.py`（產生的公開名稱來源查表）與
`gui/language_wrapper/{english,japanese,traditional_chinese,simplified_chinese}.py` 語系字串表。

## Windows arm64:裝得起來了，但少了影像與加密

`TODO` — 上游仍未發 wheel（`opencv-python`、`cryptography`），但安裝本身不再是卡點

### 還沒有答案的：Windows arm64 上這些功能不能用

裝得起來不等於功能齊。該平台上以下四組會拋帶提示的錯誤，而不是默默失效：

| 功能 | 缺的是 | 錯誤形式 |
| --- | --- | --- |
| 影像比對、截圖轉 BGR、螢幕錄影 | `opencv-python`／`je_open_cv` | `utils/cv2_utils/optional.py` 的 `require_cv2()`／`require_je_open_cv()` 拋 `RuntimeError` |
| 動作檔加密與 Ed25519 簽章（`action_signing`） | `cryptography` | 拋 `CryptographyUnavailableError`（也是 `RuntimeError`；HMAC 簽章不受影響） |
| 秘密金庫（`${secrets.NAME}`） | `cryptography` | 同上 |
| ACME／TLS 發證、加密錄影 | `cryptography` | 模組層 `ImportError` 轉述（照 `webrtc_transport` 慣例） |

`BLOCKED`（2026-11-12 以下方指令重驗，三者仍無 win_arm64 wheel；cryptography 仍只到 46.0.3）— 仍需相容的上游 wheel：`opencv-python>=4.8,<6`、
`cryptography>=50.0.0` 與 `aiortc` 的傳遞相依 `google-crc32c`。
不能為相容性降低 cryptography 安全下限。上游提供相容版本後，需重驗安裝與功能，
再移除 `pyproject.toml` 中相應平台標記並同步更新
`test/unit_test/headless/test_arm64_dependency_markers.py`。

重驗指令（不需要 arm64 機器，也不需要 runner）：

```bash
pip install --dry-run --only-binary=:all: --platform win_arm64 --python-version 3.12 --target /tmp/probe 'opencv-python>=4.8,<6' 'cryptography>=50.0.0'
```

重驗通過後，需調整相應環境標記與 `test_arm64_dependency_markers.py`，保留安全下限。

注意一個驗證上的陷阱：**`pip --platform` 不會換掉 marker 的評估環境**，
它只影響 wheel 相容性標籤，所以拿本機做 `--dry-run` **驗不到標記的效果**（兩個
套件依舊會被要求）。能驗的是兩件事：直接評估 marker（上面那支測試在做的），
以及 `windows-11-arm` 那一格自己綠。
