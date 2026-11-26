==============================
Socket 伺服器（遠端 API）
==============================

.. warning::

   這是 **實驗性** 功能。

Socket 伺服器允許其他程式語言（或遠端機器）透過 TCP 傳送 JSON 指令來使用 AutoControl。
每條連線都必須先驗證。

啟動伺服器
==========

.. code-block:: python

   import time
   from je_auto_control import start_autocontrol_socket_server

   server = start_autocontrol_socket_server(host="127.0.0.1", port=9938)
   print("token file:", server.token_path)
   # quit_server 會關閉監聽 socket。
   while server.socket.fileno() != -1:
       time.sleep(0.5)

或從命令列：

.. code-block:: bash

   je_auto_control start-server --port 9938 [--token T] [--token-file PATH] [--no-auth]

伺服器在背景執行緒中執行，預設綁 ``127.0.0.1``。

驗證
====

客戶端在連線上送出的第一行必須是 ``AUTH <token>``。伺服器回 ``AUTH_OK``，
之後照舊讀取一條指令。

伺服器接受哪個 token：

- **RBAC 關閉** （未設定 ``JE_AUTOCONTROL_RBAC_USERS``）：伺服器 token。依序取
  ``token`` 參數（CLI ``--token``）、環境變數 ``JE_AUTOCONTROL_SOCKET_TOKEN``，
  都沒有時於啟動時以 ``secrets.token_urlsafe(32)`` 隨機產生。它給予伺服器一直以來的
  受信任行為。
- **RBAC 開啟** ：只接受 RBAC 使用者庫裡某位使用者的 token。伺服器 token 不被接受，
  也不寫 token 檔：與 REST、MCP 相同，沒有身分的 token 會讓持有者等於關掉 RBAC。
  每個指令都以該使用者的角色執行。執行動作清單需要 ``drive_input``；整份清單在第一個
  動作執行前就先檢查，動作檔中巢狀的指令則由執行器以同一角色檢查。``quit_server``
  需要 ``manage_hosts``。

伺服器 token 以原子方式寫入 ``~/.je_auto_control/socket_server_<port>.token``
（實際綁定的連接埠；CLI ``--token-file``／參數 ``token_path`` 可改路徑）。
這個檔案只有擁有者能讀：POSIX 上為 0600，Windows 上存取清單只列目前使用者。
伺服器關閉時會刪除它，除非之後已有另一個伺服器換掉了檔案。CLI 只印出檔案路徑，
從不印出 token 本身。

驗證失敗的限制：

- 從連線到 ``AUTH_OK`` 最多 10 秒；屆時仍未通過驗證的客戶端會被斷線。
- 每條連線最多 3 次錯誤 token，之後關閉連線。
- 失敗嘗試依客戶端位址限流（沿用 REST 伺服器的閘門）：一分鐘內失敗 8 次後，錯誤 token
  會收到 ``authentication refused: too many failed attempts``。正確的 token 永遠不會被鎖住。

沒有先 ``AUTH`` 就送出的指令（包括 ``quit_server``）會被以 ``authentication required``
拒絕，不會執行。

**舊版相容的關閉選項。** ``require_auth=False``（CLI ``--no-auth``）讓每條連線不需
``AUTH`` 就以受信任身分執行，並在啟動時記錄一則警告：任何連得到伺服器的程序都能執行
任何指令，``quit_server`` 也包括在內。若客戶端仍送出 ``AUTH``，會收到 ``AUTH_OK``。

傳送指令（客戶端）
==================

``send_socket_command`` 會先驗證、送出一條指令，並回傳回覆的各行。token 依序取
``token`` 參數、``JE_AUTOCONTROL_SOCKET_TOKEN``、該連接埠的伺服器 token 檔
（``token_path`` 可改路徑）。RBAC 下請傳使用者的 token。token 被拒時拋出
``SocketAuthError``。

.. code-block:: python

   import je_auto_control as ac

   lines = ac.send_socket_command([
       ["AC_set_mouse_position", {"x": 500, "y": 300}],
       ["AC_click_mouse", {"mouse_keycode": "mouse_left"}],
   ], host="127.0.0.1", port=9938)
   print(lines)
   ac.send_socket_command("quit_server", port=9938)

``read_socket_token(port)`` 從檔案讀出 token；``authenticate_connection(connection, stream, token)``
在你自己開的 socket 上完成握手。連 ``--no-auth`` 伺服器時傳 ``require_auth=False``。

任何語言的原始客戶端：

.. code-block:: python

   import json
   import pathlib
   import socket

   token = (pathlib.Path.home() / ".je_auto_control" / "socket_server_9938.token").read_text().strip()
   sock = socket.create_connection(("127.0.0.1", 9938))
   sock.sendall(f"AUTH {token}\n".encode("utf-8"))
   command = json.dumps([["AC_set_mouse_position", {"x": 500, "y": 300}]])
   sock.sendall((command + "\n").encode("utf-8"))

   response = b""
   while b"Return_Data_Over_JE" not in response:
       chunk = sock.recv(8192)
       if not chunk:
           break
       response += chunk
   print(response.decode("utf-8"))  # 以 AUTH_OK 開頭
   sock.close()

既有客戶端的遷移
================

照未驗證協定寫的客戶端現在會收到 ``authentication required``，指令不會執行。擇一處理：

- 第一行送出 ``AUTH <token>\n``，並在讀指令回覆前先讀掉 ``AUTH_OK`` 那一行；token 取自
  token 檔、``JE_AUTOCONTROL_SOCKET_TOKEN``，或（RBAC 下）使用者的 token；或
- 以 ``--no-auth``／``require_auth=False`` 啟動伺服器保留舊協定，並接受此時任何本機程序
  都能操控這台機器。

協定細節
========

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 屬性
     - 值
   * - 編碼
     - UTF-8
   * - 握手
     - 第一行 ``AUTH <token>``，回 ``AUTH_OK``（``--no-auth`` 時不需要）
   * - 回應結束標記
     - ``Return_Data_Over_JE``
   * - 拒絕
     - 一行錯誤訊息，接著 ``Return_Data_Over_JE``
   * - 關閉伺服器指令
     - （``AUTH`` 之後）傳送 ``"quit_server"`` 以停止伺服器；除非被拒，否則沒有回覆
   * - 請求格式
     - 每個連線一個指令：JSON 動作清單加一個換行。可以縮排；指令在能完整解析的
       那個換行結束（或在客戶端關閉寫入端時結束）。
   * - 回應格式
     - 每個結果一行，最後是 ``Return_Data_Over_JE`` 與換行。請讀到這個標記為止；
       單次 ``recv`` 可能只拿到一部分。
   * - 預設連接埠
     - 9938
   * - Token 檔
     - ``~/.je_auto_control/socket_server_<port>.token``，僅擁有者可讀，關閉時刪除

Driver 執行檔
=============

``autocontrol_driver/generate_autocontrol_driver.py`` 會啟動需要驗證的 socket 伺服器，並持續執行到客戶端送出
``quit_server``。它的執行檔不放在 repo 裡，而是由 ``Driver`` workflow（``.github/workflows/driver.yml``）
在 Windows 與 Ubuntu runner 上用 Nuitka 建置：

* Windows：一個沒有主控台視窗的 ``AutoControlDriver.exe`` （``--windows-console-mode=disable``）。
* Linux：一個 ``AutoControlDriver`` 二進位檔。

每個建置都會啟動一次，必須拒絕沒有 token 的指令、回應帶 token 的指令，並在收到 ``quit_server`` 後結束
（``autocontrol_driver/smoke_driver.py``）。建置結果會上傳為 workflow artifact，並附在每個發布的 GitHub release。
在本機建置：

.. code-block:: bash

    python -m pip install nuitka==4.3.5 zstandard==0.25.0
    python autocontrol_driver/build_driver.py --output-dir dist

Driver 沒有視窗：token 請從上面的 token 檔讀取，停止它請送 ``quit_server``。
