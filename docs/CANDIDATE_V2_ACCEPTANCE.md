# Candidate V2 驗收追蹤與產物合約

此表追蹤批准計畫，不取代或縮減其逐項條件。passed 必須指向實跑 evidence；未實作不得以合約定義冒充通過。

## 已固定的 v2 合約

- `server/analysis/v2_contract.py` 為版本入口及共享數值驗證器。report 的 candidates 僅為優先項；catalog 綁定完整 evaluated_count、priority_ids、逐候選 detail_sha256 及 frozen_sha256。run/dataset/candidate 共同定位，不能跨版本拼接。
- 詳情 envelope 包含 event_spec、exploration、validation、revenue_decomposition、source_diagnostics、selection、timing_status。事件沿用既有受限 AST；禁止 SQL。候選採首次達標一次。
- exploration/validation 共用 groups(all/triggered/untriggered)，每組 users、unknown_revenue_users、revenue_usd、arpu_usd。人數分組相加；未知收益及無人組收益為 null，不補零。coverage 分母為全部成熟用戶。delay_seconds median/p90 單位秒。所有數值必須有限。
- comparison 的差額單位 USD/user；比率的分母明示，零分母 null。bootstrap 使用既有 intervals lower/upper、seed、replicates，新增統計結果不得冒稱區間經多重校正。
- validation 的 Welch 原始 p、Holm adjusted p、family_size、alpha、testable/reasons 與 evidence_status 分離。不可檢驗 p=1；全凍結家族完成校正前不發布通過。具體生產／消費子結構與一致性由 CV03 整合測試落實。
- revenue_decomposition 以同一候選分组，before=[0,W)、remaining=[W,168)、d7=[0,168)；收入總額相加，缺失傳播。共同 landmark 24/72/144 與個人觸發後收益分開。來源任一組<20隱藏比較；日曆空日 coverage=null。此處是固定語意，不代表數值已計算。
- selection 保留優先角色、探索 Pareto 層、相似優先 ID/Jaccard；不使用 holdout 排序或補選。timing_status 為 observed 或 assumed_event_time，後者不能標 historically_validated。
- 預算、窗口、分位、角色、統計／時間政策完全依批准計畫第2–3節；Welch 適用性及容量是待驗方法假設，不是產品事實。
- v1 只讀舊值，缺少 v2 欄位時不注入；v1/v2 API 原始 bytes 保留。前端版本讀取屬 CV04，不能由後端讀取測試推論通過。

## 逐項驗收索引

| 計畫條件 | 驗收責任與證據位置 | 目前 |
|---|---|---|
| CV01 C1–C3 | v2_contract、手算及真下載 API；evidence/CV01.md | 已有實跑證據 |
| CV02 C1 | 全窗口、各格式分位/1-2-5、家庭預算/回補、逐條未評估 | passed：evidence/CV02.md 最終 Gate |
| CV02 C2 | Pareto、交替選取、樣本門檻、90%替代、重現性 | passed：evidence/CV02.md 最終 Gate |
| CV02 C3 | 改 holdout 不改搜尋/選擇，起點邊界及首次觸發 | passed：evidence/CV02.md 最終 Gate |
| CV03 C1 | 全家族凍結/結果、Holm手算、退化/重尾/無訊號 | passed：evidence/CV03.md 最終 Gate |
| CV03 C2 | 收益加總、D6/168、來源/空日/未知/未成熟 | passed：evidence/CV03.md 最終 Gate |
| CV03 C3 | PG/S3恢復、checkpoint、揭露、校正完成發布 | passed：evidence/CV03.md 最終 Gate |
| CV04 C1 | 三頁/全部卡/收入圖、三格式數值及ID一致 | passed：evidence/CV04.md |
| CV04 C2 | 桌面/手機目視、離線、篩選匯出與50筆分頁 | passed：evidence/CV04.md |
| CV04 C3 | Agent分頁/<=10比較/引用、v1及父hash | passed：evidence/CV04.md |
| CV05 C1 | 上傳至對話分支及匯出真端到端、既有回歸 | 待驗 |
| CV05 C2 | 10萬/100萬事件、至少一組實評2000、資源/真值 | 待驗 |
| CV05 C3 | 既有配額不變、失敗修復留證、外部清單/交付 | 待驗 |

每列同時要求 G1 真實作、G2 命令退出碼、G3 回歸、G4 原始資料保留、G5 evidence/狀態同步。最終按批准計畫全文逐條審核，不能只查此表。

## 最終固定版本核驗清單（尚未完成）

以下是已定位的驗證入口，不是通過宣告。CV01–CV04歷史證據保留；CV05完成前，最新計算版本仍需整套命令退出碼、容量產物與實際內容核對。

| 要求 | 應核對的當前實作／測試入口 | 最終證據 |
|---|---|---|
| 十窗口、固定起點、半開端點、首次達標、D7成熟／零事件／未知值 | features、targets、predicates；test_features、test_targets、test_predicates、test_holdout_predicates、test_v2_contract | 待最終回歸 |
| 正值分位、1/2/5收入刻度、格式、原子/組合/序列預算與回補、全部未評估原因 | search/search_policy；test_search、test_v2_search_policy、test_v2_search_integration、test_sequences | 待最終回歸 |
| Pareto三維、窗口父條件20、相似90%、最多10優先、不湊數、不依holdout補選 | priority/finalists；test_v2_priority、test_finalists、test_v2_search_integration | 待最終回歸 |
| 全2000凍結家族、Welch/Holm、退化p=1、1000 user bootstrap、原樣本/品質/日方向gate | freeze/validation/statistics_v2/bootstrap；test_v2_freeze_contract、test_validation、test_statistics_v2、test_bootstrap、test_v2_positive_family | 待最終回歸及容量 |
| 每候選前/後/D7分解、24/72/144 landmark、D6不因剩餘短淘汰、source小樣本、空日未知 | diagnostics/revenue/source；test_v2_revenue_decomposition、test_v2_sources、test_v2_calendar | 待最終回歸 |
| 新版重現、immutable input/父報告、數值及版本來源一致 | test_reproducible_reductions、test_v2_contract、test_findings、test_report_delivery；pipeline/feature/method fingerprints | 待最終回歸；不能把跨舊算法窄容差當新版重現 |
| 完整客戶目錄、全部狀態、detail hash、排序/篩選/50筆分頁、原始精度 | candidate_reader/catalog/paging；test_candidate_catalog、test_candidate_paging、前端model/client tests | 待最終回歸 |
| 白話證據卡與三格式數字/ID一致、桌面/手機、關API離線可用 | test_candidate_exports、test_report_delivery、test_product_browser；CV04目視產物 | 待最新browser回歸並核對適用版本 |
| Agent搜索/比較上限/引用、分支/分群、披露污染、舊版可讀 | test_candidate_agent、test_read_tools、test_compute_tools、test_findings、test_segments、test_product_browser；Agent workspace tests | 待最終回歸 |
| 真PG/S3與持久Worker、批次中斷恢复/租約隔離、未完成校正不發布、scratch清理不傷artifact | test_checkpoints、test_validation_batches、test_pipeline、test_resources；相關jobs/backup/recovery回歸 | 待完整Python suite |
| 10萬/100萬完整13階段與獨立CSV/Decimal真值、至少一組實評2000、時間/RSS/磁碟/大小 | scripts.benchmark；兩批result.json checks全部true、reached_2000_candidates、fingerprint及原Limits | 最新固定版本10萬已通過（cv05-100k-v2-03）；100萬待定 |
| G1–G5與交付停止條件 | 完整suite/build/typecheck/web/Agent/contracts、所有handle已收取、evidence/CV05/PHASE_STATUS/本表/容量/外部清單 | 尚未具備完整交付證據 |

最終命令集合：`.venv/bin/python -m pytest`（保存JUnit與失敗詳情）、`npm run build`、`npm run typecheck`、`npm run test:web-model`、`npm run test --workspace agent`、`.venv/bin/python contracts/check.py`，及兩批正式`python -m scripts.benchmark ... --run`。失敗需修復後依影響重跑，不能以子集取代全套，也不能以較早版本的passed替代最新版。

不納入本輪：滾動窗口實作、雲端部署、任意產品事件、成本上傳、SDK/平台回傳或ROI成效保證。這些排除不豁免任何本地核心或容量失敗。
