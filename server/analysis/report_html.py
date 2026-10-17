"""Standalone, accessible report presentation. No network, model or statistical recalculation."""
import html
import json
from server.analysis.report_language import condition_name, family_name, reasons_text, statement_text, date_text


def esc(value):
    return html.escape(str(value), quote=True)


def pretty(value):
    return esc(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))


def cell(value, unit=None):
    if value is None:
        return '<span class="muted">未知</span>'
    if unit == "percent":
        display = f"{value*100:.2f}%"
    elif unit == "usd":
        display = (f"{value:.6f}" if not value or round(value, 6) else f"{value:.3g}")+" 美元"
    elif unit == "hours":
        display = f"{value/3600:.2f} 小時"
    else:
        display = str(value)
    return f'<span data-value="{esc(value)}" title="原始值：{esc(value)}">{esc(display)}</span>'


def table(headers, rows, caption):
    rows = list(rows)
    if not rows:
        return '<p class="muted">無可用資料；未產生結果不代表數值為零。</p>'
    return '<div class="table" tabindex="0" role="region" aria-label="'+esc(caption)+'"><table><caption>'+esc(caption)+\
        '</caption><thead><tr>'+''.join('<th scope="col">'+esc(h)+'</th>' for h in headers)+\
        '</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def details(label, value):
    return '<details><summary>'+esc(label)+'</summary><pre>'+pretty(value)+'</pre></details>'


def condition(predicate):
    return condition_name(predicate)


STATUS = {"historically_validated": "歷史資料支持，仍需投放測試", "insufficient_data": "目前資料不足，無法判斷", "exploratory": "新發現，仍需新資料確認"}
CAPABILITIES = {"revenue_analysis": "前 7 天廣告收益分析", "revenue_trigger": "收益門檻觸發", "ad_frequency": "廣告頻次",
                "session_count": "使用次數", "engaged_seconds": "有效互動時長"}


def render_report(model):
    summary, rows, diagnostics = model["summary"], model["candidates"], model["diagnostics"]
    quality, targets, profile = summary["quality"], summary.get("targets") or {}, summary.get("data_profile") or {}
    labels = {row["candidate_id"]: f'C{i+1}' for i, row in enumerate(rows)}
    names = {row["candidate_id"]: str(row["event_spec"]["window_hours"])+" 小時內，"+condition(row["event_spec"]["predicate"]) for row in rows}
    for point in (diagnostics.get("sensitivity") or {}).get("points", []):
        names.setdefault(point["candidate_id"], family_name(point["family"], point["threshold"]))
    label = lambda identity: (labels[identity]+" · " if identity in labels else "")+names.get(identity, "其他事件條件（詳見設定）")
    source = lambda name, pointer="": '<details><summary>查看計算來源</summary><p class="source">'+esc(name+pointer)+' · '+esc(model["audit"]["sources"].get(name, {}).get("sha256", "未提供"))+'</p></details>'
    section = lambda id, title, body: f'<section id="{id}"><h2>{esc(title)}</h2>{body}</section>'
    empty = not summary["historically_validated_count"]
    headline = "目前還不能選出值得優先測試的事件" if empty else "找到有歷史資料支持的事件條件"
    overview = '<p class="lead">'+headline+'</p><p>比較開始使用後前 7 天的廣告收益。沒有完整 7 天資料的用戶不當成零收益；過去收益較高，不代表用這個事件投廣告一定更有效。</p>'
    overview += '<h3>下一步</h3><p>'+('先確認下方限制與資料是否完整，再補充資料或調整要研究的條件。' if empty else '比較人數、收益與符合條件的時間，再選擇適合的事件規劃投放測試。')+'</p>'
    overview += table(["找到的條件", "選入比較的條件", "有歷史資料支持", "已有完整 7 天資料的用戶", "尚未完整觀察 7 天的用戶"], [[
        cell(summary.get("searched_candidate_count")), cell(summary["candidate_count"]), cell(summary["historically_validated_count"]),
        cell(targets.get("mature_users")), cell(targets.get("immature_users"))]], "分析範圍")
    overview += '<p>資料完整截止時間：'+esc(date_text(profile.get("complete_through")))+'；用戶安裝日期範圍可展開下方「來源資料範圍」查看。</p>'
    overview += details('分析狀態詳細資料', model['analysis_status'])
    overview += table(["資料筆數", "用戶", "事件"], [["保留", cell(profile.get("users")), cell(profile.get("events"))],
        ["排除輸入列（含重複）", cell(quality.get("excluded_input_rows", {}).get("users")), cell(quality.get("excluded_input_rows", {}).get("events"))]], "資料品質概覽")
    overview += table(["能力", "可用", "限制原因"], [[esc(CAPABILITIES.get(k,k)), "可用" if v["enabled"] else "不可用", esc(reasons_text(v["reasons"]) or "無")]
        for k,v in quality.get("capabilities", {}).items()], "目前可分析的行為")
    overview += '<p>主要限制：'+esc(reasons_text(summary["reasons"]) or "見下方統計與資料限制")+'</p>'+source("baseline")+source("quality")+source("targets")
    recheck=summary.get('finding_recheck')
    if recheck:
        recheck_labels={'reusable_evidence':'可重用歷史證據','exploratory_only':'僅探索性結果','insufficient_evidence':'證據不足',
                'not_supported':'本批未支持','not_evaluated':'未完成評估'}
        overview+='<h3>固定舊規則重驗</h3><p>未依本批結果重挑門檻。可重用歷史證據不等於投放提升；後續批次仍須驗證。</p>'
        overview+=table(['之前的事件條件','這批資料的結果','限制'],[[esc(label(r['candidate_id'])),
            esc(recheck_labels[r['status']]),esc(reasons_text(r['reasons']))] for r in recheck['assessments']], '固定舊規則重驗結果')
        overview+=details('重驗來源快照',recheck)
    segment=summary.get('segment')
    if segment:
        overview='<h3>'+esc({'country':'國家','platform':'手機系統','acquisition_source':'用戶來源'}.get(segment['segment']['field'],'人群'))+'：'+esc(segment['segment']['value'])+' 的用戶分析</h3>'
        overview+='<p>使用原本的事件條件與用戶分組，不重新挑選条件；仍只比較已有完整 7 天資料的用戶。這是同批資料的進一步觀察，不能當作新資料的獨立確認或投放成效。</p>'
        overview+=details('來源分析與分組識別資料', {'parent_run_id': model['audit'].get('parent_run_id'), 'split_id': segment['split_id']})
        overview+='<p>選中用戶：'+cell(segment.get('selected_users'))+'；還未完整觀察 7 天：'+cell(segment.get('immature_users'))+'；欄位未知：'+cell(segment['field_unknown_users'])+'</p>'
        overview+=table(['比較用戶','已有完整 7 天資料的用戶','前 7 天廣告收益總額','前 7 天平均廣告收益','限制'],[
            [esc({'exploration':'尋找條件的用戶','holdout':'留出來檢查的用戶'}.get(split,'其他用戶組')),cell(group['users']),cell(group['revenue_usd'],'usd'),cell(group['arpu_usd'],'usd'),esc(reasons_text(group['reasons']))]
            for split,group in segment['cohorts'].items()],'分群分母與收益')
        overview+='<p>限制：'+esc(reasons_text(segment['reasons']))+'。小樣本收益不顯示，未知不等於零。</p>'
        segment_specs={row['candidate_id']:row['event_spec'] for row in segment.get('event_specs',[])}
        segment_rows=[]
        for row in segment['candidates']:
            spec=segment_specs.get(row['candidate_id'])
            metric=row.get('metrics') or {}
            triggered=metric.get('groups',{}).get('triggered',{})
            name=(str(spec['window_hours'])+' 小時內，'+condition(spec['predicate'])) if spec else '先前的事件條件（未附完整設定）'
            segment_rows.append([esc(name),esc('留出來檢查的用戶' if row['split']=='holdout' else '尋找條件的用戶'),
                cell(triggered.get('users'))+' / '+cell(row['users']),cell(metric.get('coverage'),'percent'),
                cell(triggered.get('arpu_usd'),'usd'),cell(metric.get('delay_seconds',{}).get('median'),'hours'),
                esc(reasons_text(row['reasons']) or '仍需新資料確認')])
        overview+='<h3>這群用戶符合哪些事件？</h3><p>兩組用戶分開比較，不混合人數。過去收益較高不代表投放更有效。</p>'
        overview+=table(['事件條件','比較用戶','符合／比較人數','符合比例','符合者前 7 天平均廣告收益','一半符合者的達標時間','限制'],segment_rows,'分群事件比較')
        overview+=details('固定候選的分群指標與限制',segment['candidates'])+source('segment')
        overview+=details('原始候選完整打點規格',segment.get('event_specs',[]))
    overview+=details('來源資料範圍',summary.get('data_scope',{}))
    comparison = []
    evidence = []
    for row in rows:
        identity, metrics, spec = row["candidate_id"], row["metrics"] or {}, row["event_spec"]
        groups, comparisons = metrics.get("groups", {}), metrics.get("comparisons", {})
        link = '<a href="#candidate-'+esc(identity)+'">'+esc(label(identity))+'</a>'
        comparison.append([link, esc(str(spec["window_hours"])+" 小時內，"+condition(spec["predicate"])),
            cell(groups.get("triggered", {}).get("users"))+" / "+cell(groups.get("all", {}).get("users")), cell(metrics.get("coverage"), "percent"),
            cell(metrics.get("delay_seconds", {}).get("median"), "hours"), cell(groups.get("triggered", {}).get("arpu_usd"), "usd"),
            cell(comparisons.get("triggered_minus_all"), "usd"), esc(STATUS.get(row["evidence_status"], row["evidence_status"]))])
        body = '<p>'+esc(str(spec["window_hours"])+" 小時內，"+condition(spec["predicate"]))+'</p>'
        body += '<p>證據狀態：'+esc(STATUS.get(row["evidence_status"], row["evidence_status"]))+'。原因：'+esc(reasons_text(row["reasons"]) or "請結合人數、收益與限制一起判斷")+'</p>'
        body += table(["驗證人群", "用戶", "前 7 天平均廣告收益", "未知收益用戶"], [[esc(name), cell(groups.get(key, {}).get("users")),
            cell(groups.get(key, {}).get("arpu_usd"), "usd"), cell(groups.get(key, {}).get("unknown_revenue_users"))]
            for key,name in (("all","全體"),("triggered","符合條件"),("untriggered","不符合條件"))], "留出用戶的人數與收益")
        intervals = metrics.get("bootstrap", {}).get("intervals", {})
        body += table(["描述性比較", "差值 USD", "95% 下界 USD", "95% 上界 USD"], [[esc(name), cell(comparisons.get(key), "usd"),
            cell((intervals.get(key) or {}).get("lower"), "usd"), cell((intervals.get(key) or {}).get("upper"), "usd")]
            for key,name in (("triggered_minus_all","觸發 − 全體"),("triggered_minus_untriggered","觸發 − 未觸發"))], "不確定性（未作多重搜尋校正）")
        body += table(["安裝日 UTC", "觸發用戶", "未觸發用戶", "平均廣告收益差額（美元）"], [[esc(d["install_day"]), cell(d["triggered"]["users"]),
            cell(d["untriggered"]["users"]), cell(d["difference_usd"], "usd")] for d in metrics.get("days", [])], "逐日穩定性")
        body += '<p>一半的符合者在此時間內達標：'+cell(metrics.get("delay_seconds", {}).get("median"), "hours")+'；90% 的符合者在此時間內達標：'+cell(metrics.get("delay_seconds", {}).get("p90"), "hours")+'</p>'
        body += '<h4>如何使用這個事件？</h4><p>從'+esc({'first_open':'首次開啟 App','install':'安裝 App'}.get(spec["origin"],'設定的起點'))+'開始，在上述時間範圍內首次符合才回傳，每人一次；到期後不補發。包含起點，不包含結束時刻。完整事件名稱與設定可交給工程師查看下方詳情。</p>'
        body += details("可交付工程師的完整事件規格", spec)+details("探索階段選入依據（不是驗證結果）", row.get("selection_evidence"))
        body += source("validation", row["evidence"]["json_pointer"])+details("完整驗證值與計算方法", metrics)
        evidence.append('<article id="candidate-'+esc(identity)+'"><h3>'+esc(label(identity))+' · '+esc(STATUS.get(row["evidence_status"],row["evidence_status"]))+'</h3>'+body+'</article>')
    compare = '<p>這裡使用另外留出、已有完整 7 天資料的用戶。符合比例是符合條件的人數除以全部比較用戶數。收益差異不代表投放提升，編號也不是排名。精確數值可查阅資料下載。</p>'
    compare += table(["候選", "觸發條件", "符合／比較用戶數", "符合比例", "一半符合者的達標時間", "符合者前 7 天平均廣告收益", "相對全體差值", "證據"], comparison, "事件條件比較")
    sensitivity = diagnostics.get("sensitivity") or {}
    points = sensitivity.get("points", [])
    sensitivity_body = '<p>這裡使用尋找條件時的用戶，觀察同一類行為在相同時間範圍內，提高要求後的人數與收益變化。這不是另外一批用戶的獨立檢查。</p>'
    sensitivity_body += table(["候選", "條件類別／窗口", "門檻", "觸發／全體", "覆蓋", "前 7 天平均廣告收益", "99% 用戶收益不超過此值"], [[esc(label(p["candidate_id"])), esc(family_name(p["family"], p["threshold"])),
        cell(p["threshold"]), cell(p["triggered_users"])+" / "+cell(p["cohort_users"]), cell(p["coverage"], "percent"), cell(p["triggered_arpu_usd"], "usd"), cell(p["triggered_revenue_p99_usd"], "usd")] for p in points], "提高要求後，人數與收益如何變化？")
    overlap = diagnostics.get("overlap") or {}
    overlap_body = '<p>人群相似度＝同時符合兩個條件的人數，除以至少符合其中一個條件的人數。「A 也符合 B」以 A 的人數為分母，反向則以 B 為分母。兩者都沒有人符合時顯示未知。</p>'
    overlap_body += table(["A", "B", "A 人數", "B 人數", "交集", "聯集", "人群相似度", "A 也符合 B", "B 也符合 A"], [[esc(label(p["a"])), esc(label(p["b"])),
        *[cell(p[k]) for k in ("a_users","b_users","intersection","union")], *[cell(p[k], "percent") for k in ("jaccard","fraction_a_in_b","fraction_b_in_a")]]
        for p in overlap.get("pairs", []) if p["a"] != p["b"]], "不同條件選中的是同一批人嗎？")
    landmark = diagnostics.get("landmark") or {}
    post_body = '<p>第一個比較排除符合條件當下的收益，只看之後的收益。第二個比較在同一時間點，依用戶是否已符合條件分組，計算從該時間至滿 7 天之前的收益。這些是進一步觀察，所用人群與上方獨立留出的用戶不同。</p>'
    post_body += table(["候選", "觸發用戶", "符合後平均廣告收益", "未知收益"], [[esc(label(p["candidate_id"])), cell(p["users"]), cell(p["arpu_usd"], "usd"), cell(p["unknown_revenue_users"])] for p in landmark.get("post_trigger", [])], "符合條件之後的平均廣告收益")
    post_body += table(["候選", "共同時間點（小時）", "此前觸發用戶", "其剩餘平均廣告收益", "此前未觸發用戶", "其剩餘 ARPU"], [[esc(label(p["candidate_id"])), cell(p["landmark_hours"]),
        cell(p["triggered"]["users"]), cell(p["triggered"]["arpu_usd"], "usd"), cell(p["untriggered"]["users"]), cell(p["untriggered"]["arpu_usd"], "usd")] for p in landmark.get("landmarks", [])], "在相同時間點比較剩餘收益")
    guidance = '<p>'+esc(statement_text(model["test_guidance"]))+'</p><p>'+('本批資料不足以給出可上線的測試優先推薦。先補足驗證樣本或解決品質限制，再確認候選。' if empty else '先考慮有歷史資料支持的條件，沿用尋找條件時決定的順序，再依達標時間、符合人數與人群重疊安排測試。不用留出的檢查資料重新挑選排名，避免把偶然差異誤當可靠發現。')+'</p>'
    guidance += '<ul>'+''.join('<li>'+esc(statement_text(v))+'</li>' for v in model["limitations"])+'</ul>'
    audit = '<p>Run：<code>'+esc(model["run_id"])+'</code><br>Dataset：<code>'+esc(model["dataset_id"])+ '</code></p>'
    audit += details("配置、版本、來源 SHA256 與物件位置", model["audit"])+details("資料品質完整明細與排除紀錄", quality)+details("資料範圍與分布", profile)+details("已有完整 7 天資料的用戶與探索／驗證切分", targets)
    body = section("overview","分析摘要",overview)+section("comparison","候選比較",compare)+section("evidence","證據與打點規格",''.join(evidence) or '<p>沒有選入比較的條件；不生成假推薦。</p>')
    body += section("sensitivity","調整條件後的變化",sensitivity_body+source("sensitivity"))+section("overlap","候選重疊",overlap_body+source("overlap"))+section("remaining","符合條件之後的收益",post_body+source("landmark"))+section("guidance","測試建議與限制",guidance)+section("audit","技術與計算詳情",'<details><summary>展開完整追溯資料</summary>'+audit+'</details>')
    nav = ''.join(f'<a href="#{id}">{name}</a>' for id,name in (("overview","摘要"),("comparison","候選"),("evidence","證據"),("sensitivity","門檻"),("overlap","重疊"),("remaining","剩餘收益"),("audit","稽核")))
    return '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>'+esc(model["title"])+'</title><style>'+CSS+'</style></head><body><header><p class="brand">AC EVENT AGENT · D7 REPORT</p><h1>'+esc(model["title"])+'</h1><p class="notice">'+('合成資料測試，非客戶投放成效。' if model["synthetic"] else '歷史觀察性分析，非投放因果證據。')+'</p><nav aria-label="報告章節">'+nav+'</nav></header><main>'+body+'</main></body></html>'


CSS = """
:root{color-scheme:dark;background:#101114;color:#ecedef;font:14px/1.65 system-ui,sans-serif;font-variant-numeric:tabular-nums}
p{overflow-wrap:anywhere}
*{box-sizing:border-box}body{max-width:1280px;margin:auto;padding:32px 32px 64px}h1{font-size:28px;font-weight:600;letter-spacing:-.03em;margin:8px 0 16px}h2{font-size:20px;font-weight:600;margin:0 0 16px}h3{font-size:16px}h4{font-size:14px}p{max-width:90ch}a{color:#a8afff}a:focus-visible,summary:focus-visible,.table:focus-visible{outline:2px solid #a8afff;outline-offset:3px}.brand,.muted,.source{color:#a5a8b2}.brand{font-size:12px;letter-spacing:.08em}.source{font:12px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}.notice{padding:12px 16px;border-left:3px solid #bca16a;background:#202127;color:#e4ce9e}nav{display:flex;flex-wrap:wrap;gap:12px 24px;padding:12px 0}section{padding:28px 0;border-top:1px solid #2c2e35;scroll-margin-top:16px}.lead{font-size:18px;color:#ecedef}.table{overflow:auto;max-width:100%;margin:20px 0;background:#17181c;border:1px solid #2c2e35;border-radius:6px}table{width:100%;border-collapse:collapse;white-space:nowrap}caption{text-align:left;padding:12px;color:#a5a8b2;font-size:12px}th{color:#a5a8b2;font-size:12px;font-weight:500}td,th{padding:10px 12px;text-align:left;border-bottom:1px solid #2c2e35}td:nth-child(2){white-space:normal;min-width:130px;max-width:400px}tr:last-child td{border-bottom:0}article{padding:12px 0 28px;border-bottom:1px solid #2c2e35}code,pre{font:12px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#17181c;padding:16px;border-radius:6px;max-width:100%}details{margin:12px 0}summary{cursor:pointer;color:#a8afff;padding:6px 0}li{margin:8px 0}
@media(max-width:600px){body{padding:20px 16px 40px}h1{font-size:24px}.lead{font-size:16px}section{padding:24px 0}nav{gap:8px 16px}}
@media print{:root{color-scheme:light;background:white;color:#202126}body{padding:0;max-width:none}nav{display:none}.table,pre,.notice{background:white}a,summary,.source,.muted,th{color:#424650}.table{overflow:visible}table{white-space:normal;font-size:10px}td,th{padding:5px}.source{font-size:9px}h2,h3{break-after:avoid}tr{break-inside:avoid}}
"""
