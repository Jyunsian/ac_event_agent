# L03 — passed

## 最終階段核對

session89948 `uv run pytest tests/test_finding_recheck.py tests/test_finding_assessment.py tests/test_findings.py tests/test_run_browser.py -q -s` exit0，9passed40.12s。重驗 browser 更新為目前按鈕及來源詳情定位，保留選擇刷新、唯一提交、原規則、匯出、跨批引用與唯讀斷言；圖表以真滑鼠懸停驗證分母及100位人群提示。此前21880採到舊腳本按鈕而失敗（7passed1failed）；1030因img選到div和SVG兩個元素失敗，已縮到繪圖容器後回歸。

證據：`.runtime/finding-selector-o4see34s/visual`（已目視重驗手機）、`.runtime/finding-ui-seiz6unj`、`.runtime/run-ui-wx0wpg6t/visual/heatmap-tooltip.png`。結合本檔的版本／報告／分群／離線精確值／錯誤與數值邊界回歸，L03範圍的概覽、真條件名稱、單位分母、版本摘要、固定規則重驗、HTML與JSON/CSV一致性已通過本地門檻。用語前後對照見 docs/LANGUAGE_BEFORE_AFTER.md。原始報告未覆寫；L04 Agent 與 L05 全站綜合回歸不在此完成宣告內。

## 續作：分群逐事件比較

前端與 HTML 新增「分群事件比較」，依實際 event_specs 提供條件名稱，分開顯示 exploration／holdout 的符合與比較人數、比例、收益、達標時間與限制。原始明細保留。舊報告未附設定時明示缺少，不猜名稱；decoder 新增分群 metrics 結構與事件設定 ID 綁定檢查，避免錯配來源。重驗概覽加入可用候選的真條件名稱，不能產生完整比較時明示。

`npm run typecheck --workspace web` exit0；`npm run test:web-model` 10passed（新增錯配設定／不完整metrics／舊報告相容測試）。session31668 離線交付2passed30.01s。最後 session91143 `uv run pytest tests/test_report_delivery.py -q -s` 2passed32.36s，新增真Web分群逐列身份／數值／中文條件／桌面手機不溢出檢查與HTML逐列精確數值核對；原報告 immutable、CSV設定、offline依賴及隱私測試保留。證據 `.runtime/report-delivery-7dq4adwk`、`.runtime/report-delivery-nfa819rj`。目視後者 child `6ff6b884-9116-4fdf-8c14-e87612868086/segment-web-390.png`。

新增 docs/LANGUAGE_BEFORE_AFTER.md 記錄已實作改寫與不能改變的語意，不將 Agent 待做內容冒充完成。L03 仍需重驗代表流程、tooltip 互動與最終逐項審核；L04尚未开始。

## 續作：瀏覽器、離線報告與顯示層

- 更新 run/offline/chart-fixture/accessibility 測試 locator，原候選排序、精確 spec、逐點數值、人數分母、未知值、錯誤身份／checksum、版本、唯讀與持久性斷言全部保留。候選選取改驗證 `data-selected-candidate`；圖表精確值用 `data-value`，另驗證千分位與美元可讀文字；長名稱邊界 fixture 明確提供 names。
- 失敗紀錄：session88061 因 a11y 測試仍期待候選 hash 出現在正文失敗；session15029 核心流程已通過，但 chart fixture 仍期待舊「可繪」與未格式化數字失敗。已更新為新文案／精確属性驗證，沒有刪除功能斷言。
- session22993 `tests/test_report_delivery.py` 2passed29.90s；session17894 `tests/test_run_browser.py tests/test_report_delivery.py` 3passed50.50s；最後 session25124 `uv run pytest tests/test_run_browser.py tests/test_report_delivery.py tests/test_conversations.py -q -s` exit0，5passed58.87s，兩項既有棄用警告。最新證據：`.runtime/run-ui-k2hz5d_2/visual`、`.runtime/report-delivery-26te6u9d`、`.runtime/report-delivery-pd5qn6aa`、`.runtime/version-ui-z_4r44sv`。
- 已目視前一輪 `.runtime/run-ui-g9skmimy/visual/report-charts.png`、`report-heatmap-mobile.png`、`.runtime/report-delivery-z8jvm9_j/4809a788-33db-4866-be9c-afcf8648714e/offline-mobile.png`。雙欄與手機不整頁橫溢，寬表格有獨立捲動。左側舊 Agent 文案與候選 hash 尚待 L04，不冒充已完成。
- HTML：移除主內容 hash／內部人群名稱，候選與敏感度使用真條件名稱，規格與完整追溯收合；保留來源與所有 data-value。分群前端修正 `holdout` 對應中文名稱（先前錯用 validation key），收益總額／未滿7天明示。品質頁增加每種能力與限制的白話說明，不只丟 JSON；匯出提供三種格式用途；圖表 tooltip 增單位與分母、render error 下沉。
- 最新 `npm run typecheck --workspace web` exit0。`npm run test:web-model` 9passed，語言測試已納入日常 check。一次錯用不存在的 tsx runner，未安裝新套件；改用專案現有 Node 原生 TS 執行成功。
- 最後又補 HTML UTC 可讀日期與已知限制句子的白話映射，未知限制原文保留，未改 JSON/CSV；`uv run pytest tests/test_report_language.py tests/test_report.py -q` 15passed0.06s。此最後顯示修改仍需離線瀏覽器回歸。
- L03 尚未關閉：分群逐候選結果仍在原始詳情，需要可讀呈現；重驗條件需核對可讀識別與來源；tooltip 需針對互動驗證；最後文案／可讀數字與前後對照仍需完成，再接 L04。

續作驗證：先收取 session81365，結果 3passed、1failed（version_browser_qa 仍定位舊概覽標題，非版本資料遺失）。更新為新標題與 href 中的 run 定位，不再依賴主畫面顯示 UUID；保留唯讀、版本、排序、圖表及刷新斷言。`uv run pytest tests/test_report.py tests/test_report_language.py tests/test_conversations.py -q` session34736 exit0，16passed19.32s，兩項既有棄用警告。`npm run typecheck --workspace web` exit0。

本輪補完 HTML 未滿7天標籤、分析狀態與分群来源下沉、敏感度條件從 family 生成中文規則、移除建議正文 holdout。圖表為未入選的搜尋候選補真條件名稱，完整性錯誤改為白話主訊息＋詳情。PHASE_STATUS 同步 L02passed／L03in_progress。仍需完整 run_browser／離線匯出回歸、HTML 剩餘專有名詞與視覺檢查；本輪16項通過不代表 L03 完成，更不代表 Agent 已改造。

2026-09-10。前置 L02 已通過。已建立 candidate-language.ts：從實際 predicate／origin／window 產生名稱，支援原子次數／收益／有效時間、AND／OR 與不重疊順序的間隔與重複次數。測試覆蓋布林差異、起點、廣告格式、小額與順序限制。已接入候選表與詳情；不改計算或 event_spec。

報告概覽先回答是否有歷史支持、限制及下一步；不得直接聲稱投放有效。新增 contracts/reason_labels.json 與 report-language.ts 做限制白話化、未知代碼安全顯示、單位與小額格式。ID／hash／事件 JSON 收入詳情，精確 data-value 與原始值 title 保留。資料品質日期明示 UTC；分群頁逐步中文化。

已執行 web typecheck exit0、language 單測 4passed（新增數值與限制測試後待再次跑）。仍未完成：HTML 客戶報告、圖表與分母提示、版本條件摘要、舊觀察、完整限制原因覆蓋、數值一致性與瀏覽器回歸。舊 run_browser_qa 中概覽／品質標題需要更新 locator，功能斷言不可減少。L03 不可提前 passed，L04 未開始。

本機 Vite 本輪重新啟動於5174，session35594；只為首頁預覽，預設代理並非已驗證的真模型完整工作區，不能當作最终交付入口。無金鑰新增或付費測試。

續作：report-language 數值／限制單測已跑，現在5 passed，web typecheck exit0。HTML 已开始接共享 reason_labels（目前函式已載入，但各輸出點尚需套用）、中文條件、收益微小值與概覽下一步。新增 Python 顯示層 test_report_language，2passed；仍需完整 HTML 與既有報告合約回歸，不能以這兩個單測視為完整交付。HTML／圖表／版本／重驗後續改造仍未完成。

圖表續作：問題式標題、讀圖說明、中文座標、比例／美元／小時，資料表保留 data-value 與原值 title；來源技術詳情收合。候選 names 從真 event_spec 提供，未知名稱目前安全回退（搜尋未入選候選尚需補名稱）。前後不同圖人群仍明示。版本 API 只增加 config 中 windows_hours／segment／thresholds，不返回數值或排計算；前端显示条件與UTC時間。finding selector 改說明「搜尋新事件」與「檢查先前條件」差別及 outcome 中文。

`uv run pytest tests/test_run_views.py -q` session62821 exit0，4passed7.01s；web typecheck exit0。branch/conversation 精確回歸另在执行（需取得結果），尚未跑新圖表 browser 數值回歸。scripts/run_browser_qa.cjs 的舊標題与raw文字數值比對需更新為新名稱＋data-value精確斷言，保留所有圖表數值比對與分母測試。Goal仍active。
