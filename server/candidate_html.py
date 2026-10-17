"""Self-contained customer reader. Embedded evidence is inert, escaped JSON."""
import json
from pathlib import Path
from server.analysis.report_language import event_name, reasons_text


def render_candidate_html(payload):
    names={d['candidate_id']:event_name(d['event_spec']) for d in payload['details']}
    reasons={e['candidate_id']:reasons_text(e['reasons']) for e in payload['entries']}
    from server.candidate_reader import revenue_series
    encoded=json.dumps({**payload,'names':names,'reason_labels':reasons,'income_groups':revenue_series(payload)},ensure_ascii=False,
                       allow_nan=False,separators=(',', ':')).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    income_script=Path(__file__).with_name('candidate_income_html.js').read_text()+Path(__file__).with_name('candidate_search_html.js').read_text()
    return (HEADER+'<script id="evidence" type="application/json">'+encoded+'</script>'+SCRIPT.replace('</script></html>',income_script+'</script></html>')).encode('utf-8')


HEADER='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; base-uri 'none'; form-action 'none'">
<title>IAA 候選事件完整報告</title><style>
body{font:15px/1.6 system-ui;background:#17181d;color:#e3e4ea;margin:0;padding:24px;max-width:1400px;margin:auto}button,input,select{font:inherit;background:#272930;color:inherit;border:1px solid #636675;padding:7px;border-radius:5px}button{cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #a4abff}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:10px;border-bottom:1px solid #454754;text-align:left;vertical-align:top}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}details{margin:15px 0}label{display:inline-block;margin:8px}#card{border:1px solid #636675;padding:18px;margin-top:24px;overflow-wrap:anywhere}small{color:#b3b6c2}@media(max-width:600px){body{padding:12px}td,th{padding:6px}}
.scroll table{min-width:760px}.scroll th{white-space:nowrap}.scroll td{min-width:90px}.scroll td:first-child{min-width:180px}#rows td:first-child{min-width:320px;max-width:480px}#rows button{text-align:left}#card>table{table-layout:fixed}#card>table th{width:48%}.scroll{border:1px solid #454754;border-radius:5px} .scroll:focus-visible{outline:3px solid #a4abff}
</style><h1>IAA 候選事件報告</h1><p id="context"></p>
<p>固定安裝／首次開啟起點後前 W 小時達標，不是任意連續 W 小時。D7 為完整前 168 小時收益；歷史關聯不等於投放提升或 ROI 保證。未知／未計算不補零。</p>
<section id="income"><h2>累積收入門檻取捨</h2><p>同窗口、同廣告格式，兩圖使用相同收入門檻橫軸。缺值不補零，不跨缺值連線。點選或按Enter查看候選證據。</p><label>收入比較範圍 <select id="income-group"></select></label><div id="income-plots"></div></section>
<label>搜尋條件或 ID <input id="search" type="search"></label>
<label>起點後窗口 <select id="window"><option value="">全部窗口</option></select></label>
<label>類型 <select id="family"><option value="">全部類型</option><option value="atom">單一條件</option><option value="compound">且／或組合</option><option value="sequence">先後序列</option></select></label>
<label>廣告格式 <select id="format"><option value="">全部格式</option></select></label>
<label>角色 <select id="role"><option value="">全部角色</option><option>價值差較大</option><option>覆蓋較廣</option><option>達標較快</option><option value="unselected">非優先項</option></select></label>
<label>證據 <select id="status"><option value="">全部</option><option value="historically_validated">有歷史支持</option><option value="exploratory">探索結果</option><option value="insufficient_data">證據不足</option></select></label>
<label>排序 <select id="sort"><option value="candidate_id">固定順序</option><option value="difference_usd">D7 差額高到低</option><option value="coverage">覆蓋高到低</option><option value="p90_seconds">P90 快到慢</option></select></label>
<p id="count" aria-live="polite"></p><small>窄螢幕可在表格內左右滑動查看全部欄位。</small><div class="scroll" tabindex="0" role="region" aria-label="候選結果橫向捲動表"><table><thead><tr><th>完整條件</th><th>符合／未符合人數</th><th>覆蓋</th><th>符合／未符合 D7 ARPU（USD）</th><th>D7 差額（USD）</th><th>P50／P90 秒</th><th>證據／角色</th></tr></thead><tbody id="rows"></tbody></table></div>
<button id="prev">上一頁</button> <button id="next">下一頁</button><article id="card" tabindex="-1" hidden></article>
<section id="search-audit"><h2>搜尋範圍與排除紀錄</h2><p>只評估本次窗口與預算內的條件，不代表無限窮盡。超出預算的條件尚未評估，不是被資料否定。</p><div id="search-summary"></div><label>搜尋排除原因或條件 <input id="pruning-query" type="search"></label><p id="pruning-count" aria-live="polite"></p><div id="pruning-table"></div><button id="pruning-prev">上一頁紀錄</button> <button id="pruning-next">下一頁紀錄</button></section>
<details><summary>匯出範圍、來源與搜尋紀錄</summary><pre id="audit"></pre></details>
<noscript>請允許本地 JavaScript 才能搜尋與閱讀；完整證據已嵌入此檔，不需要網路。</noscript>
'''

SCRIPT='''<script>
'use strict';
const data=JSON.parse(document.getElementById('evidence').textContent),byId=new Map(data.details.map(d=>[d.candidate_id,d]));
const el=id=>document.getElementById(id),text=v=>v==null?'未知／此版本未計算':typeof v==='object'?JSON.stringify(v,null,2):String(v);
const status={historically_validated:'有歷史支持',exploratory:'探索結果',insufficient_data:'證據不足'};
let page=1;
function node(tag,value){const n=document.createElement(tag);n.textContent=text(value);return n;}
function section(root,title,value){const d=document.createElement('details');d.append(node('summary',title),node('pre',value));root.append(d);}
function grid(root,title,headers,rows){root.append(node('h3',title));if(!rows.length){root.append(node('p','此候選未計算'));return;}const wrap=document.createElement('div');wrap.className='scroll';const t=document.createElement('table'),head=document.createElement('tr');for(const h of headers)head.append(node('th',h));t.append(head);for(const values of rows){const tr=document.createElement('tr');for(const v of values)tr.append(node('td',v));t.append(tr);}wrap.append(t);root.append(wrap);}
function show(id){const d=byId.get(id),e=data.entries.find(e=>e.candidate_id===id),s=e.summary||{},card=el('card');card.replaceChildren();card.hidden=false;
card.append(node('h2',data.names[id]),node('p',(status[e.evidence_status]||e.evidence_status)+' · '+data.reason_labels[id]));
const table=document.createElement('table');
for(const [label,value] of [['覆蓋率',s.coverage],['達標 P50（秒）',s.median_seconds],['達標 P90（秒）',s.p90_seconds],['符合人數',s.triggered_users],['未符合人數',s.untriggered_users],['符合 D7 ARPU（USD）',s.triggered_arpu_usd],['未符合 D7 ARPU（USD）',s.untriggered_arpu_usd],['全體 D7 ARPU（USD）',s.all_arpu_usd],['D7 差額（USD）',s.difference_usd],['比較角色',s.role],['收益時間語意',d.timing_status]]){const tr=document.createElement('tr');tr.append(node('th',label),node('td',value));table.append(tr);}card.append(table);
const revenue=d.revenue_decomposition,m=d.validation.metrics,ci=m?.bootstrap?.intervals?.triggered_minus_untriggered;
grid(card,'完整 D7 三組收益',['人群','人數','ARPU（USD）','收益未知人數'],['all','triggered','untriggered'].map(k=>[({all:'全部比較用戶',triggered:'符合',untriggered:'未符合'})[k],m?.groups?.[k]?.users,m?.groups?.[k]?.arpu_usd,m?.groups?.[k]?.unknown_revenue_users]));
grid(card,'探索與驗證對照',['探索 D7 差額（USD）','驗證 D7 差額（USD）'],[[d.exploration?.difference_usd,m?.comparisons?.triggered_minus_untriggered]]);
const inference=d.validation.inference;
grid(card,'凍結家族統計檢驗',['家族候選數','單尾 Welch p','Holm 校正 p','校正檢查'],[[inference?.family_size,inference?.p_value,inference?.adjusted_p_value,inference?.passed===true?'通過':inference?.passed===false?'未通過':null]]);
card.append(node('p','優先名單於驗證前固定，不依驗證結果補選。Holm 通過仍須同時符合樣本、品質及每日方向等門檻。'));
grid(card,'共同切點至 D7 的剩餘收益',['起點後小時','已達標人數','未達標人數','已達標剩餘 ARPU（USD）','未達標剩餘 ARPU（USD）','差額（USD）'],(d.validation.landmarks||[]).map(p=>[p.window_hours,p.groups?.triggered?.users,p.groups?.untriggered?.users,p.groups?.triggered?.remaining?.arpu_usd,p.groups?.untriggered?.remaining?.arpu_usd,p.comparisons?.remaining?.difference_usd]));
card.append(node('p','共同 24／72／144 小時切點依當時是否已達標重新分組，只為優先候選計算；未計算不代表零收益，亦不同於個人觸發後收益。'));
if(d.selection?.similar_priority_id){const target=d.selection.similar_priority_id;card.append(node('p','探索人群 Jaccard 相似比例：'+text(d.selection.jaccard)));if(byId.has(target)){const button=node('button','查看相似優先候選：'+data.names[target]);button.onclick=()=>show(target);card.append(button);}else card.append(node('p','相似優先候選未包含於本次篩選匯出：'+target));}
card.append(node('p','95% Bootstrap 描述區間（USD）：'+text(ci?.lower)+' 至 '+text(ci?.upper)+'。描述區間不等於全家族檢驗通過。'));
grid(card,'窗口前後收益（USD）',['期間','符合 ARPU','未符合 ARPU','差額'],revenue?['before','remaining','d7'].map(k=>[({before:'起點至前 '+d.event_spec.window_hours+' 小時',remaining:d.event_spec.window_hours+' 至 168 小時',d7:'完整 D7'})[k],revenue.groups?.triggered?.[k]?.arpu_usd,revenue.groups?.untriggered?.[k]?.arpu_usd,revenue.comparisons?.[k]?.difference_usd]):[]);
card.append(node('p','晚期窗口剩餘時間較短，剩餘收益僅供診斷，不以此跨窗口排名。'));
grid(card,'成熟安裝批次觀測量（不是平台接收量）',['安裝日','用戶數','符合數','覆蓋比例'],(m?.days||[]).map(r=>[r.install_day,r.users,r.triggered_users,r.coverage]));
grid(card,'來源內收益比較（USD）',['來源','符合人數','未符合人數','符合 ARPU','未符合 ARPU','差額'],(d.source_diagnostics||[]).map(r=>[r.acquisition_source,r.triggered_users,r.untriggered_users,r.triggered_arpu_usd,r.untriggered_arpu_usd,r.difference_usd]));
card.append(node('p','任一來源組少於 20 人不顯示收益比較；來源診斷不改全量排序，也不代表排除混雜。'));
section(card,'窗口前／窗口後／完整 D7 原始收益分解',d.revenue_decomposition);
section(card,'探索集對照',d.exploration);section(card,'驗證、逐日、Bootstrap 區間與 Holm',d.validation);
section(card,'來源診斷（小樣本不顯示收益比較）',d.source_diagnostics);section(card,'優先選擇與相似替代',d.selection);
section(card,'完整工程規格與可追溯證據',d);card.focus();}
function render(){let rows=data.entries.filter(e=>{
 const s=e.summary||{},role=el('role').value;
 return (!el('status').value||e.evidence_status===el('status').value)&&
 (!el('window').value||e.window_hours===Number(el('window').value))&&
 (!el('family').value||s.family===el('family').value)&&
 (!el('format').value||(s.ad_formats||[]).includes(el('format').value))&&
 (!role||(role==='unselected'?!(data.report?.catalog?.priority_ids||[]).includes(e.candidate_id):s.role===role))&&
 (data.names[e.candidate_id]+' '+e.candidate_id).toLowerCase().includes(el('search').value.toLowerCase());});
const key=el('sort').value;rows.sort((a,b)=>{if(key==='candidate_id')return a.candidate_id.localeCompare(b.candidate_id);const x=a.summary?.[key],y=b.summary?.[key];return x==null?(y==null?a.candidate_id.localeCompare(b.candidate_id):1):y==null?-1:(key==='p90_seconds'?x-y:y-x)||a.candidate_id.localeCompare(b.candidate_id);});
page=Math.max(1,Math.min(page,Math.ceil(rows.length/50)));el('count').textContent='符合 '+rows.length+' / 匯出 '+data.entries.length+' 項；第 '+page+' 頁，每頁 50 項';el('rows').replaceChildren();
for(const e of rows.slice((page-1)*50,page*50)){const s=e.summary||{},tr=document.createElement('tr'),td=document.createElement('td'),button=node('button',data.names[e.candidate_id]);button.onclick=()=>show(e.candidate_id);td.append(button);tr.append(td);
for(const value of [text(s.triggered_users)+' / '+text(s.untriggered_users),s.coverage,text(s.triggered_arpu_usd)+' / '+text(s.untriggered_arpu_usd),s.difference_usd,text(s.median_seconds)+' / '+text(s.p90_seconds),(status[e.evidence_status]||e.evidence_status)+' / '+text(s.role)])tr.append(node('td',value));el('rows').append(tr);}
el('prev').disabled=page===1;el('next').disabled=page*50>=rows.length;}
for(const w of [...new Set(data.entries.map(e=>e.window_hours).filter(w=>typeof w==='number'))].sort((a,b)=>a-b)){const o=node('option','前 '+w+' 小時');o.value=String(w);el('window').append(o);}
for(const format of [...new Set(data.entries.flatMap(e=>e.summary?.ad_formats||[]))].sort()){const o=node('option',format);o.value=format;el('format').append(o);}
for(const id of ['search','status','sort','window','family','format','role'])el(id).oninput=()=>{page=1;render();};el('prev').onclick=()=>{page--;render();};el('next').onclick=()=>{page++;render();};
el('context').textContent=(data.export.synthetic?'合成測試資料 · ':'')+(data.export.export_scope==='complete'?'完整匯出':'篩選匯出')+' · 本次評估 '+data.export.evaluated_count+' 項，匯出 '+data.export.exported_count+' 項';
el('audit').textContent=JSON.stringify({export:data.export,search:data.search},null,2);render();
</script></html>'''
