# AC Event Agent MVP — 本地交付報告

日期：2026-09-09。產品版本0.1.0，資料庫0017。PH01–PH42全部本地門檻通過；最終簽核見[狀態表](../PHASE_STATUS.md)及[PH42證據](../evidence/PH42.md)，不代表正式上線。

## 結論與邊界

| 項目 | 實際狀態 |
|---|---|
| 本地功能 | 上傳→Python首報告→Agent工具→分支→三格式匯出已真端到端驗證；資料服務、背景任務與恢復均非mock。 |
| 真模型 | Vercel AI SDK＋OpenRouter正式adapter已實作；目前驗收使用明示SDK測試模型，未呼叫真OpenRouter。X01待key、模型及付費授權。 |
| 雲端 | 三個正式Docker images本地演練通過，未部署雲端／DNS／TLS，託管PG／AWS S3尚未驗。X02／X03。 |
| 真資料 | 僅合成資料，未驗真客戶log或投放效果。X05。 |
| 容量 | 10萬及100萬事件的一般／寬ID、偏斜、亂序、10%重複情境完整通過；1000萬在1536MiB RSS配額下MEMORY_LIMIT，不能宣稱支援1000萬。X04。 |

純IAA D7 `[install,168h)`；包含小時與天級窗口、頻次／價值／回訪／時長、有限AND／OR／序列搜尋。輸出是歷史候選與測試依據，不是保證投放提升。未加入登入、會員、多租戶、IAP、ROI或投放自動化。

## 開始使用與交接入口

- [README](../README.md)：依賴、檢查、生成合成資料與入口。
- [本地持久工作區](local_workspace.md)：init一次、serve／exec啟動、停止後重開；只供本機合成資料，PG trust auth不適用客戶正式環境。
- [正式部署](deployment.md)：三images、Compose、外部PG／S3、私密env、migration與健康檢查。無登入的共享工具不可匿名公開。
- [資料匯入](import_api.md)、[完整產品流程](product_acceptance.md)、[客戶報告交付](report_delivery.md)。
- [備份還原](backup_restore.md)、[Agent恢復](agent_recovery.md)、[容量](capacity.md)、[外部補驗](../EXTERNAL_CHECKS.md)。
- [需求追蹤](traceability.md)與[現行證據審核](release_audit.md)：逐需求→Phase→具體assert／命令／產物。

## 主要留存證據

正式容器：`.runtime/deployment-e2e-2jkwb3kn/result.json`，真Nginx入口上傳、四問、三分支及下載；force-recreate與211物件隔離還原後，六份父子報告hash一致。桌面與手機截圖在同目錄visual。三images：

| Image tag | 已驗image ID（SHA256） |
|---|---|
| ac-event-python:ph41-local | a42c8e42c15ed64c866b6eaa6d8bc8e13d50410f77e92bf45f06e4bfd70a9ffe |
| ac-event-agent:ph41-local | 1e99d7c131797e5147c7178cbb30a31f781e2df87637c23cdb858e6f968e9d26 |
| ac-event-web:ph41-local | 9f005fe0961bdca5de30f3b7466166543df697211e884120012c2e9792b95e8a |

本地常駐CLI：`.runtime/local-workspace-flow-8ba3cf75/product-acceptance.json`；實际migration／API／Python／Node／Vite／Chrome，正式無key入口後明示SDK替身四問，全部停機後重開同PG／S3與API，四turn／三branch／六報告hash保留。

離線普通與分群匯出：`.runtime/report-delivery-xsng5__g/`、`.runtime/report-delivery-rdzffo0m/`；關閉API後離線重開HTML，各表與JSON逐值相同、無外部請求。整個.runtime含私密設定與原始資料，**不能當客戶交付包分享**；客戶只收選定版本的正式HTML／JSON／CSV。

容量四份結果：`.runtime/benchmark-100k-001/result.json`、`benchmark-1m-001/result.json`、`benchmark-stress-100k-001/result.json`、`benchmark-stress-1m-001/result.json`；皆13階段與獨立真值校驗。100萬一般計算158.92秒、峰值RSS約607MiB；壓力186.54秒、約874MiB，僅compute子程序，不是全系統峰值或SLA。失敗1000萬紀錄另存`benchmark-10m-001/result.json`。

## 已知限制與安全使用

- 原始資料、報告、分支不可變；修正資料建立新dataset，不覆寫舊版。沒有自動保留期或清理政策，需監看磁碟與備份。
- 相同用戶／已揭露驗證資料的新分析保持探索性；經驗庫新批次固定舊規則重驗，反例會保存。這是證據更新，不是模型權重訓練。
- 未知收益不補零、未成熟不當低收益；小樣本可以不推薦。schema與來源ID品質仍需客戶確認。
- 引用校驗證明來源存在且scope正確，不保證真模型敘述語意；真模型需X01逐題驗收。
- Worker資源監視是取樣，不等於所有部署平台的OS硬隔離；Compose另有容器配額。健康端點不是資料及模型全鏈路成功證明。
- 備份需維護窗口、可信archive及空的隔離目標；含原始資料及對話，需私密保存。限制見備份手冊，禁止直接覆寫已有目標。
- 已知非阻斷警告：Starlette/httpx與anyio棄用警告、ECharts lazy chunk大小提示；沒有為消除警告而放寬測試門檻。

## 重現與下一步

`npm run check`是完整開發檢查入口。PH38原全套曾有一個可及性locator失敗，修復後只重跑受影響用例；PH42再按版本及風險補验，具體結果見release_audit，不把第一次全套exit1改寫成成功。

下一位操作者先讀狀態表和外部清單。沒有key也可使用基礎報告；獲授權後才執行真模型smoke與四題產品驗收。指定正式網路入口／雲端後才執行外部部署；不得把本地成功改稱已上線。
