# 語言體驗完成審核

狀態：本輪交付門檻通過（2026-09-10）。此表按實作、實際測試輸出、持久產物及呈現結果核對；詳細命令、失敗與修復保留在evidence/LANGUAGE-L01至L05。真模型為有限抽樣，不保證未來每次生成都正確。

| 需求 | 實作／可核對的證據 | 本輪結論 |
|---|---|---|
| 全站用語、狀態與層級 | LANGUAGE_PLAN.md矩陣；language.ts、field-language.ts、report-language.ts與共享reason_labels；L01 | 通過；最後原因標籤4項語言單測與實際概覽已核對 |
| 欄位用途、完整截止與匯出UTC、示範隔離 | upload-page；upload_browser_qa實際續傳、錯檔拒絕、映射／UTC保存、demo隔離；L02 | 通過 |
| 進度、排隊、失敗、重試、歷史 | run-page與language錯誤allowlist；run_browser與product回歸；L02／L05 | 通過，技術詳情仍可查 |
| 概覽結論／原因／下一步、無候選不強薦 | report-panel與report_html；report值／樣本不足測試、真入口1440／390；L03／L05 | 通過；language-handoff-final呈現最新原因標籤 |
| 真條件名稱、分母、單位、小額、缺值 | candidate-language、report-language、Python report_language；語言單測、delivery精確data-value及HTML／JSON比較；L03 | 通過；最後read_tools真來源比對與child指標一致性回歸完成 |
| 圖表問題標題／提示／資料表 | report-charts、chart-renderer；真hover與桌面／390圖表檢查；L03 | 通過，不只用靜態截圖證明hover |
| 版本切換、重驗、三格式／父版保留 | branch-picker、finding-selector；finding-recheck／delivery／product四題三格式＋CLI重啟hash；L03／L05 | 通過；未覆写歷史報告 |
| 安全Markdown、原文、有效／非法引用 | assistant-message、message-format、message-references；browser安全fixture與引用時序／來源單測；L04 | 本地通過；中文分隔符新增回歸已通過 |
| 長度截斷與錯誤狀態 | runtime length判定、queue AGENT_OUTPUT_LIMIT與安全文案；runtime與queue測試 | 通過單元與隊列持久測試；不發布半截答案 |
| 真模型白話、正確分母／條件／建議 | .runtime/language-glm-live-003、language-glm-final-003；公開steps與L05語義審核 | 第三輪五題＋最後短回覆通過；前期失敗保留。最後短回覆手機、桌面已檢視 |
| 五題工具行為、唯讀不重跑 | test_read_tools job count、compute代表情境、product四題；真模型每輪tools與immutable parent檢查 | 通過；一四五題只讀工具，第二／三題保存子版，父版hash一致 |
| 缺引用補正與保存 | readonly-agent、read_tools真API／PG整合29403 | 通過；最多一次、無工具、原剩餘預算，foreign不補正；模型輸出／用量保存，重新載入不新增模型call |
| 最終回歸與可操作交付 | build、web／agent測試、pytest70788、局部回歸72452／66011／29403；LANGUAGE_ACCEPTANCE.md | 全套247passed；最後改動另列局部通過，未將事後新增測試算入247。交付入口正常且Agent available |

已目視真入口概覽桌面／手機、第三輪長回覆與最後短回覆；language_reply_qa在1440／390驗證所有五題引用，以及最後短回覆的原始ID隱藏、正確定位／刷新保存。language_live_qa覆蓋四tabs、空頁、上傳、歷史；無key與錯誤安全狀態有先前browser證據。既有歷史模型回覆原文保留，不追溯修改措辭。完整路徑索引與局部測試終值見L05最終交付判定。

已知限制：模型不是全文事實查核器，缺引用補正仍可能失敗而拒發；Markdown有限子集；圖表chunk警告與兩項依賴警告未消除；磁碟約6.5GiB可用。這些不影響本次已驗證的語言交付，不宣稱雲端就緒、任意資料量或真客戶效果。

未部署雲端、未新增會員或多租戶、未使用客戶資料。OpenRouter原授權key已恢復且認證成功，不再列為使用者未提供的外部阻塞。模型傳輸只使用合成資料聚合證據，文件不含憑證。
