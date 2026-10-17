# Agent 中斷恢復與執行限制

Node Worker、Python Worker 分開執行。對話、工具意圖／結果、公開 SDK 訊息與 runtime 配置保存在 PostgreSQL；計算產物與已發布報告保存在持久物件儲存。不是逐 token 續傳，也不保證分散式 exactly-once。

## 正常執行

1. Node 領取 turn，取得 lease 與 fence；缺 OpenRouter 配置不領取工作。
2. 初始化固定 model ID、SDK 版本、prompt hash、步數上限及最初 deadline。同 turn 恢復不得更換配置。
3. SDK `prepareStep` 在每次模型請求前持久預留一步。已預留但中斷的步數仍算消耗，重啟不重置預算。
4. 工具先保存原 call ID／參數，再調用既有正式工具。計算工具的同 ID 重放對上既有分支或 job，不覆寫父報告。
5. 工具結果先提交，再交回 SDK。每步公開文字及工具配對合併為 checkpoint，保存用量；不保存私有 reasoning、provider metadata 或原始 log。
6. 最後答案經引用檢查後，使用有效 fence 原子發布訊息與 turn 完成狀態。

SDK 的觀察型 callback 例外不能當作執行閘門；步數預留使用 `prepareStep`，checkpoint 保存失敗另觸發 abort，防止下一個模型請求或最終假成功。

## 程序中斷後

替代 Node 等待既有 lease 真正過期後領取同 turn，fence 增加。載入最新完整公開 checkpoint，查全部工具紀錄；已完成工具讀回結果，尚未確定完成的工具使用原 ID 重放，透過正式工具查回原分支／job。補入 checkpoint 未包含的 call/result，重建可引用證據集合，不能重複配對。

最後完整 checkpoint 已是 stop、且沒有後續未完成工作時，直接驗引用並發布保存的答案，不再請求模型。中斷串流尚未提交的文字可能重新生成；這不是保證原字句逐 token 接續。

設定改變回報 `AGENT_RUNTIME_CONFIG_CHANGED`，不默默改模型或放寬上限。超過原 deadline／步數時不再發起新的模型請求。已完整保存的最終答案仍可恢復發布；背景計算成果及原報告不因此删除。

## 失敗的區別

- 模型失敗：Agent turn 失敗；baseline 與已發布子報告保持可讀。使用者可以在修復模型設定後明確重試。
- 計算失敗：子 run／job 失敗，不能產生假報告。模型可引用既有 baseline 解釋失敗，不把子計算成功當作前提。
- 不確定的 bridge／工具網路失敗：可能已提交副作用，不將它固化成「沒有執行」。保留原工具意圖與 ID，由 lease 恢復；仍受 turn 原有 attempt 上限約束。
- 取消／失效 fence：不能提交新工具結果或最終答案，既有資料與報告不移除。

## 大小與相容性

每 turn 最多 100 個工具意圖；參數32 KiB、單工具結果128 KiB；journal及step讀取回應256000 bytes。訊息超限明確拒絕，不偷偷截掉工具配對。只載入最新完整累積checkpoint，先前step保留索引／usage與DB原紀錄。

此恢復實作要求 migrations 到0017或以上。升級前先遵循備份說明；不得用重建DB或刪除舊turn解決相容性問題。沒有公開部署或付費API的隱含授權。

## 驗證入口

`npm run test --workspace agent`

`uv run pytest tests/test_agent_process_recovery.py tests/test_agent_journal.py tests/test_agent_steps.py tests/test_chat_browser.py -q`

程序故障測試使用真 Node／SDK、HTTP、PostgreSQL、S3相容儲存與Python Worker，模型是合成測試替身；在工具HTTP提交前／後與finish前對真Node執行SIGKILL。另有模型在子報告發布後失敗、真Python計算子程序失敗的獨立狀態檢查。真OpenRouter呼叫與雲端故障演練仍由EXTERNAL_CHECKS.md追蹤，不以本地結果宣稱已上線。
