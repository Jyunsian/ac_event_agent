# 表格標籤修正

2026-09-17：正式 Web 與 mock 欄名改「達標時間」「Holdout 驗證」。時間列使用平均／50%／90%，驗證狀態縮為收入較高：已驗證／未確認、資料不足、尚未驗證、僅供探索。mock 保留示意標記。移除重複起算說明；保留達標母體與起算點。只修改呈現，統計通過標準不變。

驗證：web build（含 typecheck）、26 項前端測試；沿用正式產物 fixture 與 mock 桌面／手機互動檢查。證據 .runtime/v4-table-labels/production、/tmp/v4-label-{build,tests}.log。更新既有臨時預覽，無雲端部署。
