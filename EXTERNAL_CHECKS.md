2026-09-17 最新授權：首次全部部署 Railway；共享密碼、獨立空白資料庫＋合成示範、US$50/月目標（模型另計）。狀態以 evidence/RAILWAY-DEPLOY.md 為準，以下舊部署目標保留歷史。

2026-09-17 本輪實測更新：Railway 正式 HTTPS／共享密碼、私有網路、PostgreSQL／Bucket 持久保存、真 OpenRouter 對話、Worker／API 恢復、備份還原與 V4 雲端容量已驗收。入口 https://web-production-ac81b.up.railway.app 。目前只含合成示範；真客戶資料、投放效果、跨日排程觀察及長期月費仍不是本輪已證明事項。Vercel 未部署，舊 CG06 狀態不改寫。

# 外部操作與延期驗證

日期：2026-09-09｜狀態：外部待驗清單；本地替代驗證已完成，尚未驗證外部環境

本表是使用者允許先延期的操作清單，不是已完成事項。核心 Phase 硬門檻不能填入此表以跳關。

## Candidate V3 收尾待驗（2026-09-11）

CG06 的 100k／20k／2k 真本地容量已通過；使用者要求停止追加耗時回歸並收尾，目前 source 尚未完成一次性 98-file 全套重跑，且容量後的 follow-up／segment 相容修改改變了 pipeline fingerprint。這是已揭露的本地補驗，不轉列外部條件，也不把它標成 passed。另待外部或後續明示授權的範圍：真客戶資料、V3 1M events、3k/4k 候選升級、託管 PG/S3、Railway/Vercel 部署與正式 GLM 品質；沒有部署或投放因果聲明。權威細節見 `evidence/CG06.md`。

## 語言改造的模型補驗（2026-09-10）

最終更新：本次語言Goal的真GLM五題第三輪與最後白話短回覆已完成，父版不變、唯讀問題不新增分析；細節與前期失敗見evidence/LANGUAGE-L05.md。本次所需模型測試不再延期。下方歷史X01尚有更廣泛模型品質／生產情境範圍，不應把這次有限抽樣當成全部外部測試完成。金鑰仍僅程序環境，撤銷後將無法提問。

恢復更新：原授權key經provider只讀認證HTTP200，已重新注入本專案正式Agent程序；5174目前available=true。金鑰未寫入檔案。新版五題真模型驗收執行中，見evidence/LANGUAGE-L05.md，不再以未配置為延期理由。

更正：使用者已於2026-09-09提供本專案臨時測試金鑰，且有真模型成功證據。2026-09-10目前入口的未配置狀態，是此次新啟Node程序未載入原授權的模型環境，不是使用者未提供金鑰，也尚未證明金鑰失效。應先修復／核對既有配置的載入；不得直接把它歸為使用者缺少外部條件。先前真模型結果不能代替新prompt驗收。

L05恢復的目前程式版正式Node Agent與API已連線，但`/api/agent/status`回傳`OPENROUTER_NOT_CONFIGURED`。本次沒有在檔案保存金鑰、沒有挪用其他專案憑證，也沒有把先前版本的GLM結果當成新prompt的驗收。新語言prompt的真模型品質與代表問題暫列X01補驗；本地SDK替身、引用校驗、不可用狀態與持久報告仍照常驗收。有效授權憑證進入本專案Worker環境後，再以合成資料、有限步數與時間測試；無需為此部署雲端。

## 最新已確認選擇（2026-09-09）

實測更新：GLM 5.3 Flash真OpenRouter provider smoke已通過（3steps／兩輪工具／2714tokens），真產品讀報告與引用亦成功。3h分支已真計算，但第一次最後敘述超120s；現以可配置300s重驗，不把child成功當turn成功。詳evidence/OPENROUTER-GLM-2026-09-09.md。X01四題整體補驗仍pending_external；沒有雲端部署。

重驗結果：300s設定下3h題turn succeeded，真GLM get_baseline_report→rerun_analysis→evaluate_analysis→帶真引用回答完整成功；child5b75631a-bc4b-4527-8b30-10d50ea7a7cf，父報告不變。兩個產品情境已真驗；其餘代表題與更廣泛模型品質仍待測，X01不提前全部通過。

- X01：測試先使用`z-ai/glm-5.3-flash`；使用者已提供臨時key供測試，文件不保存key。真模型尚未驗證，測試後由使用者撤銷key。
- X03：前端Vercel、後端Railway，**測試完成後才部署**。目前只記錄決策，不建立服務、不配置DNS或新增費用。後端包含API、Python Worker、Node Agent Worker。
- X02：PG／S3具體供應商與區域仍待確認；不能推定使用者已選定Railway資料庫或某個bucket。
- 下方Compose命令仍是本地／自管部署驗收參考；不能直接當成Vercel／Railway部署步驟。正式平台適配與存取保護需在部署階段另驗並更新命令，不改寫歷史本地驗收結果。

| ID | 待外部條件 | 先完成的替代驗證 | 補验通過標準 | 狀態 |
|---|---|---|---|---|
| X01 | OpenRouter key、選定模型及使用授權 | PH26–PH36 的真 SDK＋可重現模型替身 | 真模型至少兩輪工具調用，正確工具參數、證據引用、錯誤處理與用量紀錄 | pending_external |
| X02 | AWS S3／託管 PostgreSQL 環境 | PH04–PH07、PH39 的本地真服务 | 真上傳CORS／續傳／權限、DB migration及資料保存通過 | pending_external |
| X03 | 主機、域名、TLS及入口設定 | PH41 的正式image本地演練 | 指定環境上傳→報告→對話及重啟驗證；記錄實際URL和版本 | pending_external |
| X04 | 足夠資源執行1000萬事件 | PH40 的10萬及100萬窄／寬欄位＋重複完整baseline實測 | 完整1000萬benchmark與正確性／資源報告，或如實公布較低上限 | pending_external |
| X05 | 客戶資料與後續投放實驗 | 合成真值、漏數／能力檢查 | 真資料合約確認、成熟批次分析；投放效果需獨立實驗證據 | pending_external |

實作到相關 Phase 時，在本檔追加：缺少條件、已完成程式、實際可執行補驗命令、預期產物、目前版本。不先捏造尚不存在的測試命令。

本地功能 Phase 可在替代驗證及全部硬門檻通過後继续；對外只能描述為「本地驗證完成／待指定外部驗證」。未通過 X01 不稱真模型整合已驗，未通過 X03 不稱已上線。X05 的商業成效驗證不阻擋軟體本地交付。

## X04 資源預檢：PH40

更新：清理後已實跑1000萬事件／10萬用戶，session87105最終exit1。`.runtime/benchmark-10m-001/result.json`記錄MEMORY_LIMIT：完成normalized、quality、targets三階段後受控停止，compute wall70.7055秒。RSS配額1536MiB、DuckDB256MB、2threads，僅工作quota提高32GiB；沒有完整報告，不宣稱1000萬容量通過。當前完整驗證範圍為100萬窄／寬欄位合成情境。X04保留為較高容量補驗，舊磁碟不足理由已失效。

早期預檢主機為8GiB RAM、當時磁碟約剩8.1GiB；這個磁碟數字已過時，執行前以即時df為準。10萬／100萬baseline已實跑並校驗，詳細數據見evidence/PH40.md；不外推1000萬容量。1000萬／10萬用戶的保守工作空間估算為23193612288 bytes，另保留2147483648 bytes。此為input×12規劃估算，不是已測峰值。

只讀補驗（不建目錄或啟動服務）：

```sh
MAX_WORKDIR_BYTES=34359738368 uv run python -m scripts.benchmark --directory .runtime/benchmark-preflight-10m --users 100000 --events 10000000
```

清理後預檢曾exit0；每次仍需依即時磁碟重新判定，不能固定預期DISK_PREFLIGHT_LIMIT。在具足夠磁碟／記憶體的指定主機先重新預檢，確認配置後以全新目錄實跑：

```sh
MAX_WORKDIR_BYTES=34359738368 uv run python -m scripts.benchmark --directory .runtime/benchmark-10m-next --users 100000 --events 10000000 --run
```

其餘CPU／RSS／時間限制仍採原設定；若超限必須保留failed紀錄，再依量測調整明示配置重驗，不能先宣稱會通過。通過需exit0、result.json status=passed、13階段、獨立真值及三格式hash一致，保存實測資源與全部設定。不得刪除客戶原始資料騰空。X04不豁免PH40其餘本地門檻。

## X02 進度：PH04

PH42現況補充：目前head為0017，PH41正式容器已真驗migration及211物件隔離還原。下段0001是PH04歷史狀態，不是目前部署目標；外部授權環境執行upgrade head後應以`uv run alembic current`確認0017（或後續已審核head），不能因基本migration成功就略過上傳、報告及重啟讀回。

本地 PostgreSQL migration、版本關聯、交易回滾及真服务重啟讀回已通過，見 evidence/PH04.md。缺少託管 DB 的指定目標與授權。補驗：在已確認、已備份且獲授權的目標設定 DATABASE_URL，執行 `uv run alembic upgrade head`；目前預期 Alembic revision 0001（後續以當時 head 為準），再於該環境驗證產品建立與重開報告。後者尚待產品流程完成，不能以 migration 成功取代端到端驗收。

## X02 進度：PH05

真本地 MinIO 的讀寫／重啟／條件寫入／multipart checksum／錯誤測試已通過，見 evidence/PH05.md。尚缺指定 AWS bucket、權限與 CORS 設定授權。已確認目標後，設定伺服器 S3 環境變數並執行 `uv run python -m scripts.storage_smoke --write-synthetic`；預期 status=passed 與 synthetic manifest，保留一個唯一驗證物件，不刪來源。此命令不建立 bucket、不驗 CORS／重啟／multipart。真瀏覽器上傳 CORS 與續傳補驗仍待 PH07 及 UI 完成，不能以基本 smoke 取代。

## X02 進度：PH07

本地正式上傳 routes 已以真 PostgreSQL/MinIO/HTTP 驗收（evidence/PH07.md）。外部已授權環境可按 docs/import_api.md 路徑進行 multipart、resume、complete、mapping、baseline 排隊並讀回；預期缺段／錯檔案拒絕、完整後 202 queued、封存不能改映射。AWS IAM 需含該 bucket/prefix 的 multipart 及 ListBucketMultipartUploads，以恢復未知初始化回應。瀏覽器 CORS 要允許實際團隊 origin 的 PUT/GET/HEAD 與必要簽名 headers；仍待 PH20 瀏覽器流程完成後在指定環境補驗，不以 TestClient 或 MinIO 通過宣稱 AWS 已驗。

## X02 進度：PH20

真Chrome→本地MinIO的presigned multipart PUT、跨來源存取、缺part／刷新／錯檔／續傳與映射保存均已驗（evidence/PH20.md）。未宣稱真AWS CORS通過。指定且獲授權的外部環境可使用前端 `/upload`，依docs/import_api.md上傳兩part以上的synthetic事件檔、刷新重選續傳，預期只補缺段且server完成hash校驗；錯檔及缺part顯示對應錯誤，保存映射刷新保持，最後POST baseline返回queued。後續Worker完成與雲端端到端仍需相關Phase及X03驗證，不能以目前排隊成功取代。

## X01 進度：PH26

PH42現況補充：PH27–36產品工具、真SDK測試模型、持久步驟及真Node SIGKILL恢復均已本地實測。取得明確付費授權後，除了下述provider smoke，需在正式工作區上傳明示合成資料並依docs/product_acceptance.md的四題逐題執行：3h窗口、美國分群、重疊及提高覆蓋率。預期工具參數／子run配置與問題相符，回答引用可定位至相同run/version的真產物，使用量及工具結果持久保存；重疊唯讀問題不新增計算分支，失敗不可顯示成功。真模型可能採不同工具順序，不能沿用測試模型的固定步數宣稱通過；保留實際結果與限制。未獲授權前不執行，也不從其他專案取得key。

正式ai7.0.94/provider3.0.0 adapter可build，SDK替身兩輪工具與邊界測試通過，未呼叫付費API。缺指定實測model/key及付費執行授權；不掃描其他專案憑證。

獲授權後在server環境設定OPENROUTER_API_KEY和OPENROUTER_MODEL，執行 `npm run build --workspace agent`，再 `node agent/dist/smoke.js --allow-paid`。只傳合成測試問題，預期status=passed、至少3個generation steps、兩次evidence結果及usage；失敗exit1，未明確opt-in exit2。此為真provider兩輪smoke，產品工具證據引用／恢復整合仍需後續PH27–36補验，不以smoke代替全產品驗收。當前只測不帶allow-paid拒絕路徑，X01保持pending_external。

## X03 部署與入口補驗

缺少條件：指定主機／區域、團隊網路、域名、TLS及建立服務的授權。PH41已完成正式image本地四問、容器重建、211物件隔離還原及internal拒絕；這不等於雲端部署。

取得授權後，先依docs/deployment.md在指定目標配置外部專用PG／S3與兩份600私密env；設定AC_SERVER_ENV_FILE、AC_AGENT_ENV_FILE絕對路徑及RELEASE_TAG，不把值提交或打印。確認維護窗口、空間與備份。從專案根目錄執行：

```sh
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d
docker compose -f deploy/compose.yaml ps
```

預期migration成功、四個常駐服務健康；仍須從指定TLS入口執行docs/product_acceptance.md的上傳→首報告→四題→三格式。未授權真模型時先完成baseline與匯出，X01保持pending，不把缺模型當作工具成功。記錄實際URL、image IDs、schema revision、run IDs、報告hash、各步結果與模型實際設定（不記key）。TLS／DNS依選定供應商配置，尚未指定前不捏造帳戶專屬命令。

入口必驗：瀏覽器無TLS警告；未授權網路不能存取此共享工具；`/internal`、`/%69nternal/agent/claim`、`/api/../internal/tools/get_baseline_report`、`//internal/agent/claim`不可繞過proxy（本地期望404）；不能只驗health便公開流量。

同一已確認Compose project，在維護窗口用`docker compose -f deploy/compose.yaml up -d --force-recreate`重建，預期同run三格式及對話保持。依docs/backup_restore.md備份、verify、還原到另一組全新空PG／bucket，重開原run逐byte/hash比較；不得對現有目標restore或down -v。全部實證通過才更新X03，不以本地結果代填。

## X05 客戶資料與商業效果補驗

缺少條件：客戶授權的去識別log、來源完整性／時區／收益回傳時間確認、資料保存與模型傳輸政策，以及投放實驗安排。不要使用local_workspace的trust-auth合成入口存放正式客戶資料。

1. 先依PRD資料合約確認App／user／event識別、安裝／重裝定義、complete_through、幣別、收益修正、available_at與來源順序。映射未知就留未知，不自行捏造時間或收入。
2. 在已授權的正式私有工作區從`/upload`建立新dataset，依docs/import_api.md上傳CSV／Parquet及映射。預期大小／SHA256一致、原始檔保留、重複／衝突／缺值品質報告可追溯；資料不合格可以診斷報告結束，不以強行產出推薦為通過條件。
3. 等Python完成後，从`/history`重開同run，核對D7成熟分母、零事件用戶、來源收益抽樣手算、候選首次可觸發時間與證據卡。下載所選版本HTML／JSON／CSV，預期相同run/version與数值；保存不含原始ID的交付報告及驗收紀錄。
4. 模型傳輸得到明確授權才啟用Agent；只傳工具聚合證據，不能把全量log貼進對話。既有結果揭露後重跑維持exploratory；新批次固定舊規則重驗，重疊用戶不能洗掉污染。
5. 若要宣稱投放提升，另由廣告主設計與執行獨立campaign A/B實驗，事先約定主要指標、期間、樣本及停止規則。記錄實際平台與結果，不從歷史ARPU倍數推導ROAS提升；本產品不自動建立或執行campaign。

本項主要是人工來源核對及產品UI操作，不存在能自動證明客戶資料真實或投放因果的單一CLI。需保存每步實際觀察及失敗原因；X05未通過不阻擋本地軟體交付，但對外不宣稱真客戶驗證或商業效果。
