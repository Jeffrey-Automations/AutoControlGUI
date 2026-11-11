# Installation and configuration

[README](../../../README/README_zh-TW.md) · [Documentation](../../README.md)

## 安裝

```bash
pip install je_auto_control            # 核心
pip install je_auto_control[gui]       # 加上 PySide6 桌面應用程式
```

需要時才安裝的選用套件：

| Extra | 啟用的功能 |
|---|---|
| `gui` | PySide6 桌面應用程式（51 個分頁）：左側可搜尋的導覽面板（`Ctrl+K`）依分類列出全部功能，分頁在第一次開啟時才建立，**View → Theme** 切換深色／淺色。窄視窗的內容可捲動；關閉視窗時，主題、字級、導覽面板顯示（`Ctrl+B`）與寬度會存入 `~/.je_auto_control/gui.ini`。主題直接使用 Qt，不需要 `qt-material`。 |
| `webrtc` | WebRTC 遠端桌面、USB 直通（`aiortc`、`av`） |
| `signaling` | 獨立的訊令／rendezvous 伺服器（`fastapi`、`uvicorn`） |
| `discovery` | mDNS / Zeroconf 區網主機探索 |
| `pdf` / `office` | PDF 與 Excel／Word／PowerPoint 讀取 |
| `fuzzy` / `locale` | `rapidfuzz` 模糊比對、`babel` 地區解析 |
| `s3` / `audio` | S3 產出物儲存、系統音量控制 |

以分頁關閉鈕關閉 factory 建立的功能面板時，下一次 Qt event loop 會釋放 widget、訂閱與計時器；重新開啟會建立新面板。**View → Tabs** 與嵌入用的 `hide_tab` 只隱藏並保留狀態。`tab_registry.open/close` 與 `close_tab` 提供明確的生命週期介面。核心分頁與 Remote Desktop 也會在關閉時釋放。共用 registry 的 TCP／WebSocket 連線仍可供腳本使用；頁面擁有的 WebRTC 連線在背景停止。重開會建立新控制項，不自動接回既有連線；待處理核准與晚到頁面回呼會被拒絕。嵌入者直接提供的 widget 維持其既有所有權契約。

**Windows arm64** 裝得起來也跑得起來，少的是上游在那裡發不出來的那些：
`opencv-python` 與 `cryptography` 都沒發 `win_arm64` wheel。所以 `find_image*`、
`screenshot()`（OpenCV／BGR 那一支——Pillow 截圖仍可用）、秘密金庫、動作檔加密、
ACME／TLS 與加密錄影會拋出指名缺哪個 wheel 的錯誤，而不是難以追查的失敗。
滑鼠、鍵盤、螢幕尺寸、視窗管理、無障礙樹、動作執行器、MCP／REST／TCP 伺服器
與 GUI 都正常——這是實測的，不是推論的。其他平台不受影響。

**系統需求：** Python ≥ 3.11。
Linux 請先安裝建置前置套件：

```bash
sudo apt-get install cmake libssl-dev
```

OCR、VLM 與 LLM 後端（`pytesseract`、`easyocr`、`paddleocr`、`anthropic`、`openai`）
都是按需載入——只裝你實際會用到的。Tesseract 的部分，`find_tesseract_cmd()` 找出執行檔
（依序是 `$TESSERACT_CMD`、`PATH`、安裝程式的預設資料夾），`set_tessdata_dir()` 把它指到
語言資料夾，`ocr_status()`／`ocr_languages()` 在第一次 OCR 之前就說出缺了什麼。

**記錄檔：** 函式庫寫到 `~/.je_auto_control/logs/AutoControlGUI.log`，第一筆記錄時
才建立（只 import 不會寫任何檔），同一個帳號的所有行程共用（附加寫入、每行帶行程 ID，
超過 10 MB 就改名成 `.1`）。要寫到別處就設定
`JE_AUTOCONTROL_LOG_FILE`，設成 `os.devnull` 則不寫檔。

---

## 平台支援

| 平台 | 後端 | 輸入 | 螢幕擷取 | 錄製 | 視窗管理 |
|---|---|:---:|:---:|:---:|:---:|
| Windows 10 / 11 | Win32 ctypes（可選 Interception 驅動） | ✅ | ✅ | ✅ | ✅ |
| macOS 10.15+ | pyobjc / Quartz | ✅ | ✅ | ✅¹ | ✅ |
| Linux X11 | python-Xlib（可選 `uinput`） | ✅ | ✅ | ✅ | ✅ |
| Linux Wayland | 經桌面 portal 的 libei，或 ydotool／wtype ＋ 擷取工具 | ✅ | ✅ | ❌ | ❌ |
| FreeBSD／OpenBSD／NetBSD | python-Xlib，與 Linux 同一套 X11 後端 | ✅² | ⚠️² | ✅² | ✅² |
| Android | adb + uiautomator2 | ✅ | ✅ | — | — |
| iOS | WebDriverAgent / facebook-wda | ✅ | ✅ | — | — |

¹ macOS 的錄製走 Quartz event tap，需要**輔助使用**權限
（系統設定 → 隱私權與安全性 → 輔助使用）。沒有授權時會直接拋出並指名
缺的是哪個權限，而不是安靜地錄到一個空的 session。

² BSD 直接跑同一套 X11 後端——同一個 X server、同一個 `python-Xlib`，而輸入、
錄製與視窗管理就只相依這一個套件。`freebsd` CI job 在真的 FreeBSD 14 上驅動真的
輸入，再從 X server 讀回來；OpenBSD 與 NetBSD 走同一條程式路徑，只是沒有 CI
runner。唯一的例外是螢幕擷取，而卡的是打包不是平台：它走 Pillow／mss 與 OpenCV，
而 `opencv-python`、`pillow`、`cryptography` 都沒有發 FreeBSD wheel。從 ports
建起來之後，擷取、影像比對、OCR 與動作加密也都能用——`import je_auto_control`
本身已經不需要它們任何一個。

Wayland 的按鍵、按鈕與指標輸入在 `auto` 模式下，僅於選用原生後端缺席時改用 CLI。
portal 請求開始後，拒絕、逾時、握手失敗、裝置暫停或權限撤銷都會停止輸入，
不會自動切換提供者；重複呼叫保留不含原生資源的失敗狀態，不重開同意對話框。
`JE_AUTOCONTROL_WAYLAND_INPUT_BACKEND=libei` 強制原生輸入，`=cli` 明確選擇 CLI。
解決權限問題後，可明確呼叫 `je_auto_control.linux_wayland.libei.reset_default_backend()`
以允許重新請求。原生組合鍵中斷時會在同一後端嘗試釋放所有已按下的按鍵，並保留原始取消。
此行為不改變明確的 wtype 文字輸入路徑或螢幕擷取選擇。

`ydotool` 退路需要
**ydotool 1.0 以上**。AutoControl 送的每一個參數都是那一版才有的；0.1.x
（Debian bookworm 與目前所有 Ubuntu 仍以這個名字提供，Debian trixie 則根本沒有）
對同一批參數回傳 0 卻不送出任何事件。AutoControl 會偵測並直接拒絕，
而不是為根本沒送出的輸入回報成功。Arch、Fedora 與 Debian unstable 提供的是 1.0。

這條退路要能**準確定位**，還有一個前提:合成器的指標加速度必須是關的。
`ydotool mousemove --absolute` 並不送任何絕對事件——它先把游標推到合成器夾取的
那個角落，再送相對位移，所以這段位移會被合成器加速。對真的 wlroots session 量到的是:
libinput 的預設 profile 讓游標走的距離正好是要求的兩倍。ydotool 自己的 `--help`
也是這樣寫的；AutoControl 每個行程會記一次警告，而不是安靜地把點擊放到錯的地方。
請對 ydotoold 的裝置關掉加速度（sway:`input type:pointer accel_profile flat`
加上 `pointer_accel 0`），或是裝上 `liboeffis`，改走協定層本來就是絕對座標的 libei。

倍率是合成器自己的設定，用戶端讀不回來，所以只有你知道它關了沒有：
`JE_AUTOCONTROL_WAYLAND_POINTER_ACCEL=flat` 表示已經關掉，移動就不再出聲；
`=strict` 則寧可拒絕這次移動，也不讓點擊落在別的地方；不設定就維持
「警告一次後照樣移動」的預設。

Wayland 的螢幕擷取需要合成器對應的工具，因為沒有單一工具能涵蓋全部：wlroots 系
（sway、Hyprland、river）用 `grim`，GNOME 用 `gnome-screenshot`，KDE 用 `spectacle`。
裝好其中一個之後，所有擷取路徑——截圖、影像與錨點定位、OCR、螢幕錄影、遠端桌面——都會
經由它。三個都沒裝時，內建 D-Bus client 會透過 session bus 嘗試 `xdg-desktop-portal`，第一次可能會跳
同意對話框。再不行，擷取會帶著安裝提示明確失敗，而不是回傳空白的 XWayland root；
`je_auto_control.api.run_diagnostics()`（以及 GUI 的 Diagnostics 分頁）的 `screen_capture`
檢查會回報目前使用哪一層。

原生 Wayland 指標座標在原始座標與版面原點換算後仍不屬於任何授權 EIS 區域時，
會以 `state="failed"` 的 `LibeiUnavailable` 拒絕，停止自動 CLI 備援，
不送出移動、frame 或後續點擊。有效座標、未提供區域的裝置、同一 sender 的後續有效請求，
以及明確選擇 CLI 的既有行為維持不變。

**輸入／擷取能力**提供 `je_auto_control.api`（亦由套件根目錄匯出）的
`BackendContext`、`CapabilityStatus`、`CapabilitySnapshot` 與 `probe_capabilities`。
呼叫 `probe_capabilities(BackendContext.current()).to_dict()`、無參數的
`AC_probe_capabilities`／唯讀 `ac_probe_capabilities`，或選擇
**Diagnostics → Actions → 檢視輸入與擷取能力**；Builder 提供相同無參數指令。
`python -m examples.capabilities` 顯示本機前置條件與確定性的 XWayland 範圍範例，不操作桌面。

輸入項描述按鍵／指標事件；既有 wtype 文字路徑獨立。探測只讀環境、PATH 與不等待鎖的既有原生狀態，
不載入選用原生函式庫、不連線、不讀取事件、不擷取或要求授權。找到工具或 bus 位址只代表
`unverified`，不等於可用。快取 libei 須完成握手，且鍵盤、絕對指標、按鈕與滾輪事件種類都在運作才回報可用；
部分授權維持未驗證，事件種類暫停或必要裝置移除則回報暫停／撤銷。八種狀態為 `available`、`unverified`、`needs_permission`、
`needs_dependency`、`unsupported`、`paused`、`revoked`、`failed`。
`available` 僅是最近的本機觀測，可能過時；實際操作仍重驗權限。XWayland 一律
`desktop_wide=False`，無法涵蓋原生 Wayland 視窗；其他範圍旗標仍受授權區域限制，不代表已驗證每個螢幕。

Context 會複製環境／工具資料，可由擁有者提供無原生物件的輸入／擷取觀測，但不授予權限。
預設本機結果不含環境值、命令參數、執行檔路徑或原生錯誤文字；AC／MCP 不接受外部提供觀測。
明確選擇 CLI 與觀測到選用原生依賴缺失後的自動備援分開；拒絕、暫停、撤銷與失敗不表示改走 CLI。
擷取工具／portal 選擇獨立診斷，重繪與切換語系只使用既有快照。原生 portal 恢復、compositor 重啟、
擷取結果與 context 的接合，以及原生 session 的重試／取消／停止控制仍列於 `Progress.md`。

GUI 工作基礎提供 `gui.task_controller.TaskController`：
`submit(work, owner=widget)` 回傳呼叫者持有的 `TaskHandle`，透過
`TaskOutcome`／`TaskProgress` 傳遞終態與進度。工作取得不依賴 Qt 的
`CancellationToken`，提供 checkpoint、有界且可被取消喚醒的等待與進度回報。
提交時捕捉 context，執行前重讀 store 使用者；工作須持有資料、不引用 widget，並驗證自身操作所需的 capability。
既有 `DeferredAuthorization.scope()` 維持輸入權限要求，`context_scope()` 僅更新與綁定身分。

擁有者、handle 或 controller 銷毀時會要求協作式停止並丟棄延遲結果；每項工作有獨立 ID／token，
回呼在 GUI 執行緒執行。不強制中斷不合作的呼叫，也不把已成功提交的結果改標為取消。
錯誤與進度使用捕捉的秘密遮罩 scope，終態不保留例外 traceback；執行緒啟動失敗會回復兩層登記並保留原失敗。
Diagnostics 已接入此共用控制器；其餘面板／backend 遷移與原生 session 操作仍列於 `Progress.md`。

主動 **Diagnostics → Actions → 執行診斷** 以共用控制器在 GUI 執行緒外執行。
**停止診斷** 要求協作式停止；四語狀態區分執行中、清理中、已取消與失敗，並顯示已完成檢查數。
重複執行不另開工作，關閉後丟棄延遲進度／結果，明確重試會建立新的擁有者工作。
GUI 以不保留例外 traceback 的 typed outcome 呈現取消；核心／SDK／CLI 與 MCP handler
維持原始直接／包裝取消物件。普通檢查錯誤仍列入報告並繼續其餘項目。

兩個 SDK namespace 匯出 `CancellationToken`、`TaskProgress`、`cancellation_scope`。
使用 `with cancellation_scope(token): report = run_diagnostics()`，擁有者可由另一執行緒呼叫
`token.cancel()`；既有無參數診斷簽章不變。Scope 不授予權限，`cancellation_scope(None)`
只在有時限的自有資源清理期間暫停取消。`AC_diagnose` 與新增的唯讀 `ac_diagnose` 共用報告；
MCP 不接受參數，使用請求取消／進度，與明確 GUI 操作同樣需要 `read_screen`，拒絕外部 token／授權資料。
這些是主動檢查，擷取可能要求同意；`ac_probe_capabilities` 維持獨立的被動選項。

Scoped Wayland D-Bus 的連線／讀取／部分寫入，以至多 0.1 秒的區間輪詢，維持原本總時限。
取消時在原 bus 以獨立 0.25 秒預算嘗試 Request.Close，再釋放連線；取消的已回傳圖片會刪除。
Scoped CLI 擷取會停止並回收自己建立的 helper／process group，清理有時限，pipe close 失敗也不蓋掉原取消，
已回收的數字 PID 不再作為訊號目標。liboeffis 取得 session 時會觀察停止並釋放自身 context。
不強制中斷不合作或原生呼叫，清理期間 GUI 仍可操作；restore／重啟、原生 session 控制、
擷取擁有者 metadata 與其餘面板／backend 遷移保留於 `Progress.md`。

`python -m examples.cancellable_diagnostics` 預設只做受控取消示範，不呼叫 provider。
`--active --cancel-after 2` 才明確執行診斷並在兩秒後要求停止；真機／裝置／API 驗收另外列管。

開啟 Diagnostics 只顯示已翻譯的「尚未執行」狀態，不執行檢查。
選擇 **Actions → 執行診斷** 才會啟動既有主動檢查，可能擷取螢幕或需要 portal 同意；
切換語系不啟動檢查。明確的 `run_diagnostics`、`AC_diagnose` 與 MCP 診斷呼叫維持主動行為；
無副作用的能力檢視使用下方獨立操作。

未完成的 screenshot portal 請求會在斷開原始 bus 前嘗試 `Request.Close`，
使用獨立的 0.25 秒 D-Bus I/O 預算。伺服器回傳替代 handle 時會跟隨該 handle；
方法回覆不確定時則使用預測 handle，已完成的 Response 不重複關閉。
一般清理錯誤不覆蓋主要擷取失敗；原始取消與強制中斷物件會穿過包裝及清理繼續傳播。
D-Bus 寫入與回覆共用呼叫預算，連線建立有明確時限，connect／驗證／Hello 中斷時，
即使 `__enter__` 失敗也會釋放自己擁有的描述元。實際合成器／對話框取消仍待平台驗收。

有一件只在 Wayland 出現、需要事先規劃的事：**擷取回來的圖裡可能有滑鼠游標。**
這裡沒有任何一條擷取要求游標，但只要 backend 沒有游標平面（包含任何以
`WLR_NO_HARDWARE_CURSORS=1` 執行的 session），wlroots 就會畫**軟體游標**並把它
合成進輸出緩衝區，而擷取交回來的正是那一份。Windows 與 X11 都不含游標，所以
「定位器、樣板比對或 OCR 在目標中間看到一個游標形狀的洞」只會在這裡發生。
Wayland 不讓用戶端讀游標位置，所以沒有東西可以可靠地遮或閃避：請在擷取之前
把指標移離要拍的區域。`screen_capture` 檢查會以 `cursor_may_be_captured` 回報這件事。

如果以上都不適用你的環境，可以直接指定自己的指令——它優先於所有偵測，`{output}` 會被
換成暫存 PNG 路徑：

```bash
export JE_AUTOCONTROL_WAYLAND_CAPTURE_COMMAND="mycapture --png {output}"
```

Wayland 禁止非特權用戶端進行全域輸入錄製——若要錄製，請設定
`JE_AUTOCONTROL_LINUX_DISPLAY_SERVER=x11` 並在 X11 session 下執行。視窗管理支援
Windows、macOS（pyobjc）與 X11（含 XWayland）；純 Wayland session 的協定不讓用戶端看到別的程式的視窗，
所以 `list_windows()` 回傳空清單，其餘視窗操作一律拋出帶原因的 `AutoControlUnsupportedOperationException`。對於會忽略合成輸入的應用程式，
可選用驅動層後端（`JE_AUTOCONTROL_WIN32_BACKEND=interception`、
`JE_AUTOCONTROL_LINUX_BACKEND=uinput`、ViGEm 虛擬手把）；驅動未安裝時會自動退回原本行為。

---

## 設定

AutoControl 讀取的每一個環境變數。這裡沒有任何一項是必填的：完全不設定時，AutoControl 會自行選擇平台後端，伺服器只綁定 `127.0.0.1`，所有需要主動開啟的功能（簽章強制、RBAC、USB 直通、工具路徑限制）都是關閉的。[設定參考](https://autocontrol.readthedocs.io/en/latest/Zh/doc/configuration/configuration_doc.html)（[原始檔](../../source/Zh/doc/configuration/configuration_doc.rst)）列出完整的可接受值，並把每個變數連到說明該功能的頁面；CI 會拿它以及下面的表格和程式碼比對。

### 平台後端

| 變數 | 預設 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_WIN32_BACKEND` | `sendinput` | 設成 `interception` 時鍵盤與滑鼠改走 Interception 驅動程式；找不到驅動或 DLL 時會警告並退回 `SendInput`。 |
| `JE_AUTOCONTROL_LINUX_BACKEND` | `x11` | 設成 `uinput` 時直接寫入核心輸入事件；`/dev/uinput` 無法寫入時會警告並退回 XTest。 |
| `JE_AUTOCONTROL_LINUX_DISPLAY_SERVER` | `auto` | 決定載入哪一個 Linux 後端：`auto` 讀取 `XDG_SESSION_TYPE` 與 `WAYLAND_DISPLAY`；`wayland` 或 `x11` 則強制指定（在 Wayland 工作階段設成 `x11` 只能操作 XWayland 視窗）。 |

### Windows Interception 驅動程式

| 變數 | 預設 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_INTERCEPTION_DLL` | 未設定：先找 `PATH`，再找套件旁邊 | `interception.dll` 的完整路徑。 |
| `JE_AUTOCONTROL_INTERCEPTION_KEYBOARD` | `1` | 鍵盤事件要送往的 Interception 裝置編號（`1`–`10`）。 |
| `JE_AUTOCONTROL_INTERCEPTION_MOUSE` | `11` | 滑鼠事件要送往的 Interception 裝置編號（`11`–`20`）。 |

### Wayland

| 變數 | 預設 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_WAYLAND_INPUT_BACKEND` | `auto` | 設成 `cli` 時透過 `ydotool` 送出輸入，完全不向桌面 portal 提出要求。這是啟動前就做好的選擇：使用者拒絕授權後，AutoControl 不會自行切換過去。 |
| `JE_AUTOCONTROL_WAYLAND_POINTER_ACCEL` | `warn` | 只影響 `ydotool` 路徑的絕對移動（那其實是會被合成器加速的相對位移）：`warn` 警告一次後照樣移動，`flat` 表示加速已關閉、不再警告，`strict` 直接拒絕移動。 |
| `JE_AUTOCONTROL_WAYLAND_CAPTURE_COMMAND` | 未設定 | 自訂的截圖指令列，以 `{output}` 表示 PNG 的輸出路徑。優先於 `grim`、`gnome-screenshot`、`spectacle` 與 portal。 |
| `JE_AUTOCONTROL_WAYLAND_RECORD_DEVICES` | 未設定：一個都不讀 | `PhysicalRecorder` 可以讀取的 `/dev/input/event*` 裝置（以逗號分隔）；實體輸入錄製必須逐一指定裝置才會啟用。 |

### MCP 伺服器

| 變數 | 預設 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_MCP_READONLY` | 未設定 | 設成 `1` 時只提供、也只能呼叫標示為唯讀的工具。 |
| `JE_AUTOCONTROL_MCP_TOOL_PROFILE` | 未設定 | `static` 模式的工具清單：以逗號分隔的工具名稱與 `category:<名稱>`。 |
| `JE_AUTOCONTROL_MCP_ALIASES` | `1` | 設成 `0` 時不註冊 `ac_*` 工具之外的簡短別名（`click`、`screenshot` …）。 |
| `JE_AUTOCONTROL_MCP_TOKEN` | 未設定 | HTTP 傳輸的 Bearer 權杖。啟用 RBAC 之後不再接受。 |
| `JE_AUTOCONTROL_MCP_ALLOWED_ORIGINS` | 未設定：只接受本機來源 | HTTP 傳輸額外接受的瀏覽器來源（以逗號分隔，須完全相符，例如 `https://example.test:8443`）。 |
| `JE_AUTOCONTROL_MCP_CONFIRM_DESTRUCTIVE` | 未設定 | 設成 `1` 時具破壞性的工具在執行前先向用戶端要求確認（MCP elicitation）。 |
| `JE_AUTOCONTROL_MCP_PATH_ROOTS` | 未設定：不限制 | 工具的每一個檔案參數都必須落在這些目錄內（以作業系統的路徑分隔字元分隔）。 |
| `JE_AUTOCONTROL_MCP_PATH_ROOTS_FROM_CLIENT` | 未設定 | 設成 `1` 時同時接受 MCP 用戶端透過 `roots/list` 回報的根目錄。 |
| `JE_AUTOCONTROL_MCP_ENV_REF_ALLOW` | 未設定：不限制 | `ac_resolve_ref` 可以讀取的環境變數名稱（以逗號分隔，可用 `fnmatch` 樣式）；設了卻沒有指名任何變數時，一個都不允許。 |
| `JE_AUTOCONTROL_MCP_AUDIT` | 未設定 | JSON-lines 檔案的路徑，每一次 `tools/call` 寫入一筆記錄。 |
| `JE_AUTOCONTROL_MCP_ERROR_SHOTS` | 未設定 | 工具每次失敗時存放截圖的目錄。 |
| `JE_AUTOCONTROL_FAKE_BACKEND` | 未設定 | 設成 `1` 時 MCP 伺服器只在記憶體中記錄滑鼠、鍵盤與剪貼簿呼叫而不實際執行，供沒有顯示器的 CI 使用。 |

### REST／RBAC 與 chat-ops

| 變數 | 預設 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_RBAC_USERS` | 未設定：沿用共用權杖 | 使用者檔案的路徑。設定它就等於為 REST API 與 MCP HTTP 傳輸啟用角色。 |
| `JE_AUTOCONTROL_CHATOPS_SCRIPT_ROOT` | 未設定：`run` 會被拒絕 | chat-ops 的 `run` 指令唯一可以載入動作檔的目錄。 |

### 執行與簽署動作檔

| 變數 | 預設 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_ALLOWED_PACKAGES` | 未設定：一個都不允許 | `AC_add_package_to_executor` 可以載入的套件（以逗號分隔，含子模組），對所有進入點生效。只在行程啟動時讀取一次。 |
| `JE_AUTOCONTROL_REQUIRE_SIGNED_ACTIONS` | 未設定 | 設成 `1` 時所有會執行動作檔的路徑，都拒絕沒有有效簽章檔的動作檔。 |
| `JE_AUTOCONTROL_ACTION_SIGNING_PRIVATE_KEY` | 未設定 | Ed25519 私鑰（PEM）的路徑。只在負責簽署的機器上設定；設定後簽署會寫出第 2 版的簽章檔。 |
| `JE_AUTOCONTROL_ACTION_SIGNING_PUBLIC_KEY` | 未設定 | 對應公鑰的路徑。在每一台執行端設定：它只能驗證，不能簽署。 |
| `JE_AUTOCONTROL_ACTION_SIGNING_PASSPHRASE` | 未設定 | 私鑰建立時若有設定通行碼，在這裡提供。 |
| `JE_AUTOCONTROL_ACCEPT_LEGACY_ACTION_SIGNATURES` | 未設定 | 設成 `1` 是遷移模式：設定公鑰之後，第 2 版之前寫出的 HMAC 簽章檔會被拒絕，除非設定了這個變數。所有檔案重新簽署後請再關掉。 |

### 遠端桌面與信令

| 變數 | 預設 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_REMOTE_DOWNLOAD_DIR` | `~/Downloads/AutoControl` | 遠端桌面檢視端存放主機傳來檔案的目錄。收到的路徑一律限制在這個目錄內。 |
| `JE_AUTOCONTROL_USB_PASSTHROUGH` | 未設定 | 設成 `1` 時在遠端桌面通道上啟用 USB 直通指令。 |
| `AC_SIGNALING_SECRET` | 未設定 | 信令／設定同步伺服器的共用密鑰（`X-Signaling-Secret`）。伺服器在沒有 `--shared-secret` 時讀取它。 |

### GUI

| 變數 | 預設 | 作用 |
|---|---|---|

### 記錄檔、資料與測試

| 變數 | 預設 | 作用 |
|---|---|---|
| `JE_AUTOCONTROL_LOG_FILE` | `~/.je_auto_control/logs/AutoControlGUI.log` | 記錄檔寫入的位置。指定空裝置（`/dev/null`、`NUL`）即可關閉檔案輸出。在寫入第一筆記錄時才讀取，而不是在 import 時。 |
| `JE_AUTOCONTROL_ENV` | `default` | 資產庫目前使用的環境（`active_environment()`），讓同一份腳本在 `dev` 與 `prod` 讀到不同的值。 |
| `JE_AUTOCONTROL_REDACTION` | `off` | 截圖遮蔽的預設政策：`off`、`moderate` 或 `strict`。未知的名稱會報錯，不會被當成 `off`。 |
| `JE_AUTOCONTROL_PYTEST_ARTIFACTS` | `./autocontrol_screenshots` | 測試沒有使用 `autocontrol_screenshot_dir` fixture 時，pytest 外掛寫入失敗截圖的目錄。 |

---

Report 分頁在首次開啟時建立。關閉會釋放控制項與本機結果畫面；重新開啟會建立新頁面並讀取目前錄製狀態。關閉分頁不會停用共用 recorder。

Screenshot 分頁同樣在首次開啟時建立，關閉時釋放。螢幕尺寸查詢、截圖與像素讀取會在背景執行，顯示執行中狀態，每次接受一項工作，並使用啟動時的輸入值。關閉後丟棄晚到結果；已開始的截圖仍可能寫入檔案。隱藏會保留頁面。選區與瀏覽檔案仍須由使用者明確操作。

報表在背景產生並顯示執行中狀態。每個分頁一次接受一個產生工作，使用開始時輸入的名稱。關閉會丟棄晚到結果；已開始的檔案寫入仍可能完成。
