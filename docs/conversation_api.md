# 對話 API（PH25–PH28 本地已驗）

需要本地正式PostgreSQL/S3與已發布baseline。Node Worker 已接唯讀 Agent runtime；真 OpenRouter 模型仍待 X01。202 queued 不代表 Agent 已執行。

- `POST /api/runs/{baseline_run_id}/conversations`：帶Idempotency-Key，201回id/baseline_run_id/next_seq/created_at。baseline未ready409；先核對可讀報告hash與身份，不建立空假對話。
- `POST /api/conversations/{id}/messages`：帶Idempotency-Key；JSON `content`（非空白，最多20000字元）、`selected_run_id`、可選`selected_candidate_id`（最多256字元）。selected run必須屬同root且ready；候選必須出現在該報告。202回turn_id/message_id/seq/status=queued/context。
- `GET /api/conversations/{id}/events?after=0&limit=100`：limit1–200，after非負；回events、next_after、has_more。while has_more使用next_after讀下一頁，沒有新事件時cursor保持不變。404表示對話不存在，不建立新對話。

同key同payload回原response，同key不同payload409。對話row lock排序送出，message/turn/event/next_seq/api_requests在同交易提交；驗證失敗不耗序號。messages/events不可update/delete。turns有單conversation最多一個running的partial unique index。排隊消息不會修改baseline run的成功狀態。

Agent隊列核心為 `server.agent_queue.AgentQueue`：claim以conversation row的SKIP LOCKED協調，僅選最早queued/running turn；running租約未過期不跳過去跑後續訊息。預設90秒、3次attempt；heartbeat續租，過期重領提升fence；舊worker不能finish。到達重試上限產生turn_failed，下一輪可領後續turn。finish原子寫assistant message及message_created/turn_succeeded事件，不改baseline狀態。Node Worker 經下列內部 HTTP 橋接操作；不要以手動改DB狀態作正式執行方式。

事件seq是conversation的全域序號，不是只計user訊息；turn ordinal保存送出當下seq，因此後續有狀態事件時ordinal可以有空隙，順序仍唯一且單調。context 只讀目前問題和成功的前序 turn，排除尚排隊的後續問題及失敗 turn；超過100則訊息或256000 UTF-8 bytes時明確失敗，不默默截斷。

## PH28 操作與 Node Worker

- `GET /api/runs/{baseline_id}/conversations`：最近100筆對話，恢復工作區用，不在 GET 建立新對話。
- `GET /api/runs/{run_id}/references/{artifact_id}?version=1&pointer=/candidates/0`：核對已發布版本與 artifact，再回可定位的 candidate_id/tab；無效指標拒絕。只接受 summary/candidates/overlap。
- 工具事件 `tool_running/tool_completed/tool_failed` 帶 tool_call_id/fence，UI 以 attempt+call 分組呈現；事件不保存原始 log 或任意錯誤 body。這不是 PH36 的完整 SDK 步驟恢復。

- `GET /api/conversations/{id}`：近期100個 turn 狀態；完整歷史讀 events cursor。
- `POST /api/turns/{id}/cancel`：帶 Idempotency-Key；取消 queued/running，提升 fence，保留原問題和事件。
- `POST /api/turns/{id}/retry`：帶 Idempotency-Key；只允許 failed/cancelled，新 turn 排在隊尾，沿用原問題、版本及候選。不覆寫原 turn；同一原 turn 重複重試回同一子 turn。
- `GET /api/agent/status`：後端探測 Node health，只回 available/code。未設定模型、Worker 離線或未連上 API 均不可用；configured 不代表真模型已驗證。
- `POST /internal/agent/claim`：Bearer AGENT_INTERNAL_TOKEN；JSON worker_id，回 claim 或 null。
- `POST /internal/agent/{context|heartbeat|finish|fail}`：同 Bearer，JSON turn_id/worker_id/fence；finish 加 content，fail 加 error_code。過期或取消的持有者回409，未知錯誤碼清洗為安全代碼。

伺服器端設定 AGENT_INTERNAL_TOKEN（API/Node 相同）、AGENT_API_BASE_URL（Node 到 FastAPI，不經前端 proxy）、AGENT_HEALTH_URL（FastAPI 到 Node），以及 OPENROUTER_API_KEY/OPENROUTER_MODEL（僅 Node）。然後 `npm run dev:agent`，或 build 後 `node agent/dist/index.js`。正式環境仍需 PH41 入口限制，不將 internal routes 公開到網際網路。

Node 每20秒續租；取消或續租失敗中止模型，失去租約後不提交。模型失敗只保存 allowlist 錯誤；缺模型設定時不領取工作。SIGTERM/SIGINT 中止呼叫、保留未完成租約供後續恢復。自訂測試模型僅由測試程式注入，不設 production fake-model 開關。工具逐步持久化／重放仍待 PH36。
