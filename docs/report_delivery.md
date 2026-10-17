# 客戶報告交付格式

選定已發布的 baseline 或分支 run，再匯出 HTML、JSON、CSV。三種格式必須對應同一 run／報告版本，不以目前對話最後一則文字推定選取版本。原始報告不可覆寫；新的計算建立新 run。

HTML 是人類閱讀版本，JSON 是完整結構化證據，CSV 是表格交換格式。Agent 對話紀錄不會自動取代報告的計算數字或成為已驗證的敘述。

## CSV 2.0

新增 `csv_schema_version=2.0`。候選數值欄位保留，新增 `record_type` 與每列的交付中繼資料：

- run_id、dataset_id、parent_run_id：所選計算與來源關係。
- synthetic、analysis_status、target：合成資料標記、分析狀態與D7目標。
- data_scope_json：來源App、用戶／事件數、完整截止、安裝日範圍及split ID；未知保留null，不補零。分群分母另看分群欄位，不混成來源總量。
- pipeline_version：計算程式指紋。
- event_spec_json：完整事件名、起點、窗口端點、條件、首次觸發、每人回傳上限、逾期行為、依賴與收益可用時間。
- limitations_json：報告限制、原因及驗證資格。

一般候選列的record_type為candidate；無候選時仍有一列limitation，保留資料身份與失敗／不足原因，不能把它算成一個推薦。分群CSV保留cohort／candidate／limitation三類，candidate列帶原始候選完整規格，分群欄位只描述診斷人群，不代表已驗證的新事件。

讀取端應按欄名處理，不硬編碼欄位位置或把每列都當候選。JSON字串欄位需用JSON parser解析；所有文字欄位沿用試算表公式注入防護。空收益儲存格是未知，不是零。

舊的已發布CSV不重新產生或覆寫，因此沒有csv_schema_version的檔案仍可能是舊格式；交付新報告前應確認實際格式版本。

## 來源與隱私

報告保存來源checksum以供追溯，不公開內部物件儲存key或本地路徑。用戶ID及逐用戶log不是客戶報告內容；資料範圍與分布為聚合資料。匯出前仍應核對輸入維度與App命名是否含非預期敏感內容，不能把單一工作區當作多租戶權限隔離。

分群HTML含完整原始事件規格，三格式都有來源範圍。歷史相關性不代表投放提升；低樣本、未知收益和探索性分支保留限制，不因匯出變成「驗證通過」。

## 驗收狀態

PH37 本地交付驗收已通過，實測證據見 evidence/PH37.md。執行 `uv run pytest tests/test_report_delivery.py -q -s`，以真本地服務與合成來源產生基礎、普通及分群分支，經 Chrome 下載後停止 API／Vite，再離線重開 HTML。靜態表格逐列對照 JSON、三格式識別標記掃描與父報告不可變性均納入測試。這不代表真客戶資料、真模型或雲端部署已驗證。
