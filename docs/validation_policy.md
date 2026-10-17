# 驗證揭露與獨立資格

PH29 後端規則；不是模型 prompt 約定，也不是投放因果驗證。

## 邊界

公開的 report JSON/HTML/CSV、run/view 結論摘要和 Agent 工具讀取，均在回傳前提交 `validation_exposures`。內部 readiness 檢查不記揭露。dataset＋split 保留首次紀錄，換對話或新建 run 不清除。提交後客戶斷線仍採「可能已揭露」，不能因此重新視為未看過。

新 run 在正規化後登錄 canonical 用戶；頻次為零、未成熟用戶也參與重疊檢查。候選和判定規則凍結後、holdout 計算前，由 Python 後端預約資格。預約綁定 run/dataset/split/frozen hash，重放不能換候選或改判定規則。

下列任一情況只輸出 exploratory：followup、同 dataset 已揭露、與任何已揭露資料有 canonical 用戶重疊、舊揭露資料的人口未知。即使重複上傳產生新 dataset 或另建 project，canonical [app_id,user_id] 相同仍被抓到；不能把新 UUID 當新獨立資料。

無重疊且尚未揭露只表示「有資格驗證」，不是歷史通過。樣本量、收益缺失、信賴區間等統計判定仍由既有 validation 執行。原 baseline 報告不回写。

## 並發與恢復

揭露和資格預約共用 PostgreSQL transaction advisory lock。先取得資格的已凍結候選可重放既有決策；先揭露的資料不能被後來的新候選取得獨立標籤。預約檢查 Worker lease/fence，發布仍走既有 JobQueue fence。

DB trigger 禁止改寫人口、預約、揭露；ineligible run 禁止升級 evidence_status，也不能改 reserved split。API 不接受使用者指定 eligible。

migration0009 之前的已揭露資料，從已提交 normalized checkpoint 及 checksum 驗證後的 users Parquet 補人口索引。不一致 checksum 失敗；缺 provenance 維持 EXPOSED_POPULATION_UNKNOWN，不能假設無重疊。相關檔案不會被覆寫或刪除。

## 保存與限制

內部用戶集合索引以 canonical [app_id,user_id] 的 SHA256 保存，每2000列寫入。這是資料比對用的假名識別，**不是匿名化**；同樣需要內部網路、DB備份與存取保護，不提供給模型或報告。產品仍不做登入或會員系統。

未知或錯誤的來源 ID 定義不能靠演算法補齊，真客戶資料合約仍屬 X05。單一政策鎖及索引資源需在 PH40 容量測試量測，不由小合成資料推估效能。

重現：`uv run pytest tests/test_validation_exposure.py tests/test_validation_policy.py -q`；真 PG/S3/Worker、明示合成資料。更多回歸與限制見 evidence/PH29.md。
