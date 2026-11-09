# Agents and integrations

[README](../../../README/README_zh-TW.md) · [Documentation](../../README.md)

## AI Agent 與 Computer Use

**AutoControl 是開源、跨平台的 computer-use 與 GUI 自動化框架。**

當 AI agent 需要操作真實桌面、原生應用程式、真正的瀏覽器視窗、遠端桌面或行動裝置，而不只是操作瀏覽器 DOM/API 時，使用 AutoControl。

### 何時選擇 AutoControl

- 真實滑鼠與鍵盤輸入
- 螢幕擷取與座標操作
- OCR 與原生無障礙樹
- 影像／樣板比對
- Vision-Language Model UI 定位
- Anchor 與 self-healing locator
- 跨平台桌面／行動裝置自動化
- JSON 動作檔
- MCP computer use

建議的 agent loop：

**observe → identify → act → wait → verify → recover**

完整的 [AI Agent 指南](../../../AI.md) 提供 MCP 設定、工具選擇、OpenAI 整合、安全性與 computer-use 關鍵字。

### AI-friendly MCP

```bash
pip install je_auto_control
je_auto_control_mcp
```

MCP 提供完整的 `ac_*` 工具，以及 `click`、`type`、`screenshot`、`find_text`、`click_text`、`drag`、`focus_window`、`wait_image` 等短名稱 alias。

只做檢查：

```bash
je_auto_control_mcp --read-only
```

只需要 canonical `ac_*` 名稱：

```bash
JE_AUTOCONTROL_MCP_ALIASES=0 je_auto_control_mcp
```

OpenAI agent 請使用 `export_openai_tools(only=[...])` 提供聚焦工具集，不要一次提供整個 AutoControl 命令目錄。

### 專案識別

**專案：** AutoControl<br>
**Repository：** `Integration-Automation/AutoControlGUI`<br>
**Python package / PyPI：** `je_auto_control`<br>
**MCP command：** `je_auto_control_mcp`


---


## 伺服器與整合

| 介面 | 啟動方式 | 說明 |
|---|---|---|
| **MCP 伺服器** | `je_auto_control_mcp`（stdio）或 `AC_start_mcp_http_server` | 820 個工具，供 Claude Desktop／Claude Code／自訂 tool loop 使用：完整的 `ac_*` 工具介面，以及常用 GUI 操作的短名稱 alias。除了以 `initialize` 握手的各版協定，也支援無狀態的 MCP 2026-07-28。Bearer 驗證、TLS、稽核記錄、限流、外掛熱重載、CI 假後端。 |
| **REST API** | `je_auto_control start-rest` | Bearer token、逐 IP 限流與鎖定、SQLite 稽核 hook、`/metrics`、`/openapi.json`、`/docs` Swagger UI、`/dashboard`。 |
| **TCP socket 伺服器** | `je_auto_control start-server` | 以換行分隔的 JSON 動作清單。預設綁 `127.0.0.1`。 |
| **pytest 外掛** | 安裝後自動生效 | 提供 fixture 與供 pytest-bdd／behave 使用的 Gherkin step library。 |
| **語言伺服器** | `python -m autocontrol_lsp.server` | 為 `AC_*` 動作 JSON 提供補全與診斷，指令清單直接取自執行期的指令表。 |
| **遠端桌面** | `RemoteDesktopHost` 或 GUI | TCP、WebSocket 或 WebRTC；TOTP、信任清單、TURN 設定、檔案／剪貼簿／音訊同步。 |

除非明確指定，所有伺服器都綁在 `127.0.0.1`。

MCP 視窗狀態工具 `ac_window_minimize`、`ac_window_maximize` 與 `ac_window_restore` 在後端接受要求時回傳視窗 handle，遭拒時回覆 `isError: true`（包括 handle 失效或啟用請求被拒）。Win32 原始 `ShowWindow` 的先前可見性由後端正規化處理。

**套件閘門。** `AC_add_package_to_executor` 與 `AC_add_package_to_callback_executor` 會匯入 Python 套件並把成員註冊成命令，所以從上面任何一個入口送來的動作清單都可能載入 `os` 或 `subprocess`。沒有被放行的套件不會載入：不在允許清單上的套件在匯入前就被拒絕，該動作以 `AutoControlExecuteActionException` 失敗。放行套件（含子模組）的方式：在 Python 裡呼叫 `executor.allow_packages("name", …)`；對所有入口——兩個 CLI、socket／REST／MCP 伺服器與排程器——設定環境變數 `JE_AUTOCONTROL_ALLOWED_PACKAGES`（以逗號分隔的名稱，行程啟動時讀取）；或只對一次 CLI 執行使用 `je_auto_control run script.json --allow-package NAME`（可重複）。`executor.set_allow_arbitrary_packages(True)` 會對所有套件打開閘門，也就是先前版本的預設行為（當時會發 `DeprecationWarning`）。這些都不是 `AC_*` 命令，所以動作清單不能自己打開閘門。

**選用的強化設定。** 下列各項在設定之前都是關閉的，沒設定的伺服器行為與先前相同。`JE_AUTOCONTROL_RBAC_USERS=<使用者檔>` 讓 REST API 與 MCP HTTP 傳輸把 bearer token 對到使用者，並依角色（viewer／operator／admin）授權每一個路由、工具與特權 `AC_*` 命令；此時共用 token 會被拒絕。`JE_AUTOCONTROL_MCP_PATH_ROOTS`（以作業系統的路徑分隔字元分開的目錄）把每一個屬於檔案路徑的 MCP 工具參數限制在這些目錄裡，`JE_AUTOCONTROL_MCP_PATH_ROOTS_FROM_CLIENT=1` 再加上 client 的 `roots/list`，`JE_AUTOCONTROL_MCP_ENV_REF_ALLOW` 限制 `ac_resolve_ref` 可以讀哪些 `env://` 名稱。`JE_AUTOCONTROL_ACTION_SIGNING_PUBLIC_KEY` 讓端點只能驗證 Ed25519 簽章的動作檔而不能簽章（`create_signing_keypair`；私鑰留在簽章的機器上）。遠端桌面的 viewer 只把 host 推來的檔案寫在 `~/Downloads/AutoControl` 底下（`JE_AUTOCONTROL_REMOTE_DOWNLOAD_DIR`）；這一項預設就是開的。

REST GUI 在使用者存放檔啟用時顯示 RBAC 模式並停用共用 token 欄位。`rest_api_registry.status()` 提供 `rbac_enabled`，該模式的 `token` 為 `null`；請使用個別使用者 token。只實作 `check()` 的自製 REST gate 仍可用於共用 token 模式；RBAC 要求已驗證的使用者 context，會拒絕沒有身分的成功結果。

RBAC viewer 不會取得列管的敏感讀取工具，即使 MCP `readOnlyHint` 為 true：剪貼簿／歷史、本機文件／資料／SQL 與 dotenv 讀取、參照解析、認證資料產生、持久存放區讀取、對外檢查、麥克風擷取與外部 VLM 請求都需要 operator／admin。斷言容器的 spec 也可能讀取這些資源，因此同樣需要 operator。螢幕觀察與純輸入解析維持既有分類。`ac_realize_item`、`ac_idempotency_begin` 與 `ac_rate_limit` 會改變狀態，已從 `--read-only` 模式排除。

間隔／cron 排程、觸發器、熱鍵、watchdog 規則、webhook、e-mail 觸發器與 observer 回呼會保留註冊者身分。每次觸發重新檢查來源使用者檔與角色；已刪除的使用者、無法使用的來源檔與 viewer 不能執行背景工作。啟動 daemon 不會改變既有工作的擁有者。擁有者資訊不保存 RBAC bearer token；未帶 `store_path` 的明確 Python `AuthorizationContext` 保留角色快照，未在 RBAC 下註冊的工作會清除 worker 原有身分。observer／watchdog 回呼使用獨立變數範圍，watchdog 動作失敗不會算成成功排除彈窗。巢狀回呼會保留呼叫端的失敗計數；webhook 擁有者被撤銷權限時回應 HTTP 403 與 `fired: false`。

### 遠端桌面的線路協定

TCP host 在送出 `AUTH_FAIL` 前就釋放認證失敗的 client 名額。Viewer 即使因錯誤 token、錯誤握手訊息或拒絕核准而失敗，也能立即重試，不必等 socket 清理或日誌完成；待處理握手仍有獨立的資源上限。

把主機開出去之前值得先知道，而且這段在其他文件裡都沒有寫。預設傳輸是**裸 TCP
上的長度前綴分幀**（不需要額外相依），連線一開始就是 **HMAC-SHA256 的
challenge／response 握手**：驗證沒過的觀看端在拿到任何一張畫面之前就會被斷掉。
JPEG 影格依設定的 FPS 與品質編碼，再透過一個共用的**最新影格槽**發給已驗證的
觀看端——所以慢的觀看端是**掉影格**，不會把其他人一起卡住。觀看端送來的輸入是
JSON，會先比對**動作允許清單**才交給既有的輸入包裝層執行，觀看端無法自己發明
新的操作。

```python
# 讓別人連進來——開一個主機，把 token 與 port 給對方
from je_auto_control import RemoteDesktopHost
host = RemoteDesktopHost(token="hunter2", bind="127.0.0.1",
                         port=0, fps=10, quality=70)
host.start()
print("listening on", host.port, "viewers:", host.connected_clients)
```

```python
# 控制另一台機器——連上去並送輸入
from je_auto_control import RemoteDesktopViewer
viewer = RemoteDesktopViewer(host="10.0.0.5", port=51234, token="hunter2",
                             on_frame=lambda jpeg: ...)
viewer.connect()
viewer.send_input({"action": "mouse_move", "x": 100, "y": 200})
viewer.disconnect()
```

也可以用 IP 允許清單（CIDR 網段或個別位址）限制誰連得進來，清單外的對端在握手
階段就會被拒絕：

```python
RemoteDesktopHost(token="tok", ip_allowlist=["10.0.0.0/8", "192.168.1.100"])
```

---
