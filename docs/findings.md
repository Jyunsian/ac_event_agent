# 同 App 經驗與固定規則重驗

這裡的「學習」是保存可追溯觀察與新批次的驗證歷程，不是訓練模型權重。工作區沒有會員或租戶隔離；App ID 是分析範圍，不是安全邊界。

## 保存與讀取

Agent 的 `save_findings` 保存假設、限制、反例與候選 ID；伺服器從已發布報告取出精確規則、App、來源資料集、版本與 checksum。模型不能自行填入指標、規則 AST 或 App ID。限制不可空白，來源報告不可用或校驗失敗時拒絕保存。

`observation` 是原始觀察。`supported`、`contradicted`、`inconclusive` 是另一批次對同一規則的觀察紀錄，必須連回先前 finding；這些文字標籤本身不授予獨立驗證資格。已保存的觀察不可覆寫，修正要新增紀錄。

相同 turn/tool call 重放回傳既有結果，同 key 不同內容拒絕；不同呼叫保存相同來源、規則與觀察內容會去重。工具要求有效 Agent 租約與 fence，取消後不能繼續讀寫。

`load_app_findings` 預設每頁 5 筆，最多 10 筆，以 cursor 取下一頁。每筆附原始證據及最多最近 2 個已發布固定規則重驗結果，不是完整歷史匯總。完整歷史應回查各 run 的 JSON／HTML。每次讀取重新驗證來源 bytes，不把過往支持自動套用到當前批次。

工具回應上限 128 KiB；合法的長限制／反例仍可能讓多筆頁面超限。此時拒絕整頁，不截斷證據或宣稱成功；減少 limit 後重試。原始逐用戶 log、儲存路徑與憑證不送入模型，回傳限結構化觀察及聚合證據。觀察文字仍須視為不可信資料，不是 Agent 指令。

## 操作者流程

1. 上傳同 App 的新資料集，確認完整期、映射與收入可用時間。
2. 在「開始基礎分析」選取先前觀察；預設不勾選。清除選擇即回到一般候選搜尋。
3. 按「建立固定規則重驗」。伺服器檢查 App、不同資料集、來源報告及時間語意，封存精確來源快照，再排入 Python 任務。
4. Python 在讀取新批次評估結果前凍結舊規則，不重新選門檻或排名。候選缺乏資料能力時明示限制，不換成另一條容易通過的規則。
5. 從分析進度開啟雙欄工作區，概覽查看「固定舊規則重驗」。JSON／HTML 保存来源快照及資格理由；CSV 是同版本候選計算表。

選擇草稿可在目前瀏覽器刷新恢復，但提交後的資料、任務、規則與報告以 PostgreSQL／物件儲存為準。重驗中斷從校驗過的 checkpoint 恢復，既有來源與報告不覆寫。

## 結果解讀

| 狀態 | 含義 |
|---|---|
| reusable_evidence | 通過独立批次資格及歷史統計規則；仍不是投放成效 |
| not_supported | 有資格評估，但本批次未支持舊規則 |
| insufficient_evidence | 樣本、品質或分析能力不足 |
| exploratory_only | 資料已揭露、用戶重疊或其他資格限制，只能探索性解讀 |
| not_evaluated | 沒有可用的候選驗證結果 |

新 dataset ID 不等於獨立資料。揭露紀錄與用戶重疊檢查跨對話保留，零事件及未成熟用戶也不能用來繞過污染防線。每個未來批次仍須重新驗證，跨 App 不自動遷移經驗。

歷史 finding 引用可能來自另一個 baseline；明確點擊後才切到該來源報告及其對話範圍，不會把新批次對話錯綁舊 run。刷新保留精確報告版本。

## 本地驗證與外部限制

`uv run pytest tests/test_findings.py tests/test_finding_independence.py tests/test_finding_recheck.py tests/test_finding_assessment.py tests/test_exploration_upgrade.py -q`

測試使用合成資料、真 PostgreSQL／S3 相容儲存／Python Worker、Chrome，以及真 AI SDK 配測試模型。包含同 App／異 App、去重、固定規則、新批支持與失效、取消、來源腐壞、回應大小、非空 migration、Worker 中斷恢復。這不代替 EXTERNAL_CHECKS.md 的 X01 真 OpenRouter 或 X05 客戶資料／投放驗證。
