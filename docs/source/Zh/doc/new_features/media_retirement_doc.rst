媒體 producer 清理
===================

音訊、錄影與 LAN 廣告會提供不可變的清理狀態，並在清理待完成或結果不確定時拋出
``MediaRetirementError``。錯誤保留原始 owner，並繼承 ``AutoControlException``
與 ``RuntimeError``。資源關閉與輸出完成各自記錄確認結果。

錄影 flush 只嘗試一次；PyAV 或 sounddevice 關閉結果不確定時，不會透過重播呼叫
宣稱成功。Zeroconf close 可在原始 owner 上重試。取消與中斷訊號維持原始身分；
若建構期間清理失敗，可透過 ``interrupted_retirement_owners(error)`` 取得保留的 owner。

HostBrowser 拒絕晚到發布，保留已進入的回呼，並在一次取消要求後觀察原始執行緒。
Zeroconf close 可重試；建構取得資源失敗仍維持不確定。單次瀏覽中斷時，若清理也失敗，
會保留原始中斷訊號並附上資源 owner。

MultiViewerHost 的 ``create_owned_session_offer()`` 回傳 SDP 與原始 session 清理物件。
排入背景工作前，可用 ``session_retirement(id)`` 取得既有連線的清理物件；
即使 ID 重用，重試也不會停止新的連線或畫面來源。既有 tuple API 保持相容。
GUI 斷線與丟棄 offer 路徑仍須接入此所有權。

Host／viewer peer 會接收建構失敗的清理 owner，並透過 ``media_failures`` 提供快取的
不可變結果。失敗的子資源不能被覆寫；即時停用會觀測原 task 的實際完成，其他媒體與
peer 關閉仍可獨立進行。麥克風啟動佔用中的 slot 會回報待完成，不會卡住 bridge loop
等待鎖。延後執行的 detach 與重新協商均綁定原 peer。

此 producer 單元尚未完成應用程式 caretaker、GUI 儲存成功提示、GUI 丟棄路徑，
以及 HostBrowser 對話框所有權整合。原生驗收仍待完成；本單元使用注入的資源驗證。
