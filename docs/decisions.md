# 工程決策 — PH01

## Candidate Event V3 Casual Game（2026-09-11）

V3 使用 `analysis_version=3.0-casual-game` 與獨立 candidate/artifact contract；新 baseline 完成切換後預設 V3，既有 run 依保存版本讀取。V3 cache identity 必須包含 contract、policy、feature 與 pipeline code hash，不能重用舊版本產物。

事件 identity 維持 `(app_id,event_id)`；Level attempt 使用 `(app_id,user_id,level_id,attempt_id)` 配對。同時間只有可靠 `source_sequence` 可證明先後。相同 attempt 有多個非重複 complete 或同時 complete/fail 時，不任選結果，停用 attempt pairing 及相依指標；Level 原始事件次數仍可分析。`level_index` 只接受來源提供的非負整數，不由 `level_id` 推測。

回訪是安裝／首次開啟後的半開區間正向 `session_start`；正向事件可在發生時觸發，absence 只在區間結束後確認，第一版不作主要候選。累積與事件型指標採 `first_match_once`；比例、平均值等非單調指標只在固定 observation end 採 `checkpoint_snapshot`，避免短暫跨門檻後又反轉。

72h 圖只使用 72h 前可完整判定 membership 的候選；晚期條件仍進完整驗證與匯出，但標 `LATE_INDICATOR_NOT_PLOTTED`。X/Y 都由 Python 以同一 holdout 分組計算，前端只驗證、篩選與渲染。

固定窗口、threshold grids、序列 constraints/gaps、20,000 Discovery／2,000 Validation Category 配額、回補、去重、Pareto/diversity 與 Gate 詳見 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md`。這些政策只由 exploration 與版本化常數決定，holdout 不改門檻、名單或排序。

## D01 正式資料語意

canonical schema 位於 contracts/schema.json；它校驗結構，不取代跨筆語意檢查。輸入 CSV 可映射並標準化，canonical 時間全部 UTC Z。缺時區的輸入拒絕，除非匯出設定明確指定時區。schema 版本 1.0。

用戶鍵為 (app_id,user_id)，事件鍵 (app_id,event_id)。同鍵同內容去重；同鍵異內容為 conflict，隔離並阻止該資料集正常收益推薦，不能挑第一筆或最後一筆蒙混。事件找不到用戶、發生於安裝前、非法日期均計入品質報告。重裝需來源給新匿名安裝 ID，MVP 不猜測生命週期。

ad_format 未知標 unknown，不混入 other。未知收益 null，0 為合法零收益。負收益保留於來源並標 correction_unsupported：本版未提供修正關聯鍵，不在觸發運算中偷偷扣回；含此情況停止收益推薦並輸出診斷，等待明確修正映射。NaN/Infinity 不是可接受金額。有效時長須非負且不超過可確定的前景期間；Session 時長不可靠則停用。

## D02 D7 與首次觸發

D7 按 installed_at 起算 [0,168h)，167:59:59 納入、168:00:00 不納入。完整截止時間必須 >= installed_at+168h；未滿者排除，不補零。成熟無事件用戶收益為0；有未知展示收益的用戶目標不完整，不能作零收益納入：預設阻止正常收益推薦，保存診斷。

candidate 窗口同為半開區間，門檻達到當下第一次觸發，每位用戶一次。available_at 不得早於 event_time。收益 timing=immediate 才可直接用 event_time；available_at 模式以該時間判定可用性；unknown 仍可算完整D7，但停用收益型即時觸發候選。session_end 的時長只在結算時可用。未來資料不得改過去觸發。

count 的 threshold 必須正整數；session_count 固定計 distinct session_id，不直接數重複 start；engaged_seconds 用 session_end 且每session一次。原子條件預設 count/revenue_sum 對 ad_impression；session_count對session_start；時長對session_end，不相容 event_name 在業務驗證拒絕。

AND 是所有原子當時同時達標；OR 任一成立。sequence 為最早可完成的非重疊貪婪配對：A後找最早合法B，完成一對後事件不再重用；超過max_gap丟失配對。相同時間僅可靠source_sequence能確立先後，否則不匹配。repeats上限3。複合僅两個原子或兩步序列，不接受深層任意AST。

## D03 搜尋預設及驗證

contracts/defaults.json 為機器可讀配置。窗口1/3/6/24/72h；168h只作診斷。最多2000候選、10個finalist、固定seed42，依安裝日的用戶數逼近70/30切分，整日不可拆。至少需要兩個探索安裝日、兩個驗證安裝日，不足則只報探索結果。

初始門檻：count [1,2,3,5,8,10,20]；Session [2,3,5]；有效秒 [60,180,600,1800]；收益門檻取探索集正值分位數[0.25,0.5,0.75,0.9]，同值去重。複合在探索集前20原子間生成，排序採確定性ID打破平手，所有剪枝留紀錄。

歷史驗證標籤工程預设：觸發與未觸發各至少100成熟用戶；至少兩個驗證日各有兩組各20人；兩日收益差異方向皆為正；用戶層bootstrap1000次的差異95%區間下界>0。只檢查探索預先凍結finalist；報告必須說明這是觀察性、描述性規則，非多重比較校正、非投放因果。少量synthetic可以測數值，不可降低門檻取得validated。测试需完整明示测试override，production defaults不变。

D7 ARPU =成熟用戶收益總和/成熟用戶數。比較全體含觸發者時bootstrap採同批用戶共同重抽樣；主要差異另外用觸發/未觸發兩組。基準為0時倍數null。相關性排序與推薦只在探索集完成，holdout只驗證固定finalist。

## D04 版本及UI

baseline不調用LLM。followup一律exploratory；若要新資料獨立驗證，以新批次baseline綁定預先凍結candidate manifest，不能升級原followup。資料揭露跨對話記錄，以dataset內容版本防止換ID洗掉holdout。artifact與run必須相符；JSON Schema不能驗證外鍵，由repository驗證。

報告模板與圖表是固定renderer，模型不能注入HTML/SQL。UI左對話右結果，深色為可調設計預設。金鑰僅服務端，無會員功能。小量資料／模型替身顯示其來源標記。

## D05 合法／非法結果矩陣

| 情境 | 預期 |
|---|---|
| UTC Z／android 用戶 | schema接受 |
| 無時區／web platform | schema拒絕 |
| null收入／合法0收入 | 結構接受；null後續品質阻止收益推薦，0正常 |
| event key衝突 | 品質阻止，不隨意選擇 |
| 任意Python op／深巢狀條件／169h | schema拒絕 |
| first_match_once條件 | schema接受，首次觸發於後續計算驗證 |
| baseline有parent／followup宣稱validated | schema拒絕 |
| 任意HTML圖表／../object key | schema拒絕 |
| 6小時剛好達標 | 窗口右端排除 |
| 相同時間無序號 A/B | 不構成嚴格先後 |

PH01驗證schema與案例；演算法數值由PH03、PH10–PH16實測，不因本文件描述而稱已實作。
## D06 — PostgreSQL 持久模型（PH04）

SQLAlchemy Core + psycopg 3 保存資料；Alembic 使用版本目錄中的固定 SQL migration，不從未來模型動態 create_all。交易由呼叫端掌控，run 與 queued job 在同一交易寫入。封存 dataset 全紀錄不可變，run 的 dataset/config/hash/lineage/計算版本不可變；狀態與進度另可更新。artifact/report 只新增版本，不覆寫。複合外鍵確保 parent 同 dataset、artifact 同 attempt/run、report 同 artifact/run；DB trigger 確認 root lineage 與封存前置。

測試建立獨立 PostgreSQL cluster，只綁 loopback、隨機 port，停止精確 data directory；保留資料與 log，不更改系統 PostgreSQL。缺 binaries 是本地門檻失敗，不用 SQLite 替代。此階段不宣稱已有任務領取／fencing／冪等回覆，這些屬 PH06。

來源：[SQLAlchemy psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)、[Alembic migration tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)，2026-09-09 查核；實際版本已鎖 sqlalchemy 2.0.52、alembic 1.19.2、psycopg 3.3.5。

## D07 — 正規化與隔離（PH08）

CSV／Parquet 先按明確欄位映射讀取，空字串視缺值，非空 ID 不 trim／猜測；日期須顯式時區，轉 UTC TIMESTAMPTZ。native 無時區 Parquet timestamp 不擅自視 UTC。收入使用有限 DOUBLE，不將 null 當 0；負收入保留並由品質 gate 阻止正常推薦。未知 ad_format 轉 unknown，但原來源保留。

固定 canonical 型別後去重；同鍵不同有效內容或同鍵有非法列，整個鍵隔離，不挑任意 winner。保留 raw 衝突列、非法列與無法串接列；quarantined_keys 是鍵數，invalid_rows 是列數，指標可重疊，不能相加推論總排除數。來源有未映射欄位不參與 canonical 相等性判斷，但來源檔原封保存。

DuckDB 磁碟工作表、受控 memory/threads、64K row group、固定排序產生標準檔；只有全檔成功與 source hash 前後一致才發布 manifest。未知 source glob/path 不接受。此時不做成熟 D7 或收益推薦判定，後續 PH09/PH10 各有 gate。
# D08 — D7 目標與切分（PH10）

成熟用戶按 UTC 安裝日整批分組。只用安裝日和人數，在探索／holdout 各至少兩日的合法邊界中選最接近 exploration_fraction 的人數比例；平手選較早邊界。不足四日所有成熟用戶列 exploration。split_id 綁 cohort Parquet hash、定義版本、完整截止與比例，不綁收益；改 holdout 收益不影響 split_id。

targets 包含未成熟用戶，但其收益 null、split=excluded_immature。成熟零事件用戶為 0；有缺失／負修正收入者目標 null，群體 ARPU 不偷偷排掉它們再計算，而顯示 null 與 unknown_targets。缺樣本時不宣稱驗證通過。資料品質限制與統計門檻仍分層檢查。
# D09 — 原子與布林首次觸發（PH12）

單調 timeline 每個原子取第一個 >= threshold 的時刻；AND 為所有原子達標時刻的最大值，OR 為最小值（允許只有一個原子有觸發）。每個候選同一半開窗口，依 user installed_at 限制；不接受更長於已生成 feature horizon 的條件。收益修正不走單調捷徑，按品質 flags 拒絕計算。

觸發記錄包含可觀察早期行為的未成熟用戶，統計必須另 join cohorts 使用成熟人群。原子 schema 接受的 event_name/ad_format 還需業務相容性檢查；計數只接受整數 threshold，數值必須有限。批次最多 2000 且 candidate_id 不重複，非法候選整批拒絕、不靜默忽略。
# D10 — 序列匹配（PH13）

兩步序列使用貪婪最早完成、非重疊配對。gap 上限含右端（窗口本身仍右端排除）；過期 start 丟棄，保留尚在 gap 內的後續 start。完成一對後清掉此前所有 starts；end 不可再作 start。相同時間只有全部相關事件 source_sequence 非 null 且唯一才按序號處理，否則只允許本時間的 B 配對較早時間的 A。若該時間完成配對，無可靠序號的同時 A 不可證明晚於 B，因此不能開始下一對。不用 event_id 打破時間平手。

正式 evaluator 用 DuckDB 排序／分批讀取，Python 僅保留目前用戶的待配 starts 與同時刻 bucket，而非全量 log。極端同用戶／同時間事件偏斜的記憶體仍須 PH40 實測，不以此宣稱無界容量。
# D11 — 探索輸入隔離與搜尋（PH14）

固定 split 後，先 materialize exploration 成熟用戶及其 canonical events，重新計算該範圍的 quality/features。不得從全資料能力 flags 篩探索候選：holdout 缺值會透過 flags 間接污染搜尋。search 僅接受有 parent source hash、target manifest hash、split_id 的 exploration scope。全資料品質警告另保留供報告／驗證，不因 scoped quality 通過而移除。

收益分位數只用探索正 snapshot 值，其他原子用 D03 網格。top20 原子依探索觸發／未觸發 D7 平均差異降序，無未觸發組者放後，ID 打破平手；只同窗口可組合。相同 metric/scope 的 AND/OR 簡化為 max/min threshold，commutative clauses canonical 排序；不以相同命中用戶當作不同延遲候選等價。序列搜尋固定三類事件任意二步、gap 60/600/3600 秒、repeats 1/2/3。

候選按窗口輪替進上限；max_candidates 小於窗口數時按升序窗口先入，未入者逐項標 MAX_CANDIDATES_LIMIT，不宣稱窮盡無界搜尋。這是候選生成／描述性排序，不是 finalist 獨立驗證。feature 接受與 config 相同的有限正數小時（最大168），不再限制整數。
# D12 — Finalist 凍結與歷史驗證（PH15）

所有候選類型先用探索人群真觸發評分，按觸發／未觸發正均值差排序，ID解平手；最多取max_finalists，不因數量不足補湊。凍結包含精確候選、來源／split／export（收益timing）、規則及搜尋hash。正式validation自行驗freeze receipt，再生成固定候選觸發，只join成熟holdout。品質失敗或能力不可用只影響驗證可用性，不回頭改finalist。

bootstrap使用固定種子、用戶層重抽樣：hit/miss分層抽兩組，hit/all使用同一cohort draw保留協方差；抽不到hit時該paired replicate無定義，記valid/requested數。百分位區間線性插值。品質、兩組最低樣本、至少兩個各組20人的驗證日、所有觀察日正差、差異95%下界>0均需符合；這是保守描述性標籤，不是因果或多重搜尋校正。
# D13 — 重疊與觀察性收益診斷（PH16）

診斷固定明示split（exploration/holdout/all_mature）及cohort_id，所有分母來自相同成熟人群。Jaccard=intersection/union；雙向覆蓋各自除A/B人數，無分母null，不用空集合的任意慣例1。相同命中集合標same_observed_users，但不合併不同觸發時間的候選。

原子敏感度點依metric/format/window成family，保留threshold及相同cohort，主ARPU不截尾、另報p99。重疊與landmark最多10個明確comparison_ids，多於10未指定就拒絕，不暗裁候選。敏感度仍涵蓋提供的所有候選。

觸發後收入取event_time嚴格晚於triggered_at且早於install+168h；同時刻無法逐筆歸因則保守全排除。共同landmark預設24/72h，分組只看嚴格早於landmark的觸發，收入區間[landmark,168h)。缺收益／負修正不補0。全部是exploratory觀察性診斷，不標因果。
# D14 — Baseline持久stage與提交（PH17）

每stage以run/stage/version/input_hash識別，input包含dataset/config、上游checkpoint、pipeline程式與contracts hash。stage樹保存JSON/Parquet及PH18新增的HTML/CSV至唯一S3物件，不保存DuckDB工作檔；PG短交易檢查lease/fence後提交checkpoint與progress，上傳不持DB交易。重啟新workspace逐檔校驗、root manifest最後還原。舊attempt checkpoint可供同run重用，舊lease不可再提交。

Worker父程序監督spawn計算並續租；子程序使用環境DB/S3建立自己的連線，payload僅攜帶run/lease識別與config。最後compact refs經父程序fenced交易發布。checkpoint成功不等於API報告ready；計算未最終提交時不發布半套artifacts。SIGKILL後自然租約到期接手，資料品質不足以diagnostic_only完成，而非假推薦或一律技術失敗。

# D15 — 離線報告及原子版本發布（PH18）

report_json 是版本模型；HTML/CSV 為同 run/attempt 的確定性匯出，三種格式均齊才在父程序 fenced 交易提交 report_versions。JSON/CSV 保留原始值，HTML 以 USD/%/h 呈現、data-value/tooltip 留原值；未知顯示未知或 CSV 空白。HTML 所有資料文字轉義，CSV 危險文字加單引號，無外部 JS/字體或模型依賴。

候選保持探索階段凍結順序。診斷用 exploration，人數/收益不可混用 holdout；源 artifact SHA/S3 key、dataset/run、split、rules、quality/targets 是稽核契約。沒有通過歷史規則時輸出待補資料建議，不湊上線推薦。下載是附件，校驗bytes後才回應；stage中間檔不是正式報告。

# D16 — 瀏覽器上傳及意圖識別（PH20）

採@noble/hashes2.4.0，Web Worker按4MiB slice增量SHA256，再逐part直傳presigned URL；不把整個大檔交給主執行緒arrayBuffer。官方[使用說明](https://github.com/paulmillr/noble-hashes#implementations)提供create/update/digest增量介面。版本由npm確認並鎖定；固定指紋、檔案size及server完整checksum一起防錯檔。

上傳建立使用dataset+完整payload的穩定key以恢復未知回應；一般mapping編輯用新intent key，避免A→B→A被前次A快取截住。baseline同dataset/config用穩定key，版本仍由backend封存。刷新讀PG紀錄，只由使用者重選File，禁止把來源檔或signedURL放localStorage。

# D17 — Ready 門檻與明確技術重試（PH21）

ready需succeeded+report_versions錨定同run/attempt的完整唯一三格式，避免將舊succeeded骨架或半成品當可對話資料。history按created_at/id keyset查PG，view只暴露進度metadata與錯誤，不把原始log交給瀏覽器對話。

手動retry是同run失敗執行的恢復，不是更改分析配置的followup：僅failed baseline且technical allowlist、零published artifacts/reports可排。以api_requests idempotency記錄明確意圖，job→run鎖順序，fence遞增拒舊worker，保留舊attempt/checkpoint並給3次新的自動嘗試額度。配置不變；若修改分析條件需後續分支機制，不能借retry繞過。

# D18 — 單一受限圖表 renderer（PH23，驗收中）

採 Apache ECharts 6.1.0，npm registry 確認版本後 exact lock，安裝 ignore-scripts、audit 0 vulnerabilities。使用 core 按需註冊 Scatter/Line/Heatmap、Grid/Tooltip/VisualMap 和 SVG renderer，React lazy 獨立載入圖表。官方依據：[按需載入](https://echarts.apache.org/handbook/en/basics/import/)、[散點](https://echarts.apache.org/handbook/en/how-to/chart-types/scatter/basic-scatter/)、[折線與缺值](https://echarts.apache.org/handbook/en/how-to/chart-types/line/basic-line/)、[Cartesian heatmap 範例入口](https://echarts.apache.org/examples/en/editor.html?c=heatmap-cartesian)；範例頁需 JS，熱圖能力仍需本地實際 renderer 驗證，不以頁面入口當完整驗收。

只接受 contracts/schema.json 的 chart 欄位與有限 numeric points，不接受 ECharts option、formatter、HTML/JS。Tooltip 採 richText；null 不補 0，空矩陣不填 100%。散點取 holdout，敏感度按 op/ad_format/window 分開而且只使用診斷 cohort；熱圖同一 cohort。已知圖表 lazy chunk 約 560 kB／gzip 190 kB，尚需 PH23 完整視覺與邊界驗證，不透過提高 warning 上限隱藏。

# D19 — 正式 AI SDK / OpenRouter adapter（PH26）

鎖定 ai7.0.94、@openrouter/ai-sdk-provider3.0.0、zod4.1.8（provider peer範圍ai^7、zod^3.25.76或^4.1.8）。npm ignore-scripts安裝，audit0 vulnerabilities。官方[ToolLoopAgent原始文件](https://raw.githubusercontent.com/vercel/ai/main/content/docs/03-agents/02-building-agents.mdx)及安裝套件型別確認7版使用isStepCount；[OpenRouter正式整合文件](https://openrouter.ai/docs/guides/community/vercel-ai-sdk)確認createOpenRouter。網站部分範例仍用舊parameters，因此實作以當前鎖版型別和SDK實測為準，使用inputSchema。

runAgent只委託真正ToolLoopAgent；預設8步、120秒、4096 output tokens、provider retry0（持久任務層負責重試），明確step_limit而非假完成。測試注入MockLanguageModelV4，不以自寫loop代替SDK。正式model只讀server env，health的configured不等於verified；workerConnected仍false，PH26不是端到端對話完成。模型錯誤不回傳response body或credentials；工具必須在其邊界處理敏感錯誤，唯讀工具在PH27實作。
