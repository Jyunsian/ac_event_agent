# V3 全量描述與 Holdout 證據分層

日期：2026-09-11

## 決策

- 主表與 CSV 使用全部 D7 成熟玩家，回答本批資料的描述性行為關聯。
- Holdout 保留為探索後凍結條件的額外重現檢查；任一組少於 100 人時只標示 Holdout 樣本不足。
- 全量觀察與 Holdout 狀態分開保存；不引入模型訓練或交叉驗證。

## 實作

- `server/analysis/casual_validation.py`：每個候選新增 `observation.scope=all_mature_users`、全量 membership 與 D2／D3／D7 描述比較；原 holdout inference 保留。
- `server/analysis/catalog_v3.py`、`server/analysis/report_v3.py`：主表、價值圖與 CSV 投影改讀全量 observation；holdout evidence status 保留。
- 完整全量 observation 保存在逐候選 detail；主報告 index 不重複內嵌 2,000 份，以維持既有 16 MiB 讀取上限。
- `web/src/`：主表明示「本批觀察」，Holdout 只顯示額外重現、未重現或樣本不足。

## 驗證

- `uv run pytest -q tests/test_v3_validation.py tests/test_v3_catalog.py tests/test_v3_exports.py tests/test_v3_revenue_decomposition.py tests/test_v3_pipeline.py`
- `npm run build --workspace web`
- `npm run test:web-model`

首次受影響回歸：Python 10 passed、2 warnings；Web model 20 passed；Web production build 通過。新增斷言要求全量 observation 的成熟用戶分母大於 holdout 分母。

## 真實本地重算

- Synthetic dataset：`f2c148d7-1afa-4719-b4b8-ed9c302e5890`
- Run：`150ab937-6dc6-400a-9056-92e3f001882b`，狀態 `succeeded`，報告 v1。
- 報告 index：15,312,045 bytes，低於既有 16 MiB 上限。
- 第一個優先候選主表分母為全部 2,200 位成熟玩家（208 符合、1,992 未符合）；其 Holdout 仍為 54／606，證明兩層沒有混寫。
- 因同一批 synthetic user identity 已在先前 Run 曝露，本次 Holdout 正確標示 `USERS_OVERLAP_EXPOSED_DATA`／尚未獨立驗證；本批全量觀察仍正常顯示。
