================
關鍵字與執行者
================

關鍵字/執行者系統是 AutoControl 的 JSON 腳本引擎。你可以將自動化步驟定義為
JSON 陣列（關鍵字），由執行者解析並執行。

關鍵字格式
==========

關鍵字是 JSON 陣列，每個元素代表一個動作：

.. code-block:: json

   [
       ["function_name", {"param_name": "param_value"}],
       ["function_name", {"param_name": "param_value"}]
   ]

範例：

.. code-block:: json

   [
       ["AC_set_mouse_position", {"x": 500, "y": 300}],
       ["AC_click_mouse", {"mouse_keycode": "mouse_left"}],
       ["AC_write", {"write_string": "Hello"}]
   ]

開關類參數(``ignore_case``、``present``、``raise_on_fail``、``paste`` 等)接受 JSON 的 ``true`` / ``false``,
或依拼法判讀的字串:``"true"``、``"yes"``、``"on"``、``"1"`` 為開,其他字串(``"false"``、``"no"``、``"off"``、
``"0"``)為關。

可用的動作指令
==============

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - 分類
     - 指令
   * - 滑鼠
     - ``AC_click_mouse``, ``AC_set_mouse_position``, ``AC_get_mouse_position``, ``AC_press_mouse``, ``AC_release_mouse``, ``AC_mouse_scroll``
   * - 鍵盤
     - ``AC_type_keyboard``, ``AC_press_keyboard_key``, ``AC_release_keyboard_key``, ``AC_write``, ``AC_write_secret``, ``AC_hotkey``, ``AC_check_key_is_press``
   * - 圖片
     - ``AC_locate_all_image``, ``AC_locate_image_center``, ``AC_locate_and_click``
   * - 螢幕
     - ``AC_screen_size``, ``AC_screenshot``
   * - 錄製
     - ``AC_record``, ``AC_stop_record``
   * - 報告
     - ``AC_generate_html``, ``AC_generate_json``, ``AC_generate_xml``, ``AC_generate_html_report``, ``AC_generate_json_report``, ``AC_generate_xml_report``
   * - 專案
     - ``AC_create_project``
   * - Shell
     - ``AC_shell_command``
   * - 執行器
     - ``AC_execute_action``, ``AC_execute_files``

執行 JSON 檔案
===============

.. code-block:: python

   from je_auto_control import execute_action, read_action_json

   execute_action(read_action_json("actions.json"))

錯誤與 ``raise_on_error``
=========================

``execute_action`` 會把失敗的動作記成它的 ``repr`` 並執行下一個；``raise_on_error=True``
則在第一個失敗就拋出。以這種方式收納的是 ``AutoControlException`` 家族，以及內建的
``OSError``、``RuntimeError``、``ArithmeticError``、``AttributeError``、``TypeError``、
``ValueError``、``LookupError`` 與 ``ImportError``。

指令拋出其他錯誤（``cv2.error``、``sqlite3.Error``、外掛自訂的例外類別）時，會在該動作
被包成 ``AutoControlForeignException``，它的 ``original`` 屬性與 ``__cause__`` 是原本的
錯誤。之後它跟其他失敗一樣被記錄，``AC_try`` 會攔到、``AC_retry`` 會重試、``AC_loop``
逐輪記錄、``AC_parallel`` 記在它的分支裡。``raise_on_error=True`` 時拋出的是這個包裝，
所以原本在 ``execute_action`` 外攔 ``cv2.error`` 或 ``sqlite3.Error`` 的程式碼，應改攔
``AutoControlForeignException`` 並讀取 ``original``。

不論 ``raise_on_error`` 怎麼設都從不收納的有：斷言失敗（``AutoControlAssertionException``
與外掛自己的 ``AssertionError``）、``AC_break``／``AC_continue``、停止請求
（``ExecutionStopped``）、取消、``KeyboardInterrupt`` 與 ``SystemExit``。

執行資料夾內所有 JSON 檔案
===========================

.. code-block:: python

   from je_auto_control import execute_files, get_dir_files_as_list

   execute_files(get_dir_files_as_list("./action_files/"))

擴充執行者
==========

你可以動態載入外部 Python 套件到執行者中：

哪些套件可以載入由套件閘門決定。``AC_add_package_to_executor`` 原本能替任何動作清單匯入 ``os`` 或
``subprocess``，所以 **沒有被放行的套件一律不載入**：不在允許清單上的套件在匯入前就被拒絕，該動作以
``AutoControlExecuteActionException`` 失敗。列出一個套件也同時放行它的子模組。放行的方式有三種：

.. code-block:: python

   from je_auto_control import executor

   executor.allow_packages("time")                # 這些套件與其子模組

.. code-block:: bash

   # 所有入口都適用：兩個 CLI、socket／REST／MCP server、排程器
   JE_AUTOCONTROL_ALLOWED_PACKAGES=time,my_plugins je_auto_control start-server

   # 只對 CLI 的這一次執行；旗標可以重複
   je_auto_control run script.json --allow-package time --allow-package my_plugins

``JE_AUTOCONTROL_ALLOWED_PACKAGES`` 是以逗號分隔的清單，只在行程啟動時讀一次；不是模組名稱（以點分隔的識別字）
的項目會被略過並記錄到日誌。``executor.set_allow_arbitrary_packages(True)`` 會放行所有套件，也就是這一版之前的
預設行為（當時任何套件都會載入，只發出 ``DeprecationWarning``）。以上都不是 ``AC_*`` 命令，所以動作清單不能
自己打開閘門。


.. code-block:: python

   from je_auto_control import package_manager

   # 載入 time 模組的所有函式
   package_manager.add_package_to_executor("time")

載入後，函式可透過 ``套件_函式名`` 的命名方式使用。
例如 ``time.sleep`` 會變成 ``time_sleep``：

.. code-block:: json

   [
       ["time_sleep", {"secs": 2}]
   ]

只要閘門允許該套件，動作檔可以在同一份清單裡載入套件並使用它：

.. code-block:: json

   [
       ["AC_add_package_to_executor", ["time"]],
       ["time_sleep", [2]]
   ]

所有指令名稱會在第一個動作執行前先檢查，而 ``time_sleep`` 要等載入指令執行後
才存在，所以這樣的清單以前不論閘門怎麼設定都會以 unknown command 被拒絕。
現在符合下列全部條件的名稱會留到執行時才檢查：名稱以 ``<套件>_`` 開頭；檔案中
較前面有一個 ``AC_add_package_to_executor`` 以字面值指名該套件（``["time"]``
或 ``{"package": "time"}``\ ，不能是 ``${變數}``\ ）；而且閘門會放行該套件。
其他情況——套件未被允許、名稱用在載入之前、``AC_*`` 名稱打錯——仍然在任何動作
執行前就被拒絕。留到執行時的名稱若其實不存在（``time_slep``\ ），執行到它時
該動作會以 ``Unknown action`` 失敗。``je_auto_control validate`` 與 REST 的
事前檢查遵循同一條規則。

查看目前執行者的指令字典：

.. code-block:: python

   from je_auto_control import executor

   print(executor.event_dict)


存下的動作清單、具名 registry 與產生的文件
==========================================

**語音指令與 macro 同時檢查兩方權限。** ``AC_voice_register`` 與 ``AC_define_macro``
會記下註冊動作清單的人。``AC_voice_dispatch`` 或 ``AC_call_macro`` 執行它時，每個步驟（包含巢狀內容與
``AC_parallel`` 分支）都必須註冊者與目前呼叫端同時具備該步驟需要的權限才會執行；被拒絕的步驟記為
``AuthorizationError``。因此存下的清單不會借用 admin 的權限，也不會在 GUI 或 Python 觸發時不經檢查就執行。
來自使用者檔的註冊者會在觸發時重新讀取，所以已刪除使用者的清單不再執行。macro 表由所有伺服器共用：
每個身分只能重新定義自己的 macro；受信任的本機程式碼（沒有 RBAC 範圍）可以重新定義任何 macro，它定義的 macro
也不能被使用者取代。匿名 MCP session 以 ``mcp:<session>`` operator 身分執行，所以即使 RBAC 關閉也適用；
不在 RBAC 與 MCP 之下時行為不變。

**具名 registry 有上限。** ``AC_cas_put`` / ``AC_cas_get``、``AC_dedup_check``、
``AC_idempotency_begin`` / ``_complete`` / ``_release``、``AC_bulkhead_run``、``AC_sequence_observe``
與 ``AC_outbox_enqueue`` / ``AC_outbox_pending`` 背後的 store 每個最多保存 ``MAX_REGISTRY_NAMES``
（1,024）個名稱。達到上限時既有名稱照常運作，也不會淘汰任何狀態；新名稱（包含讀取從未寫入過的名稱）會拋出指出該
registry 的 ``RegistryFullError``。這些 registry 都沒有刪除或重設指令，名稱在程序結束時釋放。

**產生的文件保留參照。** ``AC_generate_sop``（``actions``、``title``）與 ``AC_generate_code``（``source``）
會代換已知的 ``${var}``（包含以變數組成的 ``source`` 路徑），但 ``${secrets.NAME}``、尚未綁定的名稱
（文件描述的步驟自己設定的迴圈變數）、巢狀佔位符，以及存放本次執行已解析為機密之值的變數，都照原樣寫出。

**解析出的 env:// 值會遮罩。** ``AC_resolve_ref`` 與 ``AC_resolve_refs`` 仍把 ``env://`` 值回傳給呼叫端，
但會登記到本次執行的機密遮罩，所以該次執行剩下的期間日誌、journal 與 MCP 稽核都顯示 ``***``。
``AC_resolve_ref`` 的 ``value`` 與 ``AC_resolve_refs`` 的 ``resolved`` 在記錄的結果與 Script Builder
結果窗格中也會遮罩。``file://`` 的值不會登記。

停止執行
--------

停止（或取消）會以 ``ExecutionStopped`` 結束進行中指令的等待：等待與暫停、擷取輸出的 shell 指令、共用 HTTP client、
範本比對、OCR、VLM 與 LLM 請求、唯讀無障礙讀取、adb 指令、USB 與 Wayland 擷取工具、行動裝置呼叫與 find-element 等待、
``AC_wait_for_port`` 探測、``AC_send_email`` （郵件可能已送出也可能沒有）、``AC_feature_match``、``AC_agent_run`` ／
``AC_computer_use`` 的每次模型呼叫、``AC_assert_audio`` ／ ``AC_assert_video``，以及管理主控台的輪詢與廣播（尚未連到的主機會略過）。
呼叫進行到一半被停止的行動裝置工作階段會關閉，與逾時相同。無法中斷的原生呼叫會在背景跑完，結果不會被使用。

無障礙寫入（設值／invoke／toggle）在執行中整個交給無障礙 walker 執行緒：寫入動作前收到停止就不會寫入；動作進行中收到停止則最多等 5 秒，之後回傳結果或拋出 ``AccessibilityWriteOutcomeUnknown``。Windows 上的檢查點在找到元素與動作之間，其他後端把整個呼叫視為動作。未在執行中時行為不變。

仍不可中斷： ``AC_parallel`` 等待分支結束（所有分支結束才放開按住的鍵），以及螢幕錄影的收尾。
