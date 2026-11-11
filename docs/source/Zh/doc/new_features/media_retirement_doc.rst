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

此 producer 單元尚未完成應用程式 caretaker、GUI 儲存成功提示、peer 替換及丟棄路徑，
以及 HostBrowser 對話框所有權整合。原生驗收仍待完成；本單元使用注入的資源驗證。
