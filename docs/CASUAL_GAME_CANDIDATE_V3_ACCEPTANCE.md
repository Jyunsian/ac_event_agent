# Candidate Event V3 驗收追蹤與產物合約

狀態：CG01–CG05 passed；CG06 `closed_partial`。固定 100k／20k／2k Gate 已通過，但最終 source 的全套回歸依使用者收尾指示停止，詳見 `evidence/CG06.md`；不把部分回歸冒充 passed。

## 固定合約入口

- JSON shape：`contracts/casual_game_v3.schema.json`。
- Python semantic contract：`server/analysis/v3_contract.py`。
- V3 config：`analysis_version=3.0-casual-game`、Discovery ≤ 20,000、Validation ≤ 2,000、priority ≤ 10、bootstrap=1,000。
- Candidate identity：canonical JSON 的 SHA-256，涵蓋 Category、indicator、observation、trigger mode、predicate、threshold、direction、denominator 與 sequence constraints。
- Artifact identity：run、dataset、analysis version、pipeline、feature、policy 與全部上游 checksum。
- 原始事件 identity：`(app_id,event_id)`；Level attempt identity：`(app_id,user_id,level_id,attempt_id)`。
- 未知值為 null，不等於 0；未完整觀察不等於 false；同時間無可靠順序不配對。

## Phase 驗收索引

| Phase | 必須證明 | 權威證據 | 狀態 |
|---|---|---|---|
| CG01 | V3 schema、AST、identity、Level ingest、舊 IAA 相容、手算 fixture | `tests/test_v3_contract.py`、`tests/test_v3_ingest.py`、`evidence/CG01.md` | passed |
| CG02 | Capability、Retention、Level progress/friction、pairing、first-match/snapshot、sequence | `tests/test_v3_quality.py`、`tests/test_v3_features.py`、`tests/test_v3_sequences.py`、`evidence/CG02.md` | passed |
| CG03 | 20k Discovery、去重、sample filter、Pareto/diversity、Category quota、2k freeze | `tests/test_v3_search.py`、`tests/test_v3_selection.py`、`tests/test_v3_freeze.py`、`evidence/CG03.md` | passed |
| CG04 | holdout 全家族、bootstrap/Welch/Holm、D2/D3/D7、source/day、recovery | `tests/test_v3_validation*.py`、`tests/test_v3_revenue_decomposition.py`、`evidence/CG04.md` | passed |
| CG05 | catalog/detail、完整匯出、72h 圖、offline、Agent read-back、desktop/mobile | `tests/test_v3_catalog.py`、`tests/test_v3_exports.py`、`scripts/v3_report_browser_qa.cjs`、`evidence/CG05.md` | passed |
| CG06 | 真 PG/S3/Worker E2E、全套回歸、100k/20k/2k 容量與獨立真值 | capacity result、`tests/test_local_workspace_product.py`、`evidence/CG06.md` | closed_partial |

## 發布禁止條件

- 任一凍結候選缺 validation result，或 Holm family 未完整。
- 圖表／報告／CSV／JSON／HTML／Agent 值無法回指同一 detail hash。
- 使用 observation end 後資料決定過去 membership。
- Discovery 未驗證候選冒充 Validation result。
- null 補零、未觀察補 false、晚期指標稱早期、關聯稱因果。
- 只設定 20,000／2,000 而未實際到達，或只跑單一 stage 冒充 100,000 事件 E2E。
