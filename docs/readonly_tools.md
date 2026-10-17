# Agent 唯讀工具

`POST /internal/tools/{name}` 僅供內網Agent服務，Authorization: Bearer使用server `AGENT_INTERNAL_TOKEN`。不得將token交前端或模型。無登入／會員系統不等於公開內部API；部署需封鎖public `/internal`。

Envelope：turn_id、parent_run_id、worker_id、fence、tool_call_id、arguments。除了arguments，皆由Worker持久claim提供；model不能指定run/dataset/object_key。有效租約前後各檢查一次，報告綁turn.report_version，不讀隨時變動的latest。

- profile_dataset：arguments={}；聚合品質、完整期、成熟／未成熟計數及受限分布。分布每格至少20users，每dimension最多10格；省略不是零。
- get_baseline_report：arguments={}；當前turn已發布報告中的候選metrics/spec/reasons，不建立計算job。
- compare_candidates：arguments={candidate_ids:[...]}，1–10個本報告ID；比較既有數值與探索重疊，分開標示cohort，不重算。

返回run/dataset/report_version/synthetic/content/references，128KiB上限，不回S3 key或原始用戶log。reference由實際report artifact UUID、checksum和精確JSON pointer組成。

正式入口`runReadonlyAgent`收集這次實際讀到的reference集合，完成後檢查回覆引用，無引用或錯引用拋AGENT_REFERENCE_INVALID，不交付未驗證文字。這只證明引用存在且屬已讀產物，不是LLM語意正確性／因果效果保證。完整UI和持久worker提交流程在PH28接通。

驗證：`npm run test --workspace agent`；`uv run pytest tests/test_read_tools.py -q`。後者用真PG、MinIO、baseline Worker與HTTP，再由真ToolLoopAgent+官方測試模型呼叫三工具；不會呼叫付費模型。
