# 達標時間與 Holdout 白話文案

2026-09-17 已完成。Web／mock 時間欄改「多久達成條件」，新增平均，保留一半與九成達標時間；註明截至目前已達標玩家及安裝／首次開啟起算。計算新增 delay_seconds.mean 與 known_users/unknown_users，只納入可靠首次時間；snapshot 不推算。CSV 與候選摘要新增 mean_seconds，Agent 聚合隨 delay_seconds 傳遞。舊報告無平均值保持未知，不推估或改寫。

Holdout 改「換一批玩家，結果還成立嗎？」；有支持、未確認、資料不足、未驗證、探索各自用白話呈現，既有統計通過條件不變。Mock 時間數值明示假設，不冒充真結果。

驗證：web build/typecheck 通過；前端 26 項；Python metrics/rolling/review fixes 16 項通過（2 既有警告）。新增手算平均 3600／45000 秒及 snapshot null 斷言。正式頁以舊真產物驗證相容、桌面手機、三群、六時點、詳情及頁籤；mock 桌面手機三群六時點互動通過。證據 .runtime/v4-time-copy/production、/tmp/v4-time-{web,python,build}.log。未重新驗收容量或部署。
