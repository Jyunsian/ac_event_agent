# V4 五個判斷面向與 mock 更新

2026-09-17：使用者授權實作，完成本次相關驗證。

- 正式 Web：`web/src/report-v4.tsx`、`v4-presentation.ts`、`style.css`。主表同時間呈現價值、覆蓋與未知人數、首次達標中位數／九成時間、收入對照及兩項 holdout 結論。snapshot 不宣稱精確首次時間；探索狀態不標驗證支持。點開補上七天總收入、收入占比、已發生／之後收入、holdout 人數、平均差與重抽樣 95% 範圍；範圍不是多重比較校正後區間。
- 所有完整比較的分頁 API：`server/candidate_reader.py` 只投影所選時間點，沿用已保存產物；不重算門檻、優先清單或統計決策。`read_tools.py` 不把新增 UI 詳細欄位塞入 Agent 大量搜尋結果，保留原聚合限制。
- `web/public/mock-v4.html`：五面向 mock、明確的全量／holdout 切換、帶期限的行為說明及假設區間。數字與檢驗狀態皆為示意。同步 `.runtime/v4-mock-public/index.html`，公開 Quick Tunnel 只供此示意頁。
- 舊報告產物與分析算法未改寫；本次不重新宣稱容量或整個歷史平台全套回歸。

驗證：

- `npm run build --workspace web`：通過，既有圖表 chunk 大小警告保留。
- `npm run test:web-model`：23 passed，包括新增 V4 時間／證據狀態測試。
- `.venv/bin/python -m pytest -q tests/test_v4_pipeline.py tests/test_v3_backward_read.py`：6 passed，69.90s；兩個既有棄用警告。
- 增加 48h API 投影斷言後，單獨重跑 `tests/test_v4_pipeline.py::test_v4_agent_aggregate_numbers_and_discovery_download`：1 passed，8.67s（包含於上列六測試，不重複計數）。
- `scripts/v4_browser_qa.cjs`：正式 ReportPanel，1440／390px；主表七欄、48h、明細六時點、holdout、144h 控制、checksum 與無頁面溢出／JS 錯誤。證據 `.runtime/v4-five-axis-qa/`。正式計算 fixture，API 真服務另由上述 Python 驗證。
- Mock Playwright：1440／390px、五面向、48h 人數、holdout、rolling、示意區間標示、無頁面溢出／JS 錯誤；`.runtime/v4-five-axis-mock/checks.json`。
- 公開頁 `https://group-walter-guam-acres.trycloudflare.com/?v=five-factors`：HTTP 200、五面向與 48h 互動通過；1440px 主表不需橫向捲動。公開連結是臨時通道，不是正式部署。
