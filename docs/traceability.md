# 需求追蹤矩陣

來源為 PRD 0.2 與 TECH 0.3；PH編號見IMPLEMENTATION_PLAN。原始要求逐項保留如下。每列的Phase對應下方可點擊驗收紀錄；[現行證據審核](release_audit.md)進一步記錄本次讀過的assert、版本補驗與實際結果，[交付報告](release_report.md)區分本地／真模型／雲端／真資料。PH42最後簽核以狀態表為準。

| 要求 | Phase | 證據 |
|---|---|---|
| 純IAA/D7；ROI留存IAP延後；無登入 | PH01/02/38/42 | defaults、build、端到端與audit |
| 用戶表欄位/重裝定義 | PH01/03/08/09 | schema、fixture、品質 |
| 事件表/格式/收益/有效時間 | PH01/03/08/11 | schema與feature真值 |
| CSV/Parquet多檔上傳/映射/完整期 | PH05/07/08/20 | 真儲存及瀏覽器整合 |
| 零用戶事件/缺值/去重/衝突 | PH03/08/09/10 | 手算真值與品質計數 |
| D7成熟/168h邊界/回傳延遲 | PH10/11/12 | 目標與觸發測試 |
| 頻次/價值/回訪/有效時長 | PH11/12/14 | 特徵與原子條件 |
| F/T/S及AND/OR/短序列/重複 | PH12/13/14 | 條件、序列及剪枝 |
| 小時/天級搜尋/上限/門檻 | PH01/14/40 | 搜尋manifest/容量 |
| 探索驗證分離/固定finalist | PH10/14/15/29 | split/exposure測試 |
| 樣本/覆蓋/延遲/ARPU/CI/基準 | PH15/16 | 指標真值 |
| 國家/平台/來源/批次穩定性 | PH15/32 | 分群及穩定性 |
| 觸發後收益/landmark/非因果 | PH16/18/37 | 診斷與報告 |
| 門檻敏感度/候選重疊/去重取捨 | PH16/23/27 | 曲線/熱圖/引用 |
| 無推薦/低樣本/能力降級 | PH09/15/18/22 | 負例 |
| 精確打點規格/證據卡/測試建議 | PH18/22/37 | 報告全欄核對 |
| 數值可追溯/配置版本/可重現 | PH04/17/18/30/42 | manifest/hash/audit |
| Python先出報告，不依赖LLM | PH17/18/21/38 | 無key端到端 |
| OpenRouter+真AI SDK/模型替身區分 | PH26/27/33/38 | tool-call整合，X01 |
| 對話/工具/新分支/唯讀不重算 | PH25/27/28/30/31/32/34 | API、UI分支 |
| Agent自適應/停止/經驗庫/反例 | PH33/35 | rounds/findings |
| 防止對話反覆holdout污染 | PH29/30/33/35 | exposure與新批次 |
| 任務持久/租約/取消/重試/冪等 | PH04/06/17/25/36/39 | 真PostgreSQL故障 |
| S3保存/不可變來源/備份還原 | PH05/07/18/39/41 | 重建與hash |
| 原始log不進模型/秘密不入前端 | PH02/27/31/38/41 | 邊界與build掃描 |
| 左對話右圖表/兩欄可調/無第三欄 | PH19/24/38 | 1280/1440截圖 |
| Linear tokens/字體/細線/深色預設 | PH19/24 | 視覺QA |
| 固定輸入/tabs/獨立捲動 | PH19/24/28 | 瀏覽器QA |
| 對話工具卡/IME/草稿/不搶捲動 | PH28/38 | 互動測試 |
| 右概覽/候選/圖表/品質四tabs | PH22/23 | 真產物UI |
| 散點/敏感度/重疊/單位/空值 | PH23 | chart schema與對照表 |
| URL/版本/引用/新結果不搶視圖 | PH28/34/37 | 刷新/版本E2E |
| 窄屏切換/鍵盤/對比/圖表替代 | PH24/38 | 768/390及a11y |
| 離線HTML/JSON/CSV/匯出版本 | PH18/37 | 離線開啟及數值 |
| 容量10萬/100萬/1000萬 | PH03/40 | 資源與正確性報告/X04 |
| 正式容器/健康/內部入口/部署 | PH41/42 | 本地演練，X02/X03 |
| 真客戶/真模型/雲端未驗揭露 | PH26/40/41/42 | EXTERNAL_CHECKS |

## 實際 Gate 證據索引

每份Phase證據包含C1–C3及G1–G5的命令、退出碼與產物；歷史過程中的失敗保留，以其最終Gate及本輪release_audit版本核對為準，不以文件存在本身判定通過。

| 要求所屬層 | 逐Phase驗收紀錄 |
|---|---|
| 合約與持久基礎 | [PH01](../evidence/PH01.md)、[PH02](../evidence/PH02.md)、[PH03](../evidence/PH03.md)、[PH04](../evidence/PH04.md)、[PH05](../evidence/PH05.md)、[PH06](../evidence/PH06.md) |
| 輸入與分析 | [PH07](../evidence/PH07.md)、[PH08](../evidence/PH08.md)、[PH09](../evidence/PH09.md)、[PH10](../evidence/PH10.md)、[PH11](../evidence/PH11.md)、[PH12](../evidence/PH12.md)、[PH13](../evidence/PH13.md)、[PH14](../evidence/PH14.md)、[PH15](../evidence/PH15.md)、[PH16](../evidence/PH16.md)、[PH17](../evidence/PH17.md)、[PH18](../evidence/PH18.md) |
| 雙欄UI與可及性 | [PH19](../evidence/PH19.md)、[PH20](../evidence/PH20.md)、[PH21](../evidence/PH21.md)、[PH22](../evidence/PH22.md)、[PH23](../evidence/PH23.md)、[PH24](../evidence/PH24.md) |
| Agent與工具 | [PH25](../evidence/PH25.md)、[PH26](../evidence/PH26.md)、[PH27](../evidence/PH27.md)、[PH28](../evidence/PH28.md)、[PH29](../evidence/PH29.md)、[PH30](../evidence/PH30.md)、[PH31](../evidence/PH31.md)、[PH32](../evidence/PH32.md)、[PH33](../evidence/PH33.md)、[PH34](../evidence/PH34.md)、[PH35](../evidence/PH35.md)、[PH36](../evidence/PH36.md) |
| 交付／恢復／容量／部署 | [PH37](../evidence/PH37.md)、[PH38](../evidence/PH38.md)、[PH39](../evidence/PH39.md)、[PH40](../evidence/PH40.md)、[PH41](../evidence/PH41.md)、[PH42](../evidence/PH42.md) |

真模型、AWS／託管PG、雲端、超出已測容量及客戶資料不在本地替身證據中冒充完成，逐項補驗見[EXTERNAL_CHECKS](../EXTERNAL_CHECKS.md)。
