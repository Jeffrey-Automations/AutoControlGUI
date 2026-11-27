========
圖片辨識
========

AutoControl 使用 OpenCV 模板匹配技術在螢幕上定位 UI 元素。
可用於尋找按鈕、圖示或其他視覺元素並與之互動。

定位所有匹配
============

尋找螢幕上所有符合模板圖片的位置：

.. code-block:: python

   import time
   from je_auto_control import locate_all_image, screenshot

   time.sleep(2)

   # detect_threshold: 0.0 ~ 1.0（1.0 = 完全匹配）
   image_data = locate_all_image(
       screenshot(),
       detect_threshold=0.9,
       draw_image=False
   )
   print(image_data)  # [[x1, y1, x2, y2], ...]

定位圖片中心
============

尋找模板圖片並回傳其中心座標：

.. code-block:: python

   import time
   from je_auto_control import locate_image_center, screenshot

   time.sleep(2)

   cx, cy = locate_image_center(
       screenshot(),
       detect_threshold=0.9,
       draw_image=False
   )
   print(f"找到位置: ({cx}, {cy})")

定位並點擊
==========

尋找模板圖片並自動點擊其中心：

.. code-block:: python

   import time
   from je_auto_control import locate_and_click, screenshot

   time.sleep(2)

   image_data = locate_and_click(
       screenshot(),
       "mouse_left",
       detect_threshold=0.9,
       draw_image=False
   )
   print(image_data)

參數說明
========

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - 參數
     - 型別
     - 說明
   * - ``image``
     - str / PIL Image
     - 要搜尋的模板圖片（檔案路徑或 PIL ``ImageGrab.grab()`` 結果）
   * - ``detect_threshold``
     - float
     - 偵測精確度，範圍 ``0.0`` 到 ``1.0``。``1.0`` 要求完全匹配。
   * - ``draw_image``
     - bool
     - 若為 ``True``，會在回傳的圖片上標記偵測到的區域。

找不到與輸入不能用
==================

``ImageNotFoundException`` 代表搜尋跑過、範本不在畫面上。搜尋無法使用的輸入改拋
``ImageSearchInputException``\ ：

* 範本檔不存在或無法解碼；
* 單一顏色的範本（到處都會得到完全相符的分數）；
* ``detect_threshold`` 超出 ``0``-``1``\ 、是 NaN 或不是數字；
* OpenCV 無法比對的影像（不支援的色彩排列或像素型別）。

兩者在 ``AutoControlException`` 底下是兄弟而非父子，所以處理「找不到」的程式碼
不會攔到範本路徑打錯的情況：

.. code-block:: python

   from je_auto_control import (
       ImageNotFoundException, ImageSearchInputException, locate_image_center,
   )

   try:
       locate_image_center("save_button.png", detect_threshold=0.9)
   except ImageNotFoundException:
       print("不在畫面上")
   except ImageSearchInputException as error:
       print(f"請修正範本或門檻: {error}")

因此不存在檢查遇到不能用的輸入會失敗，不再通過：``AC_assert_image`` 加
``present: false`` 會失敗（"the template could not be used"），``AC_wait_image_gone``
與 ``ac_wait_for_image`` 直接拋出而不是等待，``AC_if_image_found`` 記成失敗而不是
執行 ``else`` 分支。用這種範本的影像觸發器會被停用並記錄；觀察者規則、狀態機的
``if_image_found`` 守衛與 anchor locator 會拋出例外。自我修復仍會退回 VLM 步驟，並
回報範本失敗的原因。裝置畫面（``DeviceFrame.locate_image``）也採同樣的區分。
