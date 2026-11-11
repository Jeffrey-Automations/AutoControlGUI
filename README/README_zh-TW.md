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

Windows、macOS、X11 與 Wayland 使用不同後端，實際功能取決於系統權限與選配依賴。Windows ARM64 另有限制，部署前請先閱讀安裝文件。

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
