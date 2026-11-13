自適應 GUI：頁首、卡片與會縮小的控制項
======================================

GUI 正以一組共用的自適應元件重新設計，讓每個分頁外觀一致，也放得進小視窗。
本頁說明目前已完成的部分：元件、視窗本身的斷點，以及每個分頁因此得到的改變。
各分頁逐頁改用這些元件，會在之後的版本陸續交付。

視窗依寬度調整
--------------

.. list-table::
   :header-rows: 1

   * - 視窗寬度
     - 導覽
     - 執行詳情
   * - 1,200 px 以上
     - 停靠在左側
     - 右側一欄
   * - 800-1,199 px
     - 停靠在左側
     - 從右側覆蓋在分頁上的抽屜
   * - 800 px 以下
     - 圖示欄
     - 從右側覆蓋在分頁上的抽屜

最窄時，按圖示欄的選單鈕、**Ctrl+B** 或 **Ctrl+K** 會以抽屜開啟功能清單；
選擇功能、按 **Escape** 或點擊變暗的區域即關閉。圖示欄最後一個按鈕切換執行詳情。
寬度須越過邊界 24 px 才會切回，在邊界附近拖曳視窗邊緣不會閃動。

**View → Navigation Panel**（**Ctrl+B**）仍記錄你是否想要停靠的清單。這個偏好與寬度分開：
視窗縮到 800 px 以下會隱藏停靠面板但不改動偏好，再放寬時只有原本顯示才會出現。關閉視窗時照舊儲存。

每個分頁都有的
--------------

* **頁首。** 每個分頁開頭顯示標題與一行用途說明（依目前語言）。說明取自
  ``<title_key>_subtitle`` 字串（Mobile 為 ``tab_mobile_subtitle``）；該語言沒有這個字串時只顯示標題。
* **卡片。** 群組框改畫成浮起的卡片、標題在上方；新頁面直接使用 ``Card``。
* **看得見的核取方塊與選項按鈕。** Fusion 以視窗色的深淺描邊，深色主題下幾乎看不見；
  現在改由程式依調色盤繪製（強調色填色、勾號、外圈與圓點），隨主題變化，不需要圖檔。
* **會縮小的控制項。** 分頁第一次顯示時會經過一次調整：下拉選單不再以最長項目決定寬度
  （Mobile 曾因一個指令名稱需要 1,464 px）、表單放不下時標籤移到欄位上方、長說明自動換行。

元件
----

位於 ``je_auto_control.gui.adaptive``：

``breakpoints``
    ``classify(width, previous)`` 回傳 ``WidthClass.COMPACT`` （800 px 以下）、
    ``MEDIUM`` 或 ``EXPANDED`` （1,200 px 起）。寬度須越過邊界 24 px 才會切回，
    在邊界附近調整大小不會閃動。不匯入 Qt。
``flow_layout.FlowLayout``
    放不下時換到下一行、而不撐寬頁面的列；最小寬度等於最寬的單一項目。
``responsive.ResponsiveBox``
    空間足夠時並排、低於指定寬度時上下堆疊。
``responsive.fit_to_width``
    上述的調整。工作區顯示每個分頁時都會執行；已調整過的控制項不會重複處理。
``surfaces``
    ``Card``、``PageHeader``、``EmptyState`` 與 ``retranslate_surfaces``。它們帶有
    ``role`` 屬性（例如 ``card``、``pageTitle``、``hint``），由主題樣式表指定外觀，樣式集中在 ``gui/theme.py``。
``style.AdaptiveStyle``
    繪製這兩種指示器的 Fusion 代理樣式，由 ``prepare_application`` 安裝。

標題、區段標題與提示文字的大小依內文字級計算（``type_scale_rules``），
**View → Text Size** 也會一併縮放它們。

寬度檢查
--------

``test/unit_test/headless/test_gui_page_widths.py`` 以視窗的方式開啟每個已註冊分頁並讀取最小寬度，
單位是視窗標籤字型的平均字元寬，使 Windows 與 Linux 字型適用同一個上限。
每頁最多 72 字元（10 pt Segoe UI 約 460 px）。目前仍有四個分頁超過，各自列出上限
（Script Builder、Flaky Tests、Audit Log、USB Sharing）；這份清單只減不增。
