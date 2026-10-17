# L02 — passed

最終狀態：passed。2026-09-10 首頁／示範回歸 session38911 exit0，`.runtime/language-home-001/checks.json`：1440／1280／768／390 無頁面溢出、桌面分欄／拖曳／刷新、手機草稿切換、鍵盤 tabs／詳情及無資料入口均通過。短文案不需要捲動時不強行要求 scrollTop>0，有溢出仍斷言獨立捲动。保留固定輸入框／tabs 檢查。桌面與手機截圖已檢视。合併下方真上傳／進度測試和共用語言單測作 L02 門檻；L03 可開始。完整產品與 Agent 尚待 L03–L05，不因本階段通過就關閉 Goal。

2026-09-10：開始建立共用顯示層 web/src/language.ts，已接進度頁的處理階段、錯誤與 UTC 日期顯示。技術識別碼／執行次數收進 details，未修改儲存狀態、任務或計算。未知錯誤一律安全通用文字，不直接回顯原始服務內容。

驗證：`node --test tests/language.test.mjs` exit0，2 passed；`npm run typecheck --workspace web` exit0。單測覆蓋未知錯誤不洩漏原文、逾時、錯檔提示、檔案大小／未知值、UTC 明示與階段映射。

尚待：上傳欄位與時間操作、示例隔離、進度頁剩餘重試文案、歷史與首頁、全錯誤狀態。未執行浏览器回歸，不宣稱 L02 通過。L03–L05 未開始。

## 後續實作（取代上述實作待辦狀態，驗收仍未完成）

- 新增 field-language.ts，完整覆蓋 schema 的 user／event 欄位中文名稱與用途；輸入保留 data-field 與原始欄名 placeholder，可精確對應來源。缺收益不補零。
- 上傳頁改用途先行、中文欄位與資料時間說明；datetime-local 明示 UTC，值只添加／移除 Z，不經瀏覽器時區轉換。示範填入按鈕限 demo=hand，建立 dataset 後保留示範參數。不是以勾選 synthetic 即開放任意範例設定。
- 檔案大小易讀化、續傳錯誤安全文字、封存提示區分換資料與改分析條件。未改 multipart／fingerprint／原始來源保存。
- 進度頁剩餘重試與報告未就緒訊息改白話；歷史不再展示 UUID／持久資料庫說明；首頁左欄移除過時開發狀態。
- `node --test tests/language.test.mjs` exit0，3 passed（新增所有 schema 欄位涵蓋、UTC 秒／毫秒／空值 roundtrip、不接受偏移值作 UTC）。`npm run typecheck --workspace web` exit0。

下一步：更新 scripts/upload_browser_qa.cjs 既有 locator 與訊息斷言（目前仍引用舊中文／錯誤碼／手算按鈕）；不能刪除錯檔、缺part、A→B→A映射、刷新、必填與封存等功能驗收。datetime-local 的無效輸入須測瀏覽器阻止提交及有效格式但違反時間合約的 API 拒絕。繼續掃上傳剩餘建立／儲存／收益時序文字及示例右欄，再跑真上傳／進度回歸。尚未開始 L03，Goal 保持 active。

## 2026-09-10 瀏覽器回歸

已更新上傳與進度測試 locator／友善錯誤斷言，保留 multipart 真傳送、缺段、同大小錯檔、續傳、A→B→A、必填、刷新與真 Worker 完成／歷史恢復／失敗重試等原始條件。新測試確認正式入口無範例填入按鈕，示範模式有按鈕。

首次 session20115 exit1：datetime-local fill 含零秒被瀏覽器正規化，改測分鐘格式，保存函式補零秒、保留已有小數秒。第二次 session51234 exit1：先前没有截止晚於匯出時間的檢查；新增頁面儲存前日期合法性與順序檢查（不是 API 新增規則）。保留空白 required 檢查，不刪原時間驗收目的。

`uv run pytest tests/test_upload_browser.py tests/test_run_browser.py -q -s` session87546 exit0，2 passed /32.99s，2既有 deprecation warnings。真 PG／MinIO／API／Python／Chrome，非 mock 成功；產物 `.runtime/upload-ui-tvzwcz8j/visual`、`.runtime/run-ui-ai3wmtdg/visual`。`node --test tests/language.test.mjs` 3passed，web typecheck exit0。

同步完成上傳剩餘建立／儲存／開始分析、收益資料時序文案、示範右側過時狀態與英文統計字眼的改寫。L02 仍待最後首頁／示範視覺檢查與全站剩餘字詞掃描，不提前開始 L03。沒有模型付費測試或雲端操作。
