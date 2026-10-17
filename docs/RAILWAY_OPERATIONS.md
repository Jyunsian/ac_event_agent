# Railway 操作紀錄

正式入口：https://web-production-ac81b.up.railway.app
專案：dc58eb6f-bd60-42a2-9135-5ea95b028a35；環境：production / 5b35b2a1-b283-4688-80c6-385c8cbd697d。
驗收狀態：evidence/RAILWAY-DEPLOY.md。登入資料不在本文件。

## 架構

web（唯一公開入口）→ api；worker 與 agent 經私有網路讀取任務；Postgres 與私密 Bucket 保存資料。全部新加坡。backup 每日 UTC 19:00 執行 pg_dump，僅刪除 database-backups/production/ 前綴超過七日的備份，不刪原始上傳與分析產物。

前端用 Nginx Basic Auth 保護頁面及 /api；/healthz 不含資料且免密碼，/internal 一律拒絕。入口 hash 與內部 token 是不同憑證。API 不接收瀏覽器 Basic Auth 憑證。前端 /api 路徑保持平台中立。

## 發布

使用 scripts/prepare_railway_release.py 建立全新 allowlist 發布目錄；從該目錄 railway link 到上述專案與 production，之後 railway up --service api/web/worker/agent --detach。勿直接從工作目錄上傳 .runtime、.env、原始客戶資料或 node_modules。

Railway 5.57.7 的 environment edit 在非 TTY 會優先讀 stdin；批次更新應透過 stdin JSON 或官方 GraphQL，不能把「No changes to apply」當成成功。railwayConfigFile API 已停用，deploy/railway/*.json 是本次服務配置參考，不宣稱會被自動套用。實際服務指定 dockerfilePath，Dockerfile 不使用 DOCKERFILE Builder enum。

API：deploy/python.Dockerfile；pre-deploy alembic upgrade head；8080、/api/health。
Worker：同 Python Dockerfile；start python -m server.worker；無公開 domain。
Agent：deploy/agent.Dockerfile；PORT 與 AGENT_PORT 均 8081，/health；AGENT_API_BASE_URL 指向私有 API。
Web：deploy/railway/web.Dockerfile；PORT 8080，/healthz；API_UPSTREAM 指向私有 API，WEB_AUTH_HTPASSWD 由私密變數提供。
Backup：deploy/railway/backup.Dockerfile；單次工作，cron 0 19 * * *，不重啟成功退出的工作。

Postgres 16 /var/lib/postgresql/data 掛載持久磁碟，PGDATA 子目錄 pgdata。DATABASE_URL 必須使用 postgresql+psycopg scheme（備份接受普通 postgresql）。Bucket CORS 只允許正式網站，暴露 ETag 以支援分段上傳。更換前端網域時同步 CORS，不開啟 *。

## 恢復與費用

維持 Worker RSS 1536 MiB、DuckDB 256 MiB、2 threads、工作目錄4 GiB、保留2 GiB、CPU600秒、單次900秒。平台 worker 2 CPU／2 GiB，單一副本；休眠關閉，避免背景任務無人處理。

更版前記錄部署 ID。程式可回退至前一個通過驗收的部署；不要用 alembic downgrade 當作任意資料庫回滾。先備份，再在獨立資料庫演練 restore。備份與檢查點都不是「只要HTTP200就正常」的證據。

US$50/月是本專案目標，非固定帳單。以 railway usage projects 與 metrics 觀察；不要把整個 workspace 的硬上限改成50元，因為該 workspace 有其他專案。模型消耗另外計費。未設定任何自動清除客戶原始檔的政策。

## 本次雲端相容修正

- Railway 入口可能壓縮 HTTP 回應並把 ETag 改為弱格式。Web 接受帶 `W/` 的同一個 SHA-256，但仍重新計算解壓後內容的雜湊；缺失或不符一律拒絕。
- API 的 JSON 主報告維持 16 MiB 上限。CSV／HTML／完整搜尋匯出先下載到獨立暫存檔並校驗 SHA-256，再以 64 KiB 區塊傳送；完成或中斷清理暫存檔。磁碟必須仍有 512 MiB 餘量。
- Nginx 從容器 `/etc/resolv.conf` 取得 resolver，每 10 秒更新 API 私有名稱解析，避免後端重部署換位址後仍連到舊容器。
- V4 優先清單已隨主報告取得；只有點「全部完整比較」才讀分頁，切換時間不預取無關完整清單。
- Agent 依所選時間點的收入關聯檢驗解釋 Holdout；不能用規則整體狀態取代單一時間點的通過結果。

## 備份還原演練

本次以備份服務實際產生的 S3 dump 還原至 `ac_event_restore_check`，不覆寫 `ac_event`。33 個資料表、成功分析及報告雜湊均已確認。備份只含 PostgreSQL；原始檔及分析產物仍依 DB 保存的 object key / SHA-256 從私密 Bucket 讀取，因此恢復時也需保留 Bucket 及其憑證。

容量測試另外使用 `ac_event_acceptance`；這兩個驗收資料庫沒有接入正式 Web 的分析列表。測試來源全部為合成資料。
