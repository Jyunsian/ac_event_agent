# 有界探索（PH33 實作中）

Agent 仍由 Vercel AI SDK 管理迴圈；Python／PostgreSQL 只負責分析任務及業務限制，不另寫一個模型迴圈。

每個 turn 首次使用探索工具時建立不可變 budget：最多 4 個新 child、累計候選預留量為父 run 的 max_candidates×4、600 秒業務期限。這些是可調整前需記錄與重驗的工程預設，不是投放平台要求或成本保證。SDK 同時保留更嚴的預設 8 步／120 秒限制。不同限制取先到達者；目前沒有以金額計算的費用上限。

建立 branch 與記錄 round 同交易，受 conversation/turn lock 序列化。同 tool call 重送回原 child，不重複扣額；失敗、取消不返還預留額。歷史 round 在 migration 0012 回填，0013 的未知歷史假設保持 null；非空升級已驗，見 evidence/PH33.md。

- get_exploration_budget：返回持久預算、已用輪數／預留量、deadline、凍結狀態及既有 child 狀態，這不是計算結論。
- rerun_analysis／analyze_segment：受業務預算控制，既有參數邊界不變。
- evaluate_analysis：返回真進度或報告引用，不消耗新的 round。
- finalize_candidates：指定本 turn 已完成非分群 child 的既有候選 IDs（可空選），保存精確 report artifact/version/hash，關閉本 turn 的新計算。冪等重送同選擇可讀回；不同選擇不能覆寫凍結紀錄。

凍結只是探索選擇結束，所有後續分支仍為 exploratory，不代表獨立驗證通過。新的 turn 有新預算，但只能建立新 run；舊報告／候選規格仍不可變，跨對話資料揭露紀錄不會重設。到限後已完成產物保留，可透過永久 run URL 閱讀。

模型只收到 allowlist 中的安全錯誤碼，例如 EXPLORATION_FINALIZED、EXPLORATION_ROUND_LIMIT、EXPLORATION_CANDIDATE_LIMIT、EXPLORATION_TIME_LIMIT；未允許的原始錯誤不外傳。沒有額外 paid API 授權時不驗真 OpenRouter，X01 保持 pending_external。

rerun_analysis 可提供簡短公開 hypothesis 與 based_on 引用；後端只接受本 turn 已交付的 evidence_id，與 round 同交易保存。未提供摘要保持 null，禁止要求或保存模型私有思考鏈。API 預算查詢同時返回這些 round 註記。

已有真 SDK 兩輪計算、凍結、假設記錄、非空升級及到限後保留部分產物的整合證據；Phase 狀態以 evidence/PH33.md／PHASE_STATUS.md 為準。
