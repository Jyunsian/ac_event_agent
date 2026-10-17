2026-09-17 最新授權：首次全部部署 Railway；共享密碼、獨立空白資料庫＋合成示範、US$50/月目標（模型另計）。狀態以 evidence/RAILWAY-DEPLOY.md 為準，以下舊部署目標保留歷史。

Railway 已實際部署並通過本輪技術驗收；目前操作請用 [Railway 操作紀錄](RAILWAY_OPERATIONS.md)，驗收見 [部署證據](../evidence/RAILWAY-DEPLOY.md)。下列「尚未部署」為歷史紀錄，非目前狀態。

# 正式部署包與本地演練

最新部署目標（2026-09-09使用者確認）：前端Vercel、後端Railway，測試完成後再部署。本手冊現有Compose是已驗本地／自管容器方案；Vercel／Railway適配與部署尚未執行，不能直接把以下命令當成該平台部署指令。模型先選OpenRouter `z-ai/glm-5.3-flash`；PG／S3供應商及入口保護待確認。參見EXTERNAL_CHECKS最新決策。

PH41本地正式images／資料持久性演練已通過，證據見evidence/PH41.md與`.runtime/deployment-e2e-2jkwb3kn/result.json`。PH42本地交付審核亦通過；X01真模型、X02託管持久服務、X03雲端/DNS/TLS尚未驗證，不宣稱已上線。

## 拓撲與保護邊界

Compose提供Nginx靜態前端／同源API代理、FastAPI、Python Worker、Node Agent及一次性migration。PostgreSQL與S3由外部持久服務提供，不把原始資料放在容器layer。worker-scratch為具名暫存volume，丟失時應從已提交物件checkpoint重算，不是資料備份。

只有web發布主機port，預設127.0.0.1:8090。API／Agent不發布port；proxy拒絕`/internal`和其子路徑。內部API仍驗證機器token。這不是登入或使用者隔離：任何能連到前端的使用者共享所有專案，正式環境必須在授權團隊網路內，TLS由指定入口配置。不要把匿名共享工作區直接公開到Internet。

## 配置與建置

1. 複製deploy/server.env.example與agent.env.example到build context以外的私密位置，設定檔權限600。填入已授權PG／S3連線；兩檔AGENT_INTERNAL_TOKEN使用同一高熵秘密。只在agent檔配置OpenRouter；沒有key仍可產出Python報告，Agent顯示未配置。
2. 設定AC_SERVER_ENV_FILE與AC_AGENT_ENV_FILE為這兩個檔案的絕對路徑。不要輸出完整`docker compose config`或容器inspect環境，避免洩漏秘密。秘密僅在runtime注入，Dockerfiles不接收secret build args；.dockerignore採allowlist排除原始log、.runtime、.env與備份。
3. 確認空間與RAM：先`docker system df`和主機`df -h`，不執行prune。計算預設2GiB容器／1536MiB RSS、DuckDB256MB、2threads；API512MiB、Agent384MiB、web128MiB，尚須預留Docker VM、持久服務與建置需求。主機低空間不等於可任意刪除舊資料。

```sh
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d
docker compose -f deploy/compose.yaml ps
```

可設定RELEASE_TAG指定本次image標籤、AC_HTTP_PORT改主機port。正式入口是Nginx build產物，不是Vite dev或preview。migration成功後才启动API／Worker；API liveness成功後啟動Agent與web。這些healthcheck不是資料庫／S3／真模型完整readiness證明，仍須執行上傳與報告整合验收。Compose不因unhealthy自動重啟程序；restart策略只處理退出，監控需保留health告警。

Python Worker額外保存/tmp/worker-health.json（tmpfs、0600）：主程序成功claim查詢（含空佇列）或續租才原子更新，healthcheck要求紀錄45秒內且PID仍存在。DB故障／主程序卡住不會由無條件背景thread維持假健康。這是supervisor與近期DB連通觀測，不代表S3可用或任務結果正確；取消／停止後PID消失或紀錄過期即不健康。未設定WORKER_HEALTH_FILE的既有本地啟動行為不變。

## 必須演練後才可宣稱通過

本地macOS Docker Desktop的隔離演練入口（需先以ph41-local標籤build三個images）：

```sh
uv run python -m scripts.deployment_acceptance --tag ph41-local --run
```

該命令已在PH41實跑exit0。它使用新的本機PG／MinIO、唯一Compose project、私密runtime env與Chrome host-resolver規則，先啟動正式Agent入口，再以明示SDK測試模型替換決策；正式SDK／工具／Python仍在images執行。UI四問、六份父子報告hash、重建容器後一致性均通過；維護窗口備份後還原到另一組全新PG/S3（211物件），改runtime連線重新建立相同正式容器，六份報告仍一致。結束只stop自身project，不delete／prune；保留.runtime/deployment-e2e-*及其私密設定，不可分享整個目錄。這個helper不是雲端部署指令或真模型驗證。

演練先檢查主機至少3GiB可用（2GiB保留＋1GiB手算fixture演練餘量），不足就不建目錄或服務。此門檻不是容量承諾；容器磁碟監視仍生效，操作時也需觀察主機backing disk，不能只看Docker VM內部df。不得藉降低保留空間或擅自刪資料強行通過。

- 以隔離PG與S3上傳合成資料，正式images計算報告；查看前端、API、兩Worker狀態與報告三格式。
- 重建本專案容器後同run／report hashes仍一致，不執行down -v或清空外部服務。
- migration及回復需維護窗口與可校驗備份；不得對未知既有DB直接試downgrade。備份合約及信任邊界見docs/backup_restore.md。上述正式image演練已驗Alembic 0017與隔離備份還原，不代表任意未來schema版本可直接downgrade。
- 從唯一公開port請求internal routes必須拒絕；驗查image內容與前端bundle沒有runtime secrets。模型替身必須明示，不改正式OpenRouter adapter冒充真模型。

依據：[Docker production](https://docs.docker.com/compose/how-tos/production/)、[Compose啟動順序](https://docs.docker.com/compose/how-tos/startup-order/)、[uv Docker](https://docs.astral.sh/uv/guides/integration/docker/)。Python使用鎖檔且排除dev套件；Node使用package-lock與分階段build。實際build成功、版本與image digest在evidence記錄，不將文件當執行證據。
