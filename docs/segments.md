# 分群診斷

`analyze_segment({field,value})` 支援 country、platform、acquisition_source 的精確單值篩選。產生持久 followup child；使用 `evaluate_analysis({child_run_id})` 等待結果。後續 turn 選中 child 時，`get_baseline_report` 可讀既有分群，不必重算。

分群沿用全體資料的成熟定義、原 split_id、父報告固定候選與資料能力，不在子群重新搜尋／切分／驗證。父報告不覆寫。分群子報告的 summary.segment 保存選中、未成熟、欄位未知人數，以及探索／holdout 分開的分母與收益。低於 config.min_group_users 時只保留人數，不顯示收益或候選 metrics；缺欄位或行為能力明示原因，不當成零。

右側「概覽／候選事件／圖表」頁提供分群分母收益表與固定候選的診斷明細；本階段沒有為小樣本製造趨勢圖。HTML 匯出同樣顯示來源、分母及限制。分群 CSV 使用獨立 schema：record_type（cohort/candidate/limitation）、segment_field/value、split、candidate_id、users、revenue_usd、arpu_usd、evidence_status、reasons、metrics_json；缺值為空欄或 JSON null。不是 baseline CSV 同一欄位格式。

所有結果為 exploratory；不宣稱分群後取得新的獨立驗證。`rerun_analysis` 是全體資料的新條件搜尋，會移除 segment；若要另一子群，使用 analyze_segment。首次 baseline API 不接受 segment。

本地證據見 evidence/PH32.md；SDK 測試模型明示 synthetic，真 OpenRouter 待 X01。
