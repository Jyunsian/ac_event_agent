# GLM 5.3 Flash 真模型接線

## 目前結果

session43544 exit0，.runtime/glm-live-003/result.json status=passed。turn ee7d86a8-27da-4d18-a5e3-fd94ae3a4ec7 succeeded；真GLM依序get_baseline_report→rerun_analysis→evaluate_analysis，child5b75631a-bc4b-4527-8b30-10d50ea7a7cf計算完成，回覆引用實際child summary artifact4f6f6632-2a44-4fa3-a68c-93743648601c與原summary，父報告hash不變。讀報告題與3h深分析題均已有真模型成功證據；美國／重疊／更高coverage完整代表題未全跑，不宣稱X01全部驗收完成。

可操作入口：http://127.0.0.1:5174/workspace?run=f195d3ce-d17c-4e6a-9b8b-5c1772c34bb8&conversation=7b222023-ffc9-4e42-aa6b-2d7a9d30de32 。本機服務保持運行，PG/S3 65329、API83598、Python5127、GLM Agent22883、Vite33334。key僅Agent程序環境，重啟需重新注入；使用者撤銷後模型不可再用。沒有雲端部署。

第二輪結果：session36805 exit1，第一題succeeded且真UI顯示2個引用按鈕；第二題曾引用未在該turn交付的evidence而工具拒絕，模型自行讀baseline再成功rerun/evaluate，child ded6b0a7-8f83-4aee-a0e6-f723b75d5a3e ready=true、DB config.windows_hours=[3]。最終敘述碰到原120s wall limit而AGENT_TIMEOUT，child報告保留，不假裝整輪成功。chat browser回歸session47183 exit0，1passed31.02s；desktop.png已目視。

正式Node入口新增可配置AGENT_TIMEOUT_MS（默认120000、允許1000..600000），GLM測試設300000；這只調模型turn等待，不修改計算／候選／step預算。兩個env範例同步。npm run test --workspace agent session43759 exit0，23passed；超600000設定實際拒啟動測試通過。真Agent現handle22883；前兩個agent已精確Ctrl-C停止。只重驗未完整成功的3h題，session43544、conversation7b222023-ffc9-4e42-aa6b-2d7a9d30de32、產物.runtime/glm-live-003，仍待收取結果。

第一輪產品test session87710 exit1：AGENT_REFERENCE_INVALID。真公開step checkpoint顯示模型已調get_baseline_report／profile_dataset／get_exploration_budget，回答引用是正確已交付ID但用Markdown反引號包住；agent/tools.ts及web/chat-panel.tsx的regex未排除反引號，誤算進ID。只修正Markdown分隔符，不放寬allowed-set、pointer或foreign ID判斷，新增反引號合法與evil後綴非法測試。`npm run test --workspace agent && npm run typecheck --workspace web` session7443 exit0，23passed／tsc。

舊真Agent31149已以自身TTY Ctrl-C停止，新Agent71240沿同本機設定與臨時key啟動（key僅程序環境）。第二輪真產品檢查session36805、產物.runtime/glm-live-002、conversation=b35f3e2d-5970-4798-84f5-4b0a949d2fe4；chat browser受影響回歸session47183。兩者仍待結果，不能重啟原請求或提前宣稱通過。正式ph41-local images尚未包含本次引用解析修正；不在此處部署雲端或冒稱舊image是最新source。

使用者明確提供臨時OpenRouter key並要求接線測試；model=`z-ai/glm-5.3-flash`。只使用既有合成資料；沒有部署雲端。key透過關閉echo的TTY讀入、只存在Node程序環境，未寫入專案檔案或此紀錄。key撤銷由使用者操作，撤銷後Agent無法再呼叫模型。

`npm run build --workspace agent` exit0。正式provider smoke：`node agent/dist/smoke.js --allow-paid`（私密程序環境），session4321 exit0，status=passed；3steps，evidence工具依序n=1、n=2；input2127／output587（其中reasoning161）／total2714。使用真OpenRouter，不是MockLanguageModel。按查得每百萬input0.075／output0.25美元估算約0.000306美元，不是帳戶扣款查證。

原8080／8081／5173是仍在運作的舊dev程序（agent/status404），保留不停止。新測試入口5174→API8092→Agent8093，使用既有持久合成工作區flow-8ba3cf75及Python Worker；正式agent/dist/index.js注入真key/model，沒有測試模型替換。API與前端代理agent/status回available=true，configured不視作完整驗收。

目前服務handles：PG/S3 65329、API83598、Python5127、真Agent31149、Vite33334。留給使用者本機測試；原本錯誤巢狀npm參數啟動的Vite PID48041已精確停止，改用直接workspace指令並修正docs/local_workspace.md。

產品檢查：scripts/live_model_acceptance.mjs只接受loopback與已標synthetic的report，送出兩題（讀報告／3h深入分支）；操作既有正式API，Agent真生成。session87710仍執行中，conversation=d9545737-52cb-49f8-8175-2295f96cb6ac，parent=f195d3ce-d17c-4e6a-9b8b-5c1772c34bb8；不能以已提交當完成。產物.runtime/glm-live-001/，後續需核對實際工具／引用／child及結果，X01完整四题仍不可提前全部標passed。
