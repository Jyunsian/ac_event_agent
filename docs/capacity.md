# 容量測試與資源保護

容量以 `scripts/benchmark.py` 的實測結果為準，不以檔案筆數猜測或小樣本推算宣稱支援上限。每批由全新真 PostgreSQL／MinIO、正式Python Worker與所有baseline stages執行；模型完全不參與。未加入客戶log、不刪現有檔案。

## 使用方式

預設只有只讀預檢，不建立資料或啟動服務：

```sh
uv run python -m scripts.benchmark --directory .runtime/benchmark-next --users 100000 --events 1000000
```

確認容量與保留空間後，加 `--run` 執行。directory必須不存在；不使用已存在的目錄、不覆寫上次結果。需要README的本地PG／MinIO及Python依賴。

```sh
uv run python -m scripts.benchmark --directory .runtime/benchmark-next --users 100000 --events 1000000 --run
```

預檢採保守CSV位元組估算，再用input×12估工作需求；這不是已證明的磁碟上限。生成後，正式管線會再以實際source bytes預檢，並在執行中監視資源。若實際失敗，要保留失敗結果、診斷原因，不把降低候選數或bootstrap次數後的結果當成原設定通過。

完整結果寫入該目錄的result.json，包含：

- 硬體、Python／pipeline指紋、全部候選與窗口配置、seed。
- 用戶／事件數、來源hash、保留及凍結候選數。
- 生成／真值計算時間、Worker wall time、總wall time。
- Compute子程序peak RSS、CPU秒數、取樣peak workdir bytes及資源設定。RSS不含PG／S3／控制程序，不能誤稱整套服務記憶體。
- 保留的benchmark、PG、S3磁碟用量；三格式報告hash。
- 獨立Python CSV／Decimal參考值：用戶／事件、零事件用戶、完整D7成熟用戶及[0,168h)收益。檢查不調用正式分析函式，收入容差明定於script。

所有正常化→目標→搜尋→凍結→驗證→診斷→報告階段須完成；job succeeded但只有診斷報告，不能作完整benchmark通過。原始資料與產物保留，服務結束時只停止這次建立的精確程序。

## 伺服器設定

| 環境變數 | 預設 | 生效範圍 |
|---|---|---|
| WORKER_RSS_MB | 1536 | Compute子程序峰值RSS監視，單位MiB |
| DUCKDB_MEMORY_MB | 256 | 全部DuckDB連線的memory_limit，依DuckDB MB語意 |
| WORKER_THREADS | 2 | 全部DuckDB連線執行緒數；不是整機CPU百分比 |
| DISK_RESERVE_BYTES | 2147483648 | 保留至少2GiB可用磁碟，預檢及運行中監視 |
| MAX_WORKDIR_BYTES | 4294967296 | 每個compute暫存目錄上限4GiB |
| WORKER_TASK_TIMEOUT_SECONDS | 900 | Worker wall-clock timeout |
| WORKER_CPU_SECONDS | 600 | Compute執行期間累積user+system CPU秒數 |
| WORKER_WORK_ROOT | OS暫存目錄下ac-event-work | 每個任務建立獨立目錄，不能與來源輸出混用 |
| MAX_UPLOAD_BYTES | 5368709120 | API單一上傳大小上限 |

設定只來自伺服器環境，不接受Agent工具修改。錯誤值拒絕，不默默使用無限資源。Compute watchdog約每0.25秒觀察RSS／free disk／CPU，每秒觀察工作目錄；native計算超限也能終止，父Worker保存明確錯誤且不發布假報告。這是取樣保護，不等同Linux cgroup硬配額；正式容器另需配置主機／容器限制。

錯誤：MEMORY_LIMIT、DISK_RESERVE_LOW、WORKDIR_LIMIT、CPU_LIMIT、TASK_TIMEOUT、DISK_FULL；配置或預檢失敗不生成假成功報告。容量改善後由正常重試流程處理，不能無限自動重試OOM／磁碟滿。

## 實測狀態

### Candidate V3（CG06 核心容量通過；全套回歸收尾未完成）

- `.runtime/cg06-v3-capacity-001/result.json`：2,200 users／100,000 events，真 PostgreSQL／MinIO／Worker 全流程通過；Discovery 20,000、Validation 2,000、priority 10、plotted 1,733，15 stages 全部 computed，獨立 users/events/mature/D7/zero-event/report checks 全 true。
- compute wall 200.580s、CPU 194.109s、peak compute RSS 927,154,176 bytes、peak workdir 575,756,789 bytes；使用原 256MB DuckDB／2 threads／1,536MiB RSS／600 CPU 秒／900 wall 秒／4GiB workdir／2GiB reserve。
- 完整 catalog 2,000，detail 41,198,742 bytes；JSON／CSV／HTML 分別 15,680,347／1,142,471／37,409,802 bytes，hash 保留於 result。
- 執行後已清理隔離服務副本與可重建 workdir；結果、來源 hash、下載報告與 stage timings 保留。之後 follow-up／segment 相容修改使全檔案 pipeline fingerprint 改變，未再跑 100k；CG06 因使用者要求收尾而標 `closed_partial`，不宣稱目前 source 已完成一次性全套回歸。詳見 `evidence/CG06.md`。

### Candidate V2（CV05 尚未通過）

- 最新固定版本 10 萬事件容量已通過：`.runtime/cv05-100k-v2-03/result.json`，2,000 位用戶／100,000 事件，實際搜尋及評估 2,000 候選、每候選 1,000 次 bootstrap，13 階段及全部獨立真值／完整目錄／報告檢查均成功。compute wall 50.119435 秒、CPU 53.865185 秒、peak RSS 453738496 bytes、peak workdir 97337517 bytes；原 DuckDB 256MB／2 threads、CPU 600 秒、wall 900 秒、RSS 1536MiB、workdir 4GiB及磁碟保留 2GiB均未放寬。這不代表百萬事件已通過，CV05仍保持進行中。

- 第十五輪`.runtime/cv05-1m-v2-15/result.json`仍failed/CPU_LIMIT，compute wall478.857314s，完成650候選checkpoint、未完整校正/報告。修復features OOM後已進validation，但不能稱整體600CPU秒通過。後續直接觸發COPY與選擇membership memo的全量值/manifest對照已通過，單stageCPU84.803s與50.024s；效益有限且不等於整合改善，目前沒有更新版完整百萬passed，詳見evidence/CV05。

- 第十四輪`.runtime/cv05-1m-v2-14/result.json`為failed/COMPUTE_FAILED，compute wall257.725368s；stack定位完整features有序聚合的DuckDB OOM。完成至selection，未進validation；不是原600CPU限制通過。正以FEATURE_VERSION1.2互斥維度分批修復並單stage百萬實跑，保留原256MB/2threads與全部十窗口；變更須重跑最終十萬/百萬與完整回歸。

- 最新單stage觸發輸出1.5量測（cv05-trigger-parts-1m-02）：23147531行、CPU90.361096s、wall75.035775s、RSS365494272bytes、work peak416145077bytes，未更改原Limits。第一版parts在256MB OOM，已改每候選DROP暫存表並重驗。這不是完整V2百萬容量通過；逐列輸出對照與最終完整回歸/十萬/百萬仍需收取。完整v4驗證manifest已具2000列且與v3資格判定完全一致，但終止stdout資源數字缺失，不補造效能證據。

下方 PH40 數字屬舊版歷史，不代表擴充窗口／全家族驗證後的容量。V2 以 `evidence/CV05.md` 與 `.runtime/cv05-*/result.json` 為準。

- 首次10萬事件／2,000用戶完成Python全管線及2,000候選，獨立D7真值一致；但容量控制腳本讀取catalog時 AttributeError，整批結果保留 failed，不算驗收通過。
- 修正腳本使用正式 UploadService 後，第二次同設定完整重跑passed：`.runtime/cv05-100k-v2-02/result.json`，13階段、2,000候選及全部checks=true；compute wall418.007s、CPU460.353s、RSS469680128 bytes、workdir183514048 bytes。RSS只指compute child，非整套服務。首跑失敗目錄保留。
- V2核對完整catalog／逐候選detail數量一致、優先最多10、實評最多2,000及至少一批達2,000旗標，記錄catalog、全部detail及三格式報告大小。不是只核對精選報告筆數。
- 100萬事件／100,000用戶新版首跑failed／CPU_LIMIT：`.runtime/cv05-1m-v2-01/result.json`，compute wall339.322s，完成至search而非完整管線。需修復並同規模重驗，不屬外部延期；不得用舊PH40數據宣稱完成。資源限制沿本頁原值，候選／bootstrap不縮減。
- 截至第八輪仍沒有V2百萬事件全管線passed：`.runtime/cv05-1m-v2-08/result.json`為CPU_LIMIT、compute wall480.195s，已完成至350候選的描述checkpoint，未完成全家族校正/報告。第2–8輪失敗與修復完整保留於evidence/CV05.md及各result.json；不能把部分checkpoint當驗證通過。
- 單階段證據不能替代容量：`.runtime/cv05-validation-1m-window-cache-01/result/manifest.json`曾完成2000項與Holm，但只驗證階段已用532.474CPU秒；之後方法改為版本化精確hybrid bootstrap。`.runtime/cv05-exploration-trigger-reuse-1m-02/result`的全部23147531觸發行Parquet與第八輪原版SHA相同（CPU107.961s）；`.runtime/cv05-selection-indexed-1m-01/result`完整selection manifest相同（CPU57.831s）。這些是正確性/單stage效能對照，不是整體600CPU秒通過。
- 第九輪`.runtime/cv05-1m-v2-09/result.json`為DISK_RESERVE_LOW、compute wall150.216s，在觸發輸出階段停止，未到完整驗證；不是CPU改善已通過的證據。保留2GiB門檻不變，清理已停止合成測試的可重建工作DB/spill後，第十輪以相同用戶/事件/2000候選及原配額重跑中。新版十萬事件與全套回歸仍須最終固定版本重驗；上方第二次十萬passed屬較早計算版本，不能當全部後續改動驗收。

- 第十輪 CPU_LIMIT（477.393s、450候選checkpoint）；第十一輪在不並行大型測試下仍 CPU_LIMIT（507.677s、850候選checkpoint）。`.runtime/cv05-1m-v2-11/result.json` 保留原600CPU秒/2000候選限制。已啟用逐stage計時，後續將另存exclusive JSONL，避免stdout截斷失去診斷。正在驗證完整相同人群的局部統計重用，尚未取得最終版本容量通過。

- 第十二輪 `.runtime/cv05-1m-v2-12/result.json` 為DISK_RESERVE_LOW（165.989s），停止於探索trigger，尚未跑到membership memo；不把此失敗當成新memo效能結果。保留來源/failed紀錄，已清理舊合成測試暫存並增加完成stage的工作DB釋放；待固定版本PG/S3恢復回歸後，重新實跑原規模與原配額。

- 第十三輪 `.runtime/cv05-1m-v2-13/result.json` 為CPU_LIMIT（475.101s、500項checkpoint），自動工作DB釋放生效但尚未完整驗證。精確stage計時已保留。之後修復浮點歸約重現性、改數字有序平均並減少bootstrap矩陣複製；單獨selection完整manifest對照相等（CPU52.113s），完整validation單stage診斷進行中。仍沒有最終版本V2百萬全流程passed，不能沿用較早版本容量或部分結果宣稱完成。

### PH40 歷史實測

1000萬事件／10萬用戶已在清理後補跑：`.runtime/benchmark-10m-001/result.json`為failed／MEMORY_LIMIT，完成normalized、quality、targets後停止，compute wall70.7055秒、總190.5733秒。配置為RSS1536MiB、DuckDB256MB、2threads、CPU600秒、wall900秒、workdir32GiB。沒有完整報告或全部13階段，不能稱1000萬通過；失敗記錄也未提供可採用的完整峰值RSS。已完整驗證仍為10萬與100萬的一般／寬ID加重複合成情境。更高容量需另定合適主機與明示配額再驗，不能僅提高配額就聲稱成功。

### 寬欄位／重複事件變體

`--id-padding 64 --duplicate-every 10` 在 user_id 與 event_id 各追加64個ASCII bytes，每第10筆原始事件重放前一筆（總原始筆數不變）。既有generator約一半事件偏向u0、時間隨機亂序，仍保留零事件用戶。這是明確合成的壓力情境，不代表所有真實資料分布。

```sh
uv run python -m scripts.benchmark --directory .runtime/benchmark-stress-next --users 100000 --events 1000000 --id-padding 64 --duplicate-every 10
```

先預檢，通過後才在同命令加`--run`。寬度已納入預檢bytes估算，不沿用窄欄位的空間估量。結果的`events`為原始筆數，`expected.events`為去重後筆數；`expected.raw_events`及`duplicate_events`分別保存原始／重複筆數。CSV/Decimal參考計算獨立依App/event ID去重；同ID不同內容直接拒絕參考真值，不任選一筆。比較正式正規化筆數與D7收益，不能把重複展示再次計收入。

早期參考驗算使用Python身份索引。準備1000萬補驗時已改為benchmark目錄下獨立reference.sqlite（cache16MiB／mmap關閉），避免將全部事件ID留在RAM；CSV/Decimal仍獨立計算D7，不使用正式DuckDB分析公式。用戶安裝表仍保留於記憶體，compute peak RSS不涵蓋控制程序。索引exclusive create、不覆寫來源或舊結果，壓力profile與成功／失敗都保留。

權威數字與最新驗收見 `evidence/PH40.md` 和各批result.json。不同用戶數、事件密度、事件種類及候選上限會改變資源需求；某批通過不代表任意同筆數資料都能在相同時間完成。1000萬事件需獨立預檢與實跑或依X04如實延期，不從100萬結果外推已驗證容量。
