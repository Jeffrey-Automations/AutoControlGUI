# Development and resources

[README](../../../README/README_zh-TW.md) · [Documentation](../../README.md)

## 文件與範例

| 資源 | 內容 |
|---|---|
| [`examples/`](../../../examples) | 45 個自足腳本：截圖點擊、OCR、排程器、遠端桌面、agent loop、可觀測性、錄製、變數、熱鍵、觸發器、報表、MCP、REST、機密、外掛、computer use、Wayland、跨主機 DAG、chat-ops、pytest/BDD、錨點定位、動作日誌、因果 peer 控制。 |
| [Read the Docs](https://autocontrol.readthedocs.io/en/latest/) | 完整 API 參考，含英文與中文。 |
| [architecture_explore.md](../../../architecture_explore.md) | 逐層記錄每個模組的職責。 |
| [docs/CAPABILITY_MATRIX.md](../../CAPABILITY_MATRIX.md) | 能力 × 平台對照矩陣。 |
| [docs/API_LIFECYCLE.md](../../API_LIFECYCLE.md) | 穩定 API 與棄用政策。 |
| [docs/updates/](../../updates/README.md) | 更新紀錄：各版本說明與完成的工作，每月一個檔（原 `WHATS_NEW.md`）。 |
| [CHANGELOG.md](../../../CHANGELOG.md) | 相容性變更記錄。 |
| [SECURITY.md](../../../SECURITY.md) | 安全政策與回報方式。 |

---

## 開發

```bash
git clone https://github.com/Integration-Automation/AutoControlGUI.git
cd AutoControl
pip install -r dev_requirements.txt
uv sync                 # 或：以已提交的 uv.lock 做可重現安裝
```

```bash
python -m pytest test/unit_test/headless      # 無頭單元測試
python -m pytest test/integrated_test/        # 跨模組流程測試

ruff check je_auto_control/
pylint je_auto_control/
bandit -c pyproject.toml -r je_auto_control/

python test/verify/typing_contract_verify.py            # mypy，整個套件，三個目標平台
python test/verify/typing_contract_verify.py --extras   # 同一項檢查，改用真正的 PySide6／aiortc 型別
python -m sphinx -b html -W docs/source docs/_build/html  # 文件，警告視為錯誤
```

dev／main 的無頭工作會保留七天的 `native-<os>-<python>` artifact，內含合併行程輸出、
套件／執行環境版本與退出碼。Linux 經 GDB 保留各執行緒原生堆疊；其他平台保留 Python
faulthandler 輸出，測試失敗仍會使工作失敗。可在 repo 執行單一指令
`python scripts/ci_native_diagnostics.py --artifact-dir test-artifacts -- python -m pytest -v --tb=short --timeout=120`；
Linux 安裝 GDB 後，可在 `--` 前加入 `--native`。
含空白／引號的 argv 仍是原始參數，已處理的 `SIGINT` 會傳給子行程。
Linux 先在完整套件的 debugger 外驗證診斷工具；前置檢查紀錄也收在同一 artifact。

選定的 dev 推送由 `.github/workflows/ei-lifecycle.yml` 在隔離 libei／libeis
容器執行，將版本及兩份原生紀錄保留於 `ei-lifecycle-<run>-<attempt>` artifact 十四天。
半開與 live 釋放子行程分別有十／六十秒時限與 faulthandler；其他子行程失敗使 CI 失敗，
釋放成功必須有 begin／end 標記。半開探測另須有相同整數 fd 數量，live 清理先釋放擁有的
device refs。run 39507190704 在 libei／libeis 1.3.901-1 通過 9/9 與 20/20 檢查，
包含座標越界拒絕且不轉用 CLI。半開 `ei_unref` 仍會 SIGSEGV，因此保留 runtime 保護，
helper 隔離仍待完成。裝置暫停與序號回讀仍未驗證；受控 socket peer 不代表合成器授權、
真機或多螢幕驗收。

歡迎貢獻——請見 [CONTRIBUTING.md](../../../CONTRIBUTING.md) 與
[CODE_OF_CONDUCT.md](../../../CODE_OF_CONDUCT.md)。CI 會強制兩條規則：`import je_auto_control`
絕不能載入 PySide6；每個功能都必須同時具備無頭 API 與 GUI 介面。

---

## 授權

[MIT License](../../../LICENSE) © JE-Chen。
內含與選用第三方元件的授權請見 [Third_Party_License.md](../../../Third_Party_License.md)。

- **首頁**：https://github.com/Integration-Automation/AutoControlGUI
- **PyPI**：https://pypi.org/project/je_auto_control/
- **文件**：https://autocontrol.readthedocs.io/en/latest/

舊式 MCP 動作包裝、平行分支及本機 DAG worker 也會保留相同的來源限制。

受管指標動作可指定該次觀察的元素索引或縮圖座標，由主機檢查目前畫面並換算原生座標，包含縮放與負螢幕原點。收據保存幾何依據，不保存影像位元組。`AgentObservationStale` 表示分派前已拒絕動作；本機 agent 只在 adapter 確認沒有按住或待處理輸入時，於重試預算內重新觀察。

緊急停止先回傳帶有 metadata.details_deferred 的精簡狀態，完整產物連結可由個別任務查詢。

受管滑鼠按下前會正規化按鈕擁有權並確認實際游標位置。Windows 指標檢查會拒絕其他視窗遮擋。影像只將指定視窗繪製至清空的私有 GDI 記憶體，幾何變動會拒絕該畫面；繪製或讀取失敗亦會釋放資源。不改用桌面擷取。這些路徑已用模擬原生 API 測試，實際原生驗收仍未驗證。

Agent 任務介面將任務範圍、工作流程設定、觸發器、技能及恢復分頁。觀察頁顯示唯讀元素和已驗證、嚴格遮罩的 JPEG，每個邏輯畫面像素對應一個呈現像素。選取元素或影像座標只會編輯該次觀察的動作請求；由 Actions 的「執行觀察動作」透過共用任務 API 送出。切換任務會清除預覽，遲到回覆不能替換目前任務；新畫面必須重新選取，舊索引不能直接重用。關閉介面只解除請求訂閱。

受管工作流程可用 workflow_wait／AC_workflow_wait 等待指定控制項的精確值或狀態，只重複讀取；可取消且受動作預算限制，預設五秒、上限六十秒，不重送寫入或提交。固定技能每一步都驗證已完成收據與固定順序，恢復亦不能跳過讀回失敗的步驟；模型自主迴圈仍保留停滯偵測。新表單／跨應用範本會在提交前拒絕原本已匹配的確認值，提交後等待新的狀態轉換。批次可設定 new_record_selector 逐筆重設；確認只證明設定的介面轉換，有交易識別值時應使用它。歸檔範本完成時會重讀指定清單及檔案摘要，清單上限一 MB，總驗證資料上限六十四 MiB。

AgentHumanReview 表示未儲存內容或未知對話框需人工審閱；包含外部觀察請求都會記錄 waiting_user 並釋放輸入控制權，明確恢復後仍會重新檢查。Windows 依原生對話框／停用擁有者及英中日已知未儲存文字判定。Workspace 也會拒絕標題首尾帶星號的文件，並可在視窗設定加入 unsaved_selector 與 unsaved_value，於改變排列前檢查應用特有指示；不宣稱能推斷所有程式的未儲存狀態。標準檔案對話框沿用 AC_handle_file_dialog 執行器，受管 driver 只接受唯一精確標題、相同 PID、已確認前景，以及授權根目錄內的絕對路徑。UIA 控制項須屬於實際指定的根視窗，同 PID 的其他視窗也會拒絕。模擬原生與本機 HTTP 測試已有覆蓋，實際平台驗收仍未驗證。

主機目標以 AgentTargetProfile 與 manage_agent_target（AC_agent_target，register/get/disable/enable/probe）設定。名稱及設定固定不可替換，目前提供 desktop／files／browser adapter，未實作類型會被拒絕；瀏覽器可使用主機審閱的 helper_python。任務固定主機設定摘要，不能擴大工具、應用、根目錄或網路來源。啟停狀態會跨重啟保存並於分派時檢查；停用會要求暫停及清理，重新啟用仍須明確恢復任務。list_agent_targets／AC_agent_target_list／CLI agent-task targets 只提供被動資訊，readiness=not_probed、native_evidence=not_recorded；完整設定需要 manage_hosts。CLI agent-task target 及 GUI「主機目標」頁使用同一服務。匿名有效 MCP 工具 session 的直接及舊式包裝呼叫都以 operator 權限執行；MCP 主機管理需要已驗證的管理員，可信任的直接 Python 呼叫維持原行為。瀏覽器自動化統一由 WebRunner（je_web_runner）提供，本機開發來源為 D:/Codes/WebRunner；browser profile 使用受管 je_web_runner SDK 契約，依賴診斷不代表原生可用。

既有瀏覽器自動化（包含 open_path(URL) 與 AC_open_path）統一交由 WebRunner，Python 套件名稱為 je_web_runner。URL 計畫的 backend 現為 je_web_runner，原本比較 webbrowser 描述值的呼叫端需改用新值；函式介面與本機檔案開啟維持相容。實際 URL 執行需要設定的 WebRunner 專案，缺少時傳出 WebRunnerBridgeError，不改用 OS 瀏覽器。本機開發來源為 D:/Codes/WebRunner；純計畫及注入 opener 測試不需要該套件。協定支援由 WebRunner 與其選用的瀏覽器決定。既有瀏覽器 GUI／MCP／AC 及錄製的 WR_* 動作都使用同一橋接。
