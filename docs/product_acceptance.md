# 完整產品示範與本地驗收

這是實際產品流程，不是 `/?demo=hand` 的靜態介面範例。模型決策使用明示合成替身；資料由真 Python 計算，HTTP、PostgreSQL、S3、Node Worker、SDK、瀏覽器皆實際執行。不代表真 OpenRouter 模型能力或投放成效。

## 重現命令

依 README 安裝專案依賴及本地 PostgreSQL／MinIO 後執行：

```sh
uv run pytest tests/test_product_browser.py -q -s
```

測試自行建立全新本地 cluster 和 bucket，不讀取客戶 DB／雲端憑證；不需登入、模型 key 或付費 API。結束時僅停止自己建立的服務。終端顯示 `.runtime/product-e2e-*/` 留存目錄，含三格式下載、桌面／手機截圖、四題事件證據與測試服務日誌。生成資料為手算 fixture 的 CSV 檔，仍走正式上傳與計算管線，不將 fixture JSON 灌入結果 UI。

## 示範操作

1. 空歷史頁 → 上傳：建立 App／資料集，選用戶表及兩個事件檔，等待服務端大小與 checksum 核對。
2. 保存來源欄位映射與合成資料匯出說明 → 建立基礎分析；只收到 queued 不算報告完成。
3. Python Worker 從持久任務表領取並產生報告，從進度頁開啟雙欄工作區。右側呈現 D7 結果與限制。
4. 左側依序提出下列問題，每題等待該 Turn 完成後刷新；原 baseline 保持選取，右側不自動跳到新分支。
5. 點「查看結果」選取已完成分支，再下載 HTML／JSON／CSV。檔案 run/version 對應所選結果，原始 baseline 不被覆寫。

| 問題 | 必须觀察到的系統行為 |
|---|---|
| 改看前 3 小時 | 讀 baseline，建立 windows_hours=[3] 分支，由 Python 計算後引用結果 |
| 只看美國用戶 | 讀資料概況，依已映射 country 做分群；保留樣本分母與未知收益限制 |
| 這三個候選的人群重疊嗎 | 使用報告中實際候選 ID，讀既有 overlap 證據，不另產生計算分支 |
| 覆蓋率高一點 | 使用受 schema 約束的門檻網格建立探索分支；保存 hypothesis，不宣稱投放提升 |

資料庫另核對一個資料集、四個成功 Turn、三個分支與六類工具 journal。所有回答帶真報告引用，文字明示合成模型。圖表數值、候選表、鍵盤、取消／模型失敗／重試等完整補充驗收：

```sh
uv run pytest tests/test_run_browser.py tests/test_chat_browser.py tests/test_report_delivery.py -q -s
```

其中 report_delivery 在 API／Vite 停止後，以全新斷網 Chrome 重開下載 HTML；圖表有完整靜態表格替代。聊天測試另包含中文輸入法、長內容、不強制捲動、取消排隊及執行中 Turn、模型錯誤重試、無 key 仍可讀報告。

## 驗證邊界

PH38 證據見 `evidence/PH38.md`。本地流程通過不代表備份還原、百萬事件容量或正式部署演練已完成，這些分別由 PH39–PH41 驗收。真模型、雲端與客戶資料仍依 EXTERNAL_CHECKS.md 補驗。
