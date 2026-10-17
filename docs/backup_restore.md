# 備份、隔離還原與故障處理

工具：`uv run python -m scripts.backup_restore`。本版是有維護窗口的整個共享工作區備份，不是不中斷服務的增量備份。DB 與專用 bucket 應屬於同一工作區；不得指向其他專案共用 bucket。備份包含原始資料與對話，不能當作可公開分享的客戶報告。

## 備份前

1. 確認正確的 DATABASE_URL、S3_BUCKET、S3_ENDPOINT_URL／region 與憑證已在程序環境；不要把密碼寫入命令、日誌或提交版本控制。
2. 阻止新流量；讓現有上傳與任務結束，再停止 API、Python Worker、Node Worker，僅操作已確認屬本部署的程序／容器。不要以模糊名稱 pkill 或停止其他專案服務。
3. 保持 DB／S3 服務可用。工具會拒絕 queued/running jobs、queued/running Agent Turns 或 uploading uploads；不能用改資料庫狀態來繞過。未完成工作先用正常產品流程處理，或另安排維護時段。
4. 本地預備足夠磁碟；備份目錄必須不存在，其父目錄由操作人員預先建立。使用與來源相容的 PostgreSQL pg_dump/pg_restore 工具，經 PATH 或 `--pg-bin` 指定。不可對未知 DB 進行操作。

```sh
uv run python -m scripts.backup_restore backup --directory .backups/workspace-001 --maintenance-confirmed
uv run python -m scripts.backup_restore verify --directory .backups/workspace-001
```

備份持有所有 public table 的 SHARE lock，阻止工作區 DB 寫入；pg_dump 使用同一 exported snapshot。資料以 custom archive 保存；bucket 物件逐檔串流複製並核對大小／SHA256，DB 中的完整物件引用也須出現在備份且 hash 相同。manifest 包含 schema revision、各表筆數及物件清單，不含憑證。只有全部完成且 fsync 後才留下 COMPLETE 校驗標記。

若失敗，保留 partial 目錄供檢查；沒有有效 COMPLETE／完整校驗就不能算成功備份。再次備份請指定新目錄，工具不覆寫、不自動刪除。完成後由操作人員恢復精確服務及入口流量。

## 還原到全新隔離目標

1. 先驗證備份；只接受自己控制、可信來源的 archive。SHA256 可偵測損壞，**不代表來源可信**；pg_restore 會執行 archive 內 SQL，禁止使用未知第三方備份。
2. 預先建立全新空資料庫和空 bucket，設定目標程序環境。DB 不先跑 migration；bucket 的權限、CORS、加密及生命週期需依部署另設，資料備份不包含雲端 IAM／DNS／TLS。
3. 不開 API／Workers，不讓其他人寫入目標。工具拒絕非空 DB、非空 bucket 或既有 multipart upload。沒有 `--clean`、drop 或自動覆蓋路徑。
4. 明確切換到目標設定後執行：

```sh
uv run python -m scripts.backup_restore restore --directory .backups/workspace-001 --maintenance-confirmed --trusted-backup
```

還原先校驗全部備份檔，再將物件 conditionally put 到空 bucket；DB 用單一交易 restore，任何 SQL 失敗不能留半套 schema/data。完成後核對 schema revision、所有資料表筆數以及物件 hash。若物件階段失敗，目標可能有部分物件；保留供檢查並使用另一個全新隔離目標，不自行清空或覆蓋。

5. 啟動目標 API（先不開對外流量），讀 `/api/runs/<原run-id>/view` 及三種 `/api/runs/<原run-id>/reports/1/{html,json,csv}`。須 ready、身份一致，且 bytes/hash 與備份前相同；重開原對話也應一致。確認來源仍可用且未變。實際切換正式流量需部署授權，不由本工具完成。

## 已知範圍與限制

- 不支持備份活動中的任務／未完成上傳，避免把暫時 multipart ID 或 active lease 移到新服務。
- 目前逐物件還原使用條件式 single PUT，单物件上限 5 GiB；超限在目標寫入前拒絕。manifest 上限16 MiB；不把此工具當作無界容量方案。
- 備份保存資料及 schema，不保存 DB 角色／密碼、雲端資源設定、程式 image 或外部 API key。發布時需同時保存相容應用版本。
- 備份不自動加密，目錄權限0700；正式備份應另使用存取控制和加密磁碟／加密儲存。不要上傳到公開bucket或提交Git。
- 備份和還原不刪資料。可重建 Worker 暫存的 retention 在容量／部署階段另定，原始來源與已發布產物不可自動清理。

## 故障處理

| 故障 | 系統行為與操作 |
|---|---|
| DB 中斷 | API 返回503 DATABASE_UNAVAILABLE；Worker無法領取／續租時不發布假成功。恢復DB後重開原報告，過期租約由新Worker接手 |
| 物件服務中斷 | API返回503 STORAGE_UNAVAILABLE；計算有界重試，未完成報告不可ready；恢復儲存後沿原run重試 |
| Worker SIGKILL／租約過期 | 原fence無權發布，替代Worker接手；Node工具／step journal維持同一tool ID及已提交子run，見agent_recovery.md |
| 磁碟滿／quota耗盡 | 計算返回DISK_FULL且不自動無限重試；先處理專用暫存容量，再以正常重試入口恢復；不刪原始資料 |

## 可重現本地驗收

```sh
uv run pytest tests/test_backup_restore.py tests/test_system_faults.py tests/test_worker.py -q -s
```

使用獨立真 PostgreSQL／MinIO，實際停止並重啟持有的服務；磁碟滿在正式檔案配置邊界注入 OS ENOSPC，不灌滿使用者主機。故障注入不進入正式 CLI。程式存在不代表 PH39 全部完成，門檻與實際命令結果見 evidence/PH39.md。
