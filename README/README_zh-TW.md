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

## 可以做什麼

- 操作滑鼠、鍵盤與視窗。
- 用圖片比對、OCR、無障礙 API 或選配的視覺模型尋找控制項。
- 將重複工作儲存為 JSON 動作檔。
- 透過 MCP 連接 AI 用戶端，或透過 REST 與 Python 整合。
- 在選配 GUI 中使用錄製、排程與遠端桌面工具。

影像偵測分頁在背景執行比對，並有自己的滑鼠按鍵選擇。
Actions 選單可停止待完成的搜尋；關閉分頁會丟棄晚到結果，重新開啟會重設輸入欄位。
取消可阻止後續移動與點擊步驟，但無法中斷已進入的原生呼叫。

自動點擊、錄製與腳本執行分頁各自持有控制項與背景工作；關閉會停止本頁工作，重開會建立新的輸入欄位。共用錄製器不隨分頁關閉，重開後會讀取後端狀態，不支援查詢時顯示未知；此狀態不代表原生掛鉤健康檢查。Ctrl+4 仍可停止腳本與自動點擊。

View → 執行詳情（Ctrl+Shift+D）可展開右側詳情。診斷分頁會提供實際進度、停止、結果與錯誤狀態；其他分頁尚未提供時會明確顯示。切換或關閉分頁會斷開其更新。嵌入程式可將 TabRegistry 傳入 WorkspaceShell；AutoControlGUIWidget(parent) 仍可使用。

WebRTC 統計輪詢在背景啟動，停止後會捨棄晚到的樣本。

Windows、macOS、X11 與 Wayland 使用不同後端，實際功能取決於系統權限與選配依賴。Windows ARM64 另有限制，部署前請先閱讀安裝文件。

Wayland NORMAL 輸入透過受管理的子程序執行 libei 與 portal 呼叫。逾時、取消或回覆不確定時會退役該程序，不重播輸入或自動切換供應者。直接使用 `LibeiBackend` 仍在呼叫端程序內執行；子程序退役不代表合成器已釋放輸入，原生驗收仍待執行。

受管理的 Agent 任務與跨主機傳輸包含實驗性功能；採用前請查看實作紀錄與專案進度中的驗收狀態。

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

關閉 Remote Desktop 會釋放頁面；重新開啟會建立新控制項，不自動接回共用連線。Registry 的 TCP／WebSocket 連線仍可供腳本使用；頁面擁有的 WebRTC 連線與音訊在背景停止。待處理核准會拒絕，延遲回呼會丟棄。已進入傳送階段的檔案傳輸須依後端的合作式取消停止。

WebRTC host/viewer 的 `stop()` 最多等待三秒完成軟體清理。`PeerStopPending` 保留同一個尚未完成的操作；明確重試只會繼續等待。`PeerStopFailed` 保留清理失敗的資源供明確重試，成功前禁止重新啟動。Multi-viewer host 保留失敗的 session 與共用來源。`FolderSyncEngine.stop_confirmed()` 在原工作執行緒仍存活時回傳 `False`。這些結果不代表原生裝置已釋放；頁面銷毀後的復原仍需持久資源保管與重試整合。

主機檔案請求會保留原傳送工作，直到工作執行緒退出，重複停止也不會提前釋放所有權。停止會通知取消並等候原工作；無法中斷的後端操作仍可能讓停止維持待完成。

MCP 唯讀標記不授予 viewer 存取權。已審查的即時畫面與呼叫者資料運算使用 `read_screen`；檔案、裝置資料及未知工具需要 `read_data`。別名共用標準名稱的權限，較強的明確設定優先。提供影像來源、從環境變數讀取設定欄位或規劃開啟本機檔案時需要 `read_data`。Anchor locator 的 accessibility／OCR 允許觀測即時畫面，影像範本需要 `read_data`，VLM 請求需要 `drive_input`。唯讀呼叫拒絕擷取產物及 VLM 分支，目錄排除可自選 ADB 執行檔的工具。MCP CI annotations 只回傳格式化文字，不寫入 stdout。未審查的 plugin 與 WebRunner 初始化工具不列入唯讀目錄，等待相依版本的個別審查。

REST 主機資料讀取與對應 MCP 權限一致：排程、遠端 session、USB passthrough 狀態、loopback／remote 裝置清單及診斷需要 `read_data`。對應已註冊的狀態指令、`AC_probe_capabilities` 與 `AC_diagnose` 會在執行提供者之前檢查權限。唯讀標記不授予 viewer 存取權；operator／admin 仍可使用。USB 列舉／事件、保留的 inspector 統計與程序 metrics 也需要 `read_data`；`AC_list_usb_devices`、`AC_usb_recent_events`、`AC_inspector_recent`、`AC_inspector_summary` 同樣檢查此權限。Dashboard 各面板分別顯示缺少的權限並清除舊資料；session 重新整理成功後也會清除先前的錯誤狀態。未列入權限表格的 executor 指令仍屬另一項審查範圍。

主機唯讀模式對外部提供的目錄及後續註冊套用相同限制，接收請求及重新核對身分後的呼叫都檢查混合用途參數。MCP 設定的失敗截圖需要可寫入的工具及重新核對後具輸入操作權限的呼叫者；唯讀呼叫與 viewer 不會觸發截圖。這不表示所有相依套件或診斷讀取均無初始化副作用。

內部 Windows 行程記憶體準備工作新增映像檔量測，透過保留的唯讀 handle 執行有界雜湊並保留失敗清理供重試。這只是觀測到的檔案證據，不是已載入程式碼或 fixture 的身分證明；原生驗收及公開記憶體工具仍未提供。詳見[契約](../docs/process_memory_contract.md)。

媒體 producer 關閉會回報待完成或不確定的清理結果，並保留原始資源。音訊與錄影不會透過不安全的 close／flush 重播宣稱成功；LAN close 可明確重試。應用程式 caretaker 與 GUI 整合仍待完成。詳見[清理契約](../docs/media_retirement_contract.md)。

HostBrowser 亦會拒絕晚到發布，並保留未完成的執行緒與關閉所有權；對話框整合仍待完成。

MultiViewerHost 可回傳含原始 session 清理物件的 offer，延後清理不會停止替換後的連線或畫面來源；GUI 接入仍待完成。
