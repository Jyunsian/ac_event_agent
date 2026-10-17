# L04 — passed (local)

最後本地門檻：session98953 `uv run pytest tests/test_chat_browser.py tests/test_run_browser.py -q -s` 2passed38.38s，含收合程式內容開關／無執行、最新助理標題與語言、先前全部對話與報告行為。證據`.runtime/chat-ui-uyvokegk`、`.runtime/run-ui-m374ht30`。session25148 production build成功、web14tests、Agent23tests通過；圖表chunk>500kB警告保留，不是build失敗。

L04本地實作門檻已齊：prompt有答案／發現／限制／下一步與數值/單位規範；renderer非原始字串堆砌、React安全文字、原文可查、有限Markdown、來源綁定與版本時序；實際工具/回歸含讀取、重跑、人群、樣本不足、逾時、取消、未啟用與非法證據拒絕，原報告保持不變。模型遵循白話規範的實際品質仍需有效授權模型測試，屬L05外部驗證，不用替身冒充。L05要做全套回歸、全站最終核對与本地入口才可完成Goal。

session65367 `uv run pytest tests/test_chat_browser.py tests/test_compute_tools.py tests/test_read_tools.py -q -s` exit0，8passed102.78s，2既有警告。涵蓋安全訊息fixture（新增粗體/inline-code引用）、三小時子分析、人群比較、探索步數限制、逾時、取消、只讀工具無新增任務及引用範圍。compute browser更新為白話labels及data-value精確值，不刪減不可變父報告／版本匯出／唯讀選取斷言。證據`.runtime/chat-ui-b7msrie8`、`.runtime/compute-ui-kyuhpw6v`、`.runtime/compute-ui-m182eoic`、`.runtime/pending-ui-hch8vkfv`。已目視message-safe-390；該截圖是收合程式內容修改之前，原文安全無執行，不宣稱美觀或真模型回答已驗收。

最後將程式區塊收合成補充內容，引用仍可單獨操作；typecheck通過，此最後改動待下一次瀏覽器回歸。TECH_PLAN補有限Markdown與引用時序/舊版本相容契約；LANGUAGE_BEFORE_AFTER補Agent已實作對照，明示prompt規範不等於真模型行為證明。L04還需全文語言掃尾、最新render驗證與完成核對；L05需全套與本地可操作入口，不應停止在局部回歸。

引用時序續作：message-references允許同一對話中、回覆產生之前已完成的工具證據，支援追問不重跑；未來seq或無seq不補綁定。仍以來源工具輪已保存context補舊版本，不用目前畫面版本。新增跨輪合法／未來禁止單測，web14tests與typecheck通過。

收取session43281：chat1passed20.72s（舊版本相容修復）；新增message-fixture真瀏覽器測試後session89714 chat1passed20.74s。證據`.runtime/chat-ui-k62ol_io`，安全HTML/JS連結不執行、未知引用無按鈕、合法引用精確定位、Markdown表格小額／未知值、原文可查、1280/390不溢出；加上原本IME、刷新、取消、重試、不強制捲動與無key真Node可讀報告檢查。替身模型不代表真模型驗收。

最後補strong/em/inline-code內引用的遞迴呈現（最多3層），typecheck與web14tests通過；此最後改動需加fixture驗證。L04仍需回覆格式完整性／提示詞行為回歸、跨分支與非法引用API測試、工具代表問題與最終文案；L05全套尚未開始。

新增 message-references.ts：引用僅綁同輪完成工具receipt；缺版本時允許該工具輪已持久保存的用戶context（run必須一致），不採目前畫面的版本或模型提供版本。版本衝突、無工具、錯輪或未知引用不提供按鈕。新增基本Markdown比較表，數字原文不變；Agent prompt加入先答案後依據／限制／下一步、單位格式、非零小額、只讀不重跑、不能把候選改變說成只改時間，原本安全與探索限制保留。Agent23tests通過、web14tests通過及typecheck通過（legacy context補丁後待重跑web）。

session83119：chat/findings 2passed1failed，歷史finding引用正常；chat引用按鈕缺失因早期readonly工具receipt只有references、不含版本。改用該輪持久用戶context補足後重跑chat（下一輪收取活躍session）。不以恢復任意目前版本fallback解決。仍須確認跨輪合法重用證據的顯示、逐引用API校驗與安全瀏覽器fixtures，不能提前L04passed。

新增 message-format.ts 與 assistant-message.tsx，支援安全的有限 Markdown 子集（段落、標題、清單、引言、程式區塊、粗體／斜體／inline code）。不接受 HTML、圖片或可執行連結；React文字轉義，無 dangerouslySetInnerHTML。一般裸引用與 Markdown report 連結轉成「查看證據 n」，沿用既有 onReference 校驗／定位，原始回覆永久保存且可展開，未寫回歷史訊息。payload context 顯示版本，精確上下文另可展開；失敗碼保留詳情。

`npm run typecheck --workspace web` exit0，`npm run test:web-model` 12passed，新增訊息格式測試納入一般check。chat回歸session7469因腳本仍用L03以前標題失敗（未改回產品文案）；更新chat/compute/version腳本文字，保留選中candidate精確context驗證。重跑session88111需收取結果。

尚需：Markdown表格／巢狀／程式區塊內引用策略、對每個可點擊引用的可信綁定（目前仍依既有點擊時校驗流程）、安全render瀏覽器測試、提示詞規範與數值呈現、長文與代表工具問答。不得僅以parser單測或替身worker說真模型通過。

session88111已完成：`uv run pytest tests/test_chat_browser.py -q -s` 1passed25.67s，證據 `.runtime/chat-ui-eldo6sop`，IME、selected context、刷新、取消、重試、引用定位、不強制捲動通過；真Node無key時送出停用而報告可讀。此為測試替身回覆＋實際Node/API持久流程，不是真模型內容驗收。L04仍in_progress。

前置 L03 已依重驗／圖表／離線及版本數值證據通過。第一批修改 chat-panel：模型不可用不要求一般使用者設定 Worker／OpenRouter；候選上下文改成「選中的事件」；工具狀態改為安排分析／查看進度等動作；錯誤主訊息改用安全 allowlist。未變更工具路由、引用驗證或已保存內容。

`npm run typecheck --workspace web` exit0。局部實作，不代表 L04 passed；待安全 Markdown、友善有效的引用綁定、提示詞／數字格式、原始上下文的詳情入口、長文與工具回歸、代表問題验收。既有 browser 測試中「等待 Python 分析結果」等 locator 需更新，不能刪減狀態／持久性斷言。首次 apply_patch 因 import 空格不匹配未套用，修正後才執行本次型別驗證。
