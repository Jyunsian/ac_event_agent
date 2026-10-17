# 發布前逐項審核（PH42 本地通過）

> Candidate V3 更新（2026-09-11）：CG01–CG05 passed；CG06 固定 100k／20k／2k 真服務容量通過，但最終 source 的完整回歸依使用者要求收尾而停止，狀態為 `closed_partial`。本頁既有 PH42／V2 歷史簽核不自動升格為 V3 發布簽核；詳見 `evidence/CG06.md`。

最終簽核見evidence/PH42.md頂端Gate：本地通過，外部仍待驗。原始需求以PRD／TECH_PLAN／IMPLEMENTATION_PLAN為準；本表把現況、具體assert與執行證據連起來。下方早期審核段落的待審項已由後续「剩餘後端範圍與運維核對」及PH42最終Gate結案，歷史Phase的「尚未實作」不代表現況。

## 已核對：合約、持久性與分析

| Phase／要求 | 現行證據與判斷 |
|---|---|
| PH01 合法／非法輸入、窗口、AST、預算 | contracts/schema.json、defaults.json與22個examples；PH42執行check.py exit0。範圍僅合約，不據此宣稱計算正确。 |
| PH02 可安裝／build、无key、不假成功 | PH41三個production images從鎖檔安裝／build，正式入口全啟動；無key Python baseline可出報告。README補上獨立Worker，乾淨環境常駐流程仍需補驗。 |
| PH03 獨立合成真值／可重現／不可覆寫 | tests/test_fixtures.py實際比對schema、6users／17events／16unique、無事件u2、同seed全部file hashes；PH42 27-test批次通過。PH40新SQLite參考對四批既有truth逐欄相同。 |
| PH04 真PG migration／重啟／不可變／回滾 | tests/test_database.py六項真PG assert，目前head0017、資料與run config保持、跨dataset parent與artifact拒絕、半交易無run/job；PH42 27-test批次通過。 |
| PH05 真S3重啟／多版本／checksum／錯誤 | tests/test_storage.py、test_storage_contract.py真MinIO寫讀／重啟／不可覆寫／checksum／錯誤分類；PH42 27-test批次通過；PH41 restore211objects。AWS仍X02。 |
| PH06 競爭租約／kill／取消／重試 | PH41 Worker＋health11tests通過，PH42 test_jobs真PG配合27-test批次再次通過；PH39故障與PH41整套容器持久性補強，不以SDK替身代替queue。 |
| PH07 真multipart／續傳／封存／上限 | PH40末次upload_api＋Worker12tests；PH41正式Nginx／API／瀏覽器真上傳及不可變父報告。錯part／hash／fingerprint／未完成封存負例在PH07 test_upload_api與multipart，後续UI證據另審。 |
| PH08 CSV／Parquet／去重／非法列／原始保存 | test_ingest現行8項含等價原生型別、跨檔去重、衝突隔離、來源hash不變、15萬rowgroups及manifest最後發布；PH42 92-test批次通過。 |
| PH09 品質／能力／零用戶／checksum API | test_quality現行涵蓋收益缺值與負修正阻擋、Session只停相關能力、unknown timing停收益觸發、分布省略分母；PH42 92-test批次通過。品質API真產物讀回有PH09／17及PH41端到端證據。 |
| PH10 D7／成熟／零事件／日期切分 | 已讀targets.py實際LEFT JOIN及[install,168h) SQL、成熟截止、null規則與只依安裝日切分；test_targets逐人獨立真值、holdout收益擾動、日批次不拆／未成熟不補零，PH42通過。 |
| PH11 小時／天級特徵／延遲／未來事件 | test_features的1/3/6/24/72h、available_at7h不回填6h、session_end有效時間、unknown/null、未完整窗口、來源／版本hash與未來事件不改過去；PH42通過。 |
| PH12 atom／AND／OR／首次觸發 | test_predicates四種聚合、AND較晚／OR較早、右端排除、非法AST與負修正拒絕；PH42通過，不將序列當頻次。 |
| PH13 順序／gap／重複／不重用 | test_sequences獨立正反序、同時可靠source_sequence、event_id不可捏造順序、non-overlap及未來不改首次觸發；PH42通過。 |
| PH14 搜尋上限／穩定ID／隔離 | 已讀exploration.py：先SEMI JOIN探索用戶建立實體scope，再算品質特徵。test_search改holdout收入、缺收入、缺Session都不改候選／門檻／排名；cap5保留5窗口、預设2000與剪枝計數；PH42通過。 |
| PH15 凍結／統計／未知分母／非因果 | tests/metrics、freeze、finalists、validation涵蓋手算ARPU／coverage、paired hit/all bootstrap、兩日足樣本真Parquet正例、不足／反向／篡改反例；PH42通過。bootstrap區間是描述性，非多重校正或投放效果。 |
| PH16 overlap／門檻／觸發後／landmark | 已讀test_diagnostics逐值assert：intersection1/union4、Jaccard.25、雙向分母、空集合null、count1/3/5/20 coverage .8/.2/.2/0、排除觸發當筆／同時刻、landmark右端與缺收益null；PH42通過。 |
| PH17 baseline／背景／checkpoint恢復 | 現行pipeline.py讀sealed資料與server limits、stage runner、source/config/code/contracts指紋；PH40四批完整13階段、PH41正式容器端到端，PH39故障；中途kill／無半發布由test_pipeline驗明，近期資源改動回歸見PH40。 |
| PH18 可讀報告／三格式／安全／原子發布 | 已讀test_report與test_report_api：診斷也有limitation列、原始object key不外洩、8類CSV公式、HTML轉義、壞來源／renderer failure無manifest、錯report hash不回content；PH42通過。PH37離線與PH41六份報告／恢復hash補強。 |

## 已核對：介面與 Agent 接入

PH19–PH28原始證據已完整閱讀；已讀accessibility_qa、chat_browser_qa實際assert與test_run_browser真服務控制方式，核對run_browser_qa三圖逐列來源、分母、報告錯身份與503保留舊內容，並讀正式agent/runtime.ts的SDK與provider接入。模型替身不冒充OpenRouter真驗。

| Phase／要求 | 現行證據與判斷 |
|---|---|
| PH19 双欄／可調／獨立捲動 | PH41正式image桌面及手機已目視；PH42真run browser再驗鍵盤320–480、固定composer／tabs與窄屏選取，原PH19獨立scroll及pointer對照保留。沒有第三常駐欄或登入。 |
| PH20 真上傳／錯誤／續傳 | PH42 test_upload_browser真Chrome／PG／MinIO：錯檔、缺part、刷新重選、映射A→B→A、成功封存，exit0；`.runtime/upload-ui-xzeaf3uy/visual/checks.json`。 |
| PH21 進度／ready／關頁／歷史 | PH42 test_run_browser先關caller才啟動真Worker；13stages完成、新頁同run、下載身份、history、technical retry與未完整發布拒絕，checks ready=true／errors=[]。 |
| PH22 候選／null／來源與版本 | 同一browser逐列比對報告候選及event_spec；排序還原、零事件人數、503／錯run／同版本內容改動皆不替換舊可讀報告。4項reader／chart模型測試亦通過。 |
| PH23 三圖／單位／分母／受控renderer | 真報告scatter／line／heatmap數據表與JSON逐值核對，cohort分母與對稱展開一致；合成極值／null-gap renderer也跑，手機heatmap截圖已目視。decoder拒任意options、錯類型、超量／錯比例／重複cell。 |
| PH24 窄屏／鍵盤／對比／長文 | 現行a11y-checks有161可見HTML文字節點，最低7.470342:1；21組palette最低5.732061:1。768／390切換保留候選及長草稿，splitter／tabs／版本／匯出鍵盤、空／失敗／長事件名及圖表表格補充均在run browser。非完整WCAG認證。 |
| PH25 持久conversation／序號／FIFO | PH25真PG交易與競爭證據、PH41四成功turn讀回；PH42 chat刷新取同conversation及候選。精確queue／重放負向會在PH29–PH36審核組再核對，不以UI完成替代並行Gate。 |
| PH26 SDK／OpenRouter／缺key | 目前runtime.ts真正new ToolLoopAgent、createOpenRouter；PH42 23個SDK tests及tsc通過，涵蓋兩輪工具／steps／usage／取消／timeout／安全錯誤。實際無key正式Node入口，UI不可送但報告可讀。X01未真驗。 |
| PH27 唯讀工具／scope／引用 | 正式產品PH41重疊問題讀既有產物；PH42 SDK tests拒外來pointer／wrongscope／超量／取消結果，沒有任意SQL／Shell工具。PH27真HTTP唯讀jobs不增加的證據保留；深層server scope於後續Agent組再審。 |
| PH28 對話／IME／取消／恢復／引用 | PH42 test_chat_browser真NodeWorker／SDK／HTTP／PG：IME Enter不送、Shift+Enter、長文不強制捲底、queued/running取消、失敗重試完成、同conversation刷新／candidate保留及引用定位；actualNodeWithoutKey=true、sendDisabled=true、reportVisible=true。 |

UI資料：`.runtime/run-ui-9yta7tyl/visual/`（run e68d837a-1ebc-45bd-833a-31ce18bb0da6），`.runtime/chat-ui-t28jqxjp/visual/`，`.runtime/upload-ui-xzeaf3uy/visual/`。手機熱圖與正式無key畫面已目視；PH41正式container的桌面／手機圖作部署入口補強。仍需PH29–PH41細項與常駐使用／交付文檔審核，不能據本組判定全部Goal完成。

## 本輪實跑範圍

### 剩餘後端範圍與運維核對

| Phase／要求 | 審核結論與具體證據 |
|---|---|
| PH27 唯讀scope／引用／不建立工作 | 完整讀test_read_tools：真SDK四steps、invalidReferenceRejected、指標逐值等同report；錯version／pointer／額外run_id／shell／unknown candidate／fence拒絕。production Node worker也真領取與finish；取消／模型失敗無assistant，前後jobs總数相同。PH42 session13036批次通過，關閉先前待核對项。 |
| PH29 揭露／凍結／獨立資格 | 原證據已完整重讀；PH42 session44319現行exposure／policy六種政策測試通過，並非僅DB CHECK。按dataset/split的首次揭露跨conversation保存，三格式並行唯一；policy包含兩連線等待同advisory lock、先後預約、legacy人口補建／缺來源保守拒絕、固定freeze hash、同用戶新dataset不取得獨立資格。PH35真正新用戶正反批次補強資格與統計結果區別。 |
| PH30 分支API負例／快取fallback | 完整讀test_branches：四並行call唯一run/job、改config409／改split422／錯fence409；同parent既有normalized/quality/targets cached，窗口不同exploration/features computed。非法seed/code/sql／超父候選cap／不屬本turn的child拒絕；取消交易故障全部回滾，成功取消使舊compute fence失效，完成報告保持。PH42 session13036通過，關閉先前待核對项。 |
| PH37 三格式與離線 | 已完整讀offline_report_qa.cjs與PH37，保留兩組普通／分群交付目錄存在；腳本新離線context、零HTTP、候選metrics／四診斷表逐值與null數量、各anchor、390px無溢出。PH41／新local workspace相同正式renderer六份hash讀回；本輪沒有改renderer。 |
| PH39 故障／備份／不覆寫 | 完整讀tests/test_system_faults.py與test_backup_restore.py：真PG／S3 stop/start後503、Worker下線不發布／S3重試第2attempt完成，原報告bytes不變。ENOSPC只在真spawn下載配置邊界注入，不填滿主機，終態DISK_FULL、零report、不重領。session13036通過。備份test實際空目標還原、三格式與對話逐byte、非空bucket sentinel／非空DB拒絕、symlink／缺COMPLETE／壞hash拒絕；PH41正式容器211物件還原是較新成功證據，無需重複建立備份。 |
| PH40 容量與資源 | 原證據100行完整讀回，四份10萬／100萬一般與壓力完整13stage、独立Decimal真值、三格式hash及現行pipeline指紋先前本輪已比對。1000萬受控MEMORY_LIMIT只完成3stage，不能稱成功。CPU/RSS/磁碟取樣配額與全系統RAM範圍明示；沒有用8GiB實測冒充16GiB規劃主機。 |
| PH41 部署包／恢復／入口 | 原證據122行完整讀回。七個部署／health/harness檔案SHA256及docker image inspect三個image IDs均與最終Gate一致；未因新local helper變更正式images。正式Nginx四問、211objects還原、六hash與internal五路徑404在deployment-e2e-2jkwb3kn/result.json；只有web loopback發布、非root/read-only/cap-drop已驗。 |
| PH42 C2 常駐本地入口 | local_workspace CLI真啟動PG/S3、migration、API、Python、正式無keyNode、Vite，明示SDK替身四問／匯出；全停後相同workspace重開六報告hash及四turn／三branch不變。`.runtime/local-workspace-flow-8ba3cf75/product-acceptance.json`，1passed30.86s；桌面圖已目視。需讀docs/local_workspace.md的loopback trust／合成用途／異常PID拒接管限制。 |

### Agent 持久性補驗（已完成部分）

| Phase／要求 | 現行assert及實跑證據 |
|---|---|
| PH30 快取身份／不可變父版 | test_stage_cache逐項變動mapping、資料hash、export、seed、窗口、code及上游hash使cache失效；validation沒有共享cache；真S3損壞不得發布checkpoint。完整child計算在compute_tools，父報告bytes不變。PH42 25-test批次通過；分支API其餘負例仍需對照原PH30證據。 |
| PH31 真重跑／取消／等待 | compute_tools真SDK、HTTP、PG、Python子程序；3h條件回報逐值匹配真report及手算holdout .02收益／.5coverage／7200秒延遲。阻塞搜尋時取消後PID不存在、job cancelled、無child report／assistant，父版仍可讀。PH42通過。 |
| PH32 分群／來源規格 | 同批次segment與test_segment_branch真計算，美國分群／缺維度限制、返回數字及spec與產物一致；模型僅替身。PH42通過。 |
| PH33 調整／停止／持久預算 | adaptive兩輪3h→24h、7steps，第二輪based_on第一輪真evidence，finalization落DB。五個並行請求只接受四個；deadline／候選cap／finalize拒絕再擴張且保留報告。非空0011→0017保留舊branches／報告，補預算不歸零。PH42通過。 |
| PH34 等待中仍讀父版／結果連動 | compute_tools真child執行中跑pending browser，父報告不變；成功／分群cases跑正式compute_browser，工具卡references／run/version匹配完成child。PH42通過，完整版本切換與匯出由PH37／41補強。 |
| PH35 經驗而非權重訓練 | test_finding_independence實際新四日400用戶正向／反轉批次，固定規則、兩組100 holdout、ARPU2/0→0/2、bootstrap差值±2，資格分別reusable_evidence／not_supported；不走search、不改父報告。test_finding_recheck禁止freeze讀outcomes。test_findings真服務／SDK／selector／歷史引用、scope與重複儲存；PH42通過。重疊用戶新dataset不能洗掉污染資格，未宣稱投放成效。 |

PH25的後端FIFO疑點已由目前20-test批次補驗：四個同時claim只有一個取得第一turn；過期重領fence遞增，舊worker heartbeat／finish均拒絕；finish故障時message/event/cursor一起回滾；retry排尾且context不包含未來問題。已讀`tests/test_agent_queue.py`的實際assert，不用UI刷新替代佇列契約。

PH36的目前實證為同批次`test_agent_journal`／`test_agent_steps`／`test_agent_process_recovery`。steps拒絕未配對tool結果、reasoning及provider私有欄位；恢復不得重設deadline或步數，未完成請求也消耗預算。真Node SIGKILL涵蓋送工具前、child發布後、finish前；自然租約到期後replacement恢復，只建立一次child及assistant，父報告bytes保持。另驗模型失敗保留完成的child、Python失敗不偽造報告；模型為SDK測試模型，不能據此宣稱真provider成功。

PH37原始證據已完整閱讀：兩種分支從正式UI下載三格式，API停止後新Chrome離線file URL重開，零遠端請求；表格逐列比JSON，來源ID標記未外洩，普通／分群完整spec與範圍保留。尚需核對目前離線驗收腳本及保留產物，不能只以原證據文字結案。

PH38原始證據已完整閱讀：原全套check曾有一個locator失敗，不稱exit0；修正後affected browser＋新增完整product E2E通過。PH41目前正式images從空PG/S3再走同一四問流程，作產品入口版本補強；與PH42新chat／run UI結果共同對應，無須重新生成容量資料。

1. `uv run pytest tests/test_database.py tests/test_storage.py tests/test_storage_contract.py tests/test_jobs.py tests/test_fixtures.py -q` → exit0，27 passed，9.92s。
2. `uv run pytest tests/test_ingest.py tests/test_quality.py tests/test_targets.py tests/test_features.py tests/test_predicates.py tests/test_sequences.py tests/test_search.py tests/test_metrics.py tests/test_freeze.py tests/test_finalists.py tests/test_validation.py tests/test_diagnostics.py tests/test_report.py tests/test_report_api.py -q` → exit0，92 passed，19.89s。
3. `uv run python contracts/check.py` → exit0，22 examples。
4. `npm run test:web-model && npm run test --workspace agent` → exit0，4個前端模型＋23個SDK／工具／journal測試，含Agent tsc。
5. `uv run pytest tests/test_upload_browser.py tests/test_run_browser.py tests/test_chat_browser.py -q -s` → exit0，3 passed，50.24s；真PG／S3／API／Python／Node／Chrome，模型明示替身。2既有deprecation warnings。
6. `uv run pytest tests/test_validation_exposure.py tests/test_validation_policy.py tests/test_agent_queue.py tests/test_agent_journal.py tests/test_agent_steps.py tests/test_agent_process_recovery.py -q` → session44319 exit0，20 passed，102.71s，2既有warnings。
7. `uv run pytest tests/test_conversations.py tests/test_compute_tools.py tests/test_stage_cache.py tests/test_segment_branch.py tests/test_exploration_budget.py tests/test_exploration_upgrade.py tests/test_findings.py tests/test_finding_independence.py tests/test_finding_recheck.py tests/test_finding_assessment.py -q` → session12503 exit0，25 passed，167.94s，2既有warnings。
8. `uv run pytest tests/test_read_tools.py tests/test_branches.py tests/test_system_faults.py -q` → session13036 exit0，5 passed，29.27s，2既有warnings。

上述pytest批次有既有Starlette／anyio deprecation warnings，沒有skip／xfail。後端／UI／Agent／運維及常駐入口已完成本表所列版本補驗；較早段落中的待審項已由後續「剩餘後端範圍與運維核對」結案。最後交付文件一致性與PH42簽核仍以狀態表為準。
