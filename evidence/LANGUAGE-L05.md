# L05 — passed

## 最終交付判定（2026-09-10）

L01–L05本輪已完成。本檔以下保留所有失敗與續作紀錄，最新結論以本節為準。

- 本地全套247passed；最後變更另通過唯讀／逾時2項、隊列6項、報告15項及新增語言4項、web14、agent25、22合約案例與production build。不是宣稱一次247全套含其後新增的測試；以全套＋列明的最後變更回歸共同覆蓋。
- 真GLM五情境第三輪全部succeeded且父報告hash不變；讀報告／重疊／資料不足都只有唯讀工具，3h與美國分析保存子版。最後白話prompt短問答final003通過，內容已人工核對：6人來源、2人比較、合法來源引用、無內部ID或統計術語、無投放效果保證。
- final003本輪工具為get_baseline_report／profile_dataset，公開step為tool-calls→stop，無計算；此成功未用到補正。缺引用補正由真API／DB整合替身強制觸發驗證，不能冒稱該補正路徑已由真模型觸發。
- 補正持久化加測曾失敗（45875、32235）：checkpoint合約只接受assistant/tool，初稿誤把runtime的user型補正指令放進prefix。已修正：指令只用於當次模型輸入，不混入模型／工具輸出checkpoint；完整工具journal與補正模型輸出／用量照常保存。17934 passed；再加入重新載入相同3steps、無新增模型call、文字一致的驗證，29403最終1passed6.29s。未放寬checkpoint role、來源或內容限制。
- 最後真回覆browser72309：1440／390正文raw ID隱藏、引用API200、同run/version、刷新保存、無錯誤／橫向溢出。最後全站browser18040同樣通過（概覽四tabs、Agent可用、空頁、上傳、歷史）。證據`.runtime/language-replies-final-003`與`.runtime/language-handoff-final`；最終手機回覆與桌面概覽已目視，包含新增原因標籤。
- 最終常駐：API12390/8094、Agent25574/8095（最新補正持久化修正）、Python36343、Vite99381/5174；同flow-8ba3cf75資料。key只在程序環境，未寫檔；沒有雲端部署或資料刪除。

已知限制：模型仍可能措辭不佳或漏引，補正最多一次、仍不合格就拒發；來源驗證不是全文事實查核。既有歷史回覆不追溯重寫。Markdown為安全有限子集。圖表chunk564.63kB警告及2項既有依賴deprecation警告保留。最後磁碟約6.5GiB可用，不啟動額外容量測試，不宣稱更高容量或真客戶效果。

交付索引：docs/LANGUAGE_PLAN.md、LANGUAGE_BEFORE_AFTER.md、LANGUAGE_AUDIT.md、LANGUAGE_ACCEPTANCE.md。文件／樣本／測試邊界明確，不把本地交付當雲端上線。

## 最新本地驗收收取

final002再次因完全沒有引用而被拒絕，handle34361 exit1。為避免只靠反覆prompt，新增readonly-agent「最多一次缺引用文字補正」，只適用零引用且allowed非空；使用原剩餘時間／步數、tools={}，補正後仍完整校驗，不為非法引用換ID、不再排計算。原無引用也無工具／foreign引用仍拒絕。新增真API整合測試：漏引補正成功、補正無工具、持續漏引僅3次模型call後拒絕、foreign僅2次後拒絕、2步預算不補正。agent25測試＋read_tools2288通過，補齊安全情境後read_tools+chat_browser66011最終2passed27.55s。

目前常駐服務已更新API12390／Agent92053；Python36343、Vite99381保留。真模型final003 handle46741，conversationbf3e552c-8c5a-436a-bdb6-46e7a6bad58c、turn430915a9-cb46-410a-9ad9-34fc4348439b，尚須收取。新窗口名稱與概覽原因的專用report_language單測4passed0.02s。合約與已保存父報告不改。

session70788全套最終247passed、2既有warnings，730.57秒。未再啟動全套。全套期間新增的queue output-limit測試另6passed；最後read_tools人名／窗口格式與timeout獨立重驗72452最終2passed32.68s，沒有修改原20秒限制或刪除assert(observed)。此前並行測試失敗已保留，獨立回歸確認可以取得完成child後正確timeout。最新report_language+report 15passed0.58s；最新build／web14／22契約57404通過；prompt收尾agent69320為25passed。

新版prompt已安全沿用key更新到Agent84574（8095），API仍60406（8094）；Python36343／Vite99381不變。final001短回覆turn73fcd97c-1175-43b8-bae0-36a25ed083bf：stop但完全漏附引用，AGENT_REFERENCE_INVALID正確拒發。公開checkpoint正文已白話並有正確6／2／100／20／2分母與門檻限制；不能把無引用算完成，也不應把來源失敗說成金鑰問題。保持同prompt與安全規則，另以新合成對話final002複验；不刪除失敗、不自動為模型補造引用。

## 2026-09-10 續作實測

### 最新續作（先讀此節）

#### 模型內容審核與第三輪

第三輪96585續作：讀報告與3h題均succeeded；前兩題正文已正確引用完整OR條件、候選2人分母，沒有把零觸發外推全6人；引用實際設定100／20／2並說明不是效果保證。3h題明示窗口與候選／門檻同時改變，不歸因單一窗口。其餘題與最終語言呈現待審核，不以這兩題推定五題全部合格。第二輪全套70788已到58%，沒有新failure；局部2346仍活躍。

第三輪96585最終exit0：五題均succeeded，parentUnchanged=true。第三題正確分開美國3人、探索2人／檢查1人，小樣本未知不補零；第四題用既有overlap，說明探索3人中的同1人，不混用檢查2人分母；第五題重新唯讀profile／baseline完成來源引用。僅第二題rerun/evaluate、第三題segment/evaluate；一四五沒有計算工具。仍有「凍結空選擇」「第90百分位」「統計把握／描述性區間」等可進一步白話化的模型措辭，不能以流程pass當全部文案問題消失；需最後語言收尾與樣本複驗。

新增scripts/language_reply_qa.cjs；session3097 exit0，`.runtime/language-replies-003`：1440／390均讀取同一第三輪五個真回覆；正文無raw report ID、每題有引用且無未確認標記，點首引用API200並定位相同run/version/candidate；刷新五回覆保留，無pageerror／橫向溢出。第五題390已目視。

局部2346最終6passed1failed197.55s：timeout測試在20秒deadline前未收到計算完成，`assert(observed)`失敗；同時有全套與真模型活動。不可只憑並行推定原因或放寬驗收；等70788終止後獨立重跑該例，必要時檢查服務日誌。最新web28915：14passed。70788已到87%，無failure字母，仍須收取終值。

最後語言prompt收尾已加：探索人群／中位數／第90百分位的白話說法；不對一般使用者拋信賴區間、多重比較校正、統計把握及空選擇凍結等內部操作。agent測試69320執行中。**目前常駐Agent65908仍載入第三輪prompt，尚未重啟到這條收尾**；下輪先收取測試，再安全沿用其程序環境憑證更新，最後以合成資料做至少一題涵蓋資料不足與下一步的回覆複驗，確認不再殘留前述術語。不要把第三輪舊回覆當新prompt證據。

新增docs/LANGUAGE_AUDIT.md逐需求完成審核索引。發現概覽原始summary reason為NO_HISTORICALLY_VALIDATED_CANDIDATES卻缺少中文標籤，已補共同reason_labels，避免泛泛提示；另將Agent中文條件窗口72.0顯示為72，未改數值。最新web-model測試28915待收取，格式化的read_tools補充斷言待重跑。未修改歷史報告。

第二輪40517終止exit1：前四題turn成功，第五題AGENT_REFERENCE_INVALID（stop不是length）。第一題正文把2人的候選比較結果外推為全部6人都沒有符合，簡化OR條件，且憑空提出每天數百人；第二／三題也沿用部分不準確敘述。不能以turn成功或引用存在宣稱內容品質通過。第五題直接沿用過去輪引用，沒有本輪交付的完整證據集合，安全檢查正確拒絕。

修正：read_tools附上從原event_spec生成的完整中文display_name、實際audit.validation_rules及分母解釋；branches的子報告候選也附同一event_name生成器，不重算指標或改報告JSON。prompt要求完整條件、候選自身比較分母、不捏造每日量級，並明確每輪重新讀取所需唯讀證據（不重跑計算）。read_tools來源與不新增jobs測試40611：1passed7.02s；新隊列output_limit不發布／下一輪可繼續測試42372：6passed9.02s。build及web14／agent25測試14910通過。最後共同event_name抽取／child label改動正由read+compute回歸2346驗證。

第二輪全套70788仍活躍，持續poll，不另起全套。此suite啟動後有新增queue測試與tool呈現修改，最終須與最新局部測試合併審核，不宣稱它涵蓋事後所有變更。

第三輪真模型新prompt產物`.runtime/language-glm-live-003`已啟動。先前模型全終止後才更新本機程序：API60406、Agent65908（安全沿用同專案程序環境金鑰），Python36343、Vite99381保留。需要收取第三輪五題與瀏覽器引用呈現並審核語義。

第三輪live handle96585，conversation556dea59-8a1b-45bc-bb2a-c5c50c07e66f，首turn7dd35c77-3c78-43bc-802a-8f8386e87c84，已確認submitted。磁碟即時8.8GiB可用（96%），沒有刪除來源或測試證據；不啟動重複全套。下一步先收取70788／2346／96585，各有已確認活躍handle。

- 共用product腳本的UTC字串修正後，session11239兩例仍失敗：select標籤含選項文字，exact locator不匹配。改用以標籤開頭的定位，沒有略過實際填寫。session97299最終2passed60.85s，完整四題、三格式、父版不可變及CLI重啟保存驗收通過。segment_branch兩例已在session6734通過。
- session3218：web14、agent23、22契約案例通過。新增長度／中文引用修正後session47857：agent25、web14、typecheck通過；其後另補一條web中文引用斷言待下次收取。
- 真模型第一輪session71208終止exit1，AGENT_REFERENCE_INVALID。公開step checkpoint證實finish_reason=length，4096輸出token耗盡，正文在evidence ID中途截斷，不能發布。也發現引用中的全形括號／頓號未被解析為分隔符。
- runtime設定有限8192輸出token上限（保留8step／300秒本機限制），prompt增加约300中文字、最多3發現、避免引用串與分母外推。length回傳output_limit並由服務發布明確AGENT_OUTPUT_LIMIT安全狀態；新增模擬provider length測試。後端／前端引用解析同步支援中文括號頓號，exact allowlist仍拒絕非法suffix與截斷ID。未修改分析計算、報告或放寬引用來源。
- 舊Agent66608已精確停止，安全沿用原程序環境中的本專案key啟動新Agent71952；不寫檔、不輸出key。API99530已停止，替換API39929載入新錯誤狀態。資料仍同flow-8ba3cf75。Python36343／Vite99381保留。
- 第二輪全套pytest session70788已啟動，尚需poll同handle。第二輪真模型新prompt產物`.runtime/language-glm-live-002`，仍須收取及逐題審核，不提前passed。
- 第二輪真模型handle40517，conversation1fb316a3-668b-4e01-b643-cb2b3eb0f7b3；首turn0c3eb611-9328-4a72-9312-5c7fc3db87ca。最新web中文引用斷言已重跑14passed。

- 全套session89604已終止：243passed、4failed、2既有警告，633.32秒。失敗為product_browser及local_workspace_product共用腳本的舊按鈕名稱，以及segment_branch兩例仍斷言舊HTML文案。計算、不可變父版與來源檢查斷言保留；已更新腳本與中文HTML期望。首輪重跑session6734：2passed、2failed；後兩例是Playwright拒絕含零秒的datetime-local字串，已用此fixture的分鐘精度重填，重跑session11239待收取。不把失敗歸類為外部條件。
- 最新production build session36081 exit0；圖表chunk564.63kB警告仍在，沒有因此調高警告門檻。
- demo視覺腳本session75914 exit0，1440／1280／768／390，分隔線、獨立捲動、手機草稿、候選詳情與空狀態通過。`.runtime/language-final-demo-20260910`。示範候選去Session／USD名稱，首次符合精確資料預設收合，增加展開測試。
- 新增scripts/language_live_qa.cjs。初輪手機空頁誤等待隱藏h1，已改等待可見標題；第二輪截圖過早拍到載入，已加入報告結果標題就緒等待，不能把早期截圖當完成內容。第三輪session29724 exit0，`.runtime/language-final-live-20260910c`，桌面1440／手機390：真持久報告四tabs、模型不可用、空頁、上傳及歷史，無橫向溢出或pageerror。概覽390已目視，確定有結論／原因／下一步，不是loading。
- workspace引用錯誤主訊息改為安全說明，原錯誤保留details；示範建議問題改為具體可理解的問題。
- 使用者指出昨日已給金鑰後，查明舊真模型session22883已不存在，原紀錄證實key僅程序環境。重新使用原授權key做provider只讀認證，HTTP200；未保存key至檔案。停止本次自行啟動的無key Agent36651，替換正式Agent66608，8095連8094、300秒turn限制，模型glm-5.3-flash。5174的agent/status已available=true；不把configured當品質驗收。
- 真模型新版五題已由scripts/live_model_acceptance.mjs --language啟動，session71208，conversation f97014cb-ef44-4a6d-85c4-43c860a6a098，產物`.runtime/language-glm-live-001`。仍需收取結果、審核正文／引用／是否不必要重跑，不冒稱完成。

L01–L04本地門檻已通過，仍需全套回歸／全站最終核對／本地可操作入口與有效模型外部條件審查。啟動全套前磁碟17GiB可用，沒有刪除任何來源資料或測試證據。production build與37項Node測試已通過，Python全套結果需獨立收取，不從局部回歸推定通過。

`uv run pytest -q`已啟動，session89604；續作先poll同一handle，不另起重複測試。全套完成前不得宣稱L05passed。

本機服務復原：原API8092屬本專案PID47986，連至flow-8ba3cf75的PG63318/S3 63319；原合成baseline f195d3ce-d17c-4e6a-9b8b-5c1772c34bb8 ready且JSON HTTP200。沒有停止既有8092/8080/8081服務。為使交付執行目前程式碼，新增同持久工作區API8094(session99530)、Python Worker(session36343)、正式Node Agent8095(session36651)，前端5174(session99381)代理8094。自行暫啟前端5531已Ctrl-C停止，未動其他前端。資料不重建、不改寫歷史報告。需續作驗證完整UI與Agent狀態，不能僅用HTTP200宣稱全交付。
