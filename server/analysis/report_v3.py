"""Customer V3 JSON/CSV and self-contained offline HTML from verified catalog artifacts."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from uuid import UUID

from server.analysis.catalog_v3 import validate_catalog_v3
from server.analysis.ingest import IngestError,file_hash

CSV_COLUMNS=("candidate_id","category","indicator_type","observation_start_hours","observation_end_hours","decision_time_hours",
             "trigger_mode","evidence_status","triggered_users","untriggered_users","unknown_users","coverage",
             "d2_early_difference_usd","d2_remaining_difference_usd","d3_early_difference_usd","d3_remaining_difference_usd",
             "d7_difference_usd","detail_sha256","reasons_json","predicate_json")


def validate_report_v3_header(value,*,run_id=None,dataset_id=None):
    """Validate the bounded V3 report index before any API returns its bytes."""
    if not isinstance(value,dict) or value.get("schema_version")!="3.0" or value.get("analysis_version")!="3.0-casual-game":
        raise ValueError("INVALID_V3_REPORT_VERSION")
    for key,expected in (("run_id",run_id),("dataset_id",dataset_id)):
        try:parsed=UUID(value[key])
        except (KeyError,ValueError,TypeError):raise ValueError("V3_REPORT_IDENTITY_MISMATCH") from None
        if expected is not None and parsed!=UUID(str(expected)):raise ValueError("V3_REPORT_IDENTITY_MISMATCH")
    candidates=value.get("candidates");summary=value.get("summary");catalog=value.get("catalog");audit=value.get("audit")
    if (not isinstance(candidates,list) or len(candidates)>10 or not isinstance(summary,dict)
            or not isinstance(catalog,dict) or not isinstance(audit,dict)):
        raise ValueError("INVALID_V3_REPORT_HEADER")
    ids=[row.get("candidate_id") for row in candidates if isinstance(row,dict)]
    if (len(ids)!=len(candidates) or len(ids)!=len(set(ids)) or summary.get("candidate_count")!=len(ids)
            or catalog.get("priority_ids")!=ids or type(catalog.get("evaluated_count")) is not int
            or not len(ids)<=catalog["evaluated_count"]<=2000):
        raise ValueError("V3_REPORT_CATALOG_MISMATCH")
    for digest in (catalog.get("sha256"),audit.get("frozen_sha256")):
        if not isinstance(digest,str) or len(digest)!=64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("INVALID_V3_REPORT_DIGEST")
    return value


def _safe(value):
    if isinstance(value,str) and value.lstrip().startswith(("=","+","-","@","\t","\r","\n")):return "'"+value
    return "" if value is None else value


def _offline_html(payload):
    encoded=json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False).replace("&","\\u0026").replace("<","\\u003c").replace(">","\\u003e")
    return f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; base-uri 'none'">
<title>Casual Game 候選事件分析</title><style>
:root{{--bg:#17181d;--panel:#202127;--line:#3b3d46;--text:#ededef;--muted:#a5a8b2;--accent:#8b94e8}}*{{box-sizing:border-box}}body{{margin:auto;max-width:1320px;padding:24px;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,sans-serif}}h1{{font-size:clamp(28px,4vw,44px);letter-spacing:-.03em}}p{{max-width:72ch;color:var(--muted)}}select,button{{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px 10px}}button:focus-visible,select:focus-visible,[tabindex]:focus-visible{{outline:3px solid var(--accent);outline-offset:2px}}.layout{{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(280px,.8fr);gap:20px}}main,aside,#detail{{min-width:0}}#detail{{overflow-wrap:anywhere}}section{{border-top:1px solid var(--line);padding-block:20px}}svg{{width:100%;height:420px;background:var(--panel);border-radius:8px}}circle{{fill:var(--accent);cursor:pointer}}table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}th,td{{text-align:left;padding:9px;border-bottom:1px solid var(--line);vertical-align:top}}.scroll{{max-width:100%;overflow:auto}}pre{{white-space:pre-wrap;word-break:break-word}}@media(max-width:720px){{body{{padding:16px}}.layout{{grid-template-columns:minmax(0,1fr)}}svg{{height:320px}}table,tbody,tr,td{{display:block;width:100%}}thead{{position:absolute;inline-size:1px;block-size:1px;overflow:hidden;clip-path:inset(50%)}}tr{{border-bottom:1px solid var(--line);padding-block:8px}}td{{display:grid;grid-template-columns:minmax(96px,.7fr) minmax(0,1fr);gap:8px;border:0;padding:4px 9px;overflow-wrap:anywhere}}td::before{{content:attr(data-label);color:var(--muted)}}}}@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto!important}}}}
</style><h1>Casual Game 候選事件分析</h1><p>完整 Validation Family 與 72 小時共同觀察點。歷史關聯不代表投放提升；未知值不補零。</p>
<label>Category <select id="category"><option value="all">全部</option></select></label><p id="count"></p><div class="layout"><main><section><h2>72 小時候選價值圖</h2><p>X 是 0 至 72 小時 ARPU 差，Y 是 72 至 168 小時 ARPU 差。只有 72 小時前完整可判定且數值完整的候選會畫點。</p><svg id="plot" viewBox="0 0 800 420" role="img" aria-label="72 小時候選價值散點圖"></svg></section><section><h2>可及性數據表</h2><div class="scroll"><table><thead><tr><th>候選</th><th>Category</th><th>X</th><th>Y</th><th>狀態</th></tr></thead><tbody id="rows"></tbody></table></div></section></main><aside><section><h2>候選證據</h2><div id="detail"><p>選取圖上點或表格候選查看精確證據。</p></div></section></aside></div>
<details><summary>完整 Discovery 搜尋紀錄</summary><pre id="search"></pre></details><script id="payload" type="application/json">{encoded}</script><script>
const data=JSON.parse(document.getElementById('payload').textContent),select=document.getElementById('category'),svg=document.getElementById('plot'),rows=document.getElementById('rows'),detail=document.getElementById('detail');
const cats=[...new Set(data.value_map.points.map(p=>p.category))];cats.forEach(c=>select.add(new Option(c,c)));document.getElementById('search').textContent=JSON.stringify(data.search,null,2);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function show(id){{const d=data.details[id];detail.innerHTML='<h3>'+esc(d.event_spec.event_name)+'</h3><p>Candidate ID: '+esc(id)+'</p><p>Category: '+esc(d.candidate.category)+'</p><p>Evidence: '+esc(d.validation.evidence_status)+'</p><p>Decision time: '+esc(d.candidate.decision_time_hours)+' hours</p><details><summary>完整 JSON 證據</summary><pre>'+esc(JSON.stringify(d,null,2))+'</pre></details>';}}
function draw(){{const points=data.value_map.points.filter(p=>select.value==='all'||p.category===select.value),known=points.filter(p=>p.chart_status==='PLOTTED');document.getElementById('count').textContent='可繪製 '+known.length+' / 全部 '+points.length;svg.innerHTML='';
const xs=known.map(p=>p.x_early_72h_difference_usd),ys=known.map(p=>p.y_remaining_72_168h_difference_usd),extent=a=>[Math.min(0,...a),Math.max(0,...a)],xe=extent(xs),ye=extent(ys),scale=(v,e,size,offset)=>offset+(v-e[0])/(e[1]-e[0]||1)*size;
known.forEach(p=>{{const c=document.createElementNS('http://www.w3.org/2000/svg','circle');c.setAttribute('cx',scale(p.x_early_72h_difference_usd,xe,700,50));c.setAttribute('cy',370-scale(p.y_remaining_72_168h_difference_usd,ye,320,30));c.setAttribute('r','7');c.setAttribute('tabindex','0');c.setAttribute('role','button');c.setAttribute('aria-label',p.category+' X '+p.x_early_72h_difference_usd+' Y '+p.y_remaining_72_168h_difference_usd);const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=p.candidate_id+' | X '+p.x_early_72h_difference_usd+' | Y '+p.y_remaining_72_168h_difference_usd;c.append(title);c.onclick=()=>show(p.candidate_id);c.onkeydown=e=>{{if(e.key==='Enter'||e.key===' '){{e.preventDefault();show(p.candidate_id)}}}};svg.append(c)}});
const number=v=>v===null||v===undefined?'未知':Number(v).toLocaleString('zh-Hant',{{maximumFractionDigits:6}});
rows.innerHTML=points.map(p=>'<tr><td data-label="候選"><button data-id="'+p.candidate_id+'">'+p.candidate_id.slice(0,10)+'</button></td><td data-label="Category">'+esc(p.category)+'</td><td data-label="X">'+esc(number(p.x_early_72h_difference_usd))+'</td><td data-label="Y">'+esc(number(p.y_remaining_72_168h_difference_usd))+'</td><td data-label="狀態">'+esc(p.chart_status)+'</td></tr>').join('');rows.querySelectorAll('button').forEach(b=>b.onclick=()=>show(b.dataset.id));}}
select.onchange=draw;draw();
</script></html>'''.encode()


def build_report_v3(catalog_dir,validation_dir,destination,segment_dir=None):
    catalog_dir,validation_dir,destination=map(Path,(catalog_dir,validation_dir,destination))
    source_paths=(catalog_dir/"catalog.json",catalog_dir/"search.json",catalog_dir/"candidate_value_map_v3.json",validation_dir/"manifest.json")
    hashes=[file_hash(path) for path in source_paths]
    catalog=validate_catalog_v3(json.loads(source_paths[0].read_text()));search=json.loads(source_paths[1].read_text());value_map=json.loads(source_paths[2].read_text());validation=json.loads(source_paths[3].read_text())
    details={}
    for entry in catalog["entries"]:
        path=catalog_dir/"details"/f'{entry["candidate_id"]}.json'
        if file_hash(path)!=entry["detail_sha256"]:raise IngestError("V3_REPORT_DETAIL_CHECKSUM_MISMATCH")
        details[entry["candidate_id"]]=json.loads(path.read_text())
    priority=[]
    for identity in catalog["priority_ids"]:
        detail=details[identity]
        priority.append({"candidate_id":identity,"evidence_status":detail["validation"]["evidence_status"],"reasons":detail["validation"]["reasons"],
            "metrics":detail["validation"]["metrics"],"event_spec":detail["event_spec"],"selection_evidence":detail["selection"],
            "evidence":{"detail_sha256":next(e["detail_sha256"] for e in catalog["entries"] if e["candidate_id"]==identity)}})
    mature_users=0
    if priority:
        groups=priority[0]["metrics"]["groups"]
        mature_users=sum(groups[name]["users"] for name in ("triggered","untriggered","unknown"))
    report={"schema_version":"3.0","analysis_version":"3.0-casual-game","run_id":catalog["run_id"],"dataset_id":catalog["dataset_id"],
        "synthetic":catalog["synthetic"],"analysis_status":"analyzed","summary":{"candidate_count":len(priority),
            "historically_validated_count":sum(row["evidence_status"]=="historically_supported" for row in priority),
            "searched_candidate_count":search["discovery_count"],"reasons":[],"quality":{},"targets":{"mature_users":mature_users},"data_profile":None},
        "candidates":priority,"catalog":{"sha256":hashes[0],"evaluated_count":catalog["evaluated_count"],"priority_ids":catalog["priority_ids"]},
        "value_map":value_map,
        # Full all-mature observations are already immutable per-candidate
        # details. Do not duplicate 2,000 copies into the bounded report index.
        "validation_results":[{key:value for key,value in row.items() if key!="observation"} for row in validation["results"]],
        "limitations":["主表使用全部成熟用戶，屬同批描述性關聯，不是獨立驗證或投放因果效果。","Holdout 只提供額外重現證據；樣本不足不抹掉本批觀察。","未知值不補零。","晚於 72 小時可判定的候選不畫入 72 小時圖。"],
        "audit":{"pipeline_version":"3.0-casual-game","analysis_version":"3.0-casual-game","policy_identity":catalog["policy_identity"],
                 "frozen_sha256":catalog["frozen_sha256"],"sources":{"catalog":{"sha256":hashes[0]},"validation":{"sha256":hashes[3]},"value_map":{"sha256":hashes[2]}}}}
    if segment_dir is not None:
        segment_path=Path(segment_dir)/"manifest.json";segment_hash=file_hash(segment_path)
        segment=json.loads(segment_path.read_text())
        if segment.get("schema_version")!="3.0" or segment.get("analysis_version")!="3.0-casual-game":
            raise IngestError("V3_SEGMENT_VERSION_MISMATCH")
        report["summary"]["segment"]=segment
        report["audit"]["sources"]["segment"]={"sha256":segment_hash}
    payload={"report":report,"catalog":catalog,"value_map":value_map,"details":details,"search":search}
    destination.mkdir(parents=True,exist_ok=False)
    packaged=destination/"catalog";packaged.mkdir();(packaged/"details").mkdir()
    for name in ("catalog.json","search.json","candidate_value_map_v3.json"):
        (packaged/name).write_bytes((catalog_dir/name).read_bytes())
    for entry in catalog["entries"]:
        name=f'{entry["candidate_id"]}.json';(packaged/"details"/name).write_bytes((catalog_dir/"details"/name).read_bytes())
    json_path=destination/"report_v3.json"
    with json_path.open("x") as stream:json.dump(report,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    csv_path=destination/"report_v3.csv"
    with csv_path.open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=CSV_COLUMNS);writer.writeheader()
        for entry in catalog["entries"]:
            detail=details[entry["candidate_id"]];result=detail["validation"];metrics=result["metrics"];observation=result.get("observation") or {"membership":result["membership"],"checkpoints":result["checkpoints"]};check=observation["checkpoints"]
            row={"candidate_id":entry["candidate_id"],"category":entry["category"],"indicator_type":entry["indicator_type"],
                "observation_start_hours":entry["observation_start_hours"],"observation_end_hours":entry["observation_end_hours"],
                "decision_time_hours":entry["decision_time_hours"],"trigger_mode":entry["trigger_mode"],"evidence_status":entry["evidence_status"],
                "triggered_users":observation["membership"]["triggered_users"],"untriggered_users":observation["membership"]["untriggered_users"],
                "unknown_users":observation["membership"]["unknown_users"],"coverage":metrics["coverage"],
                "d2_early_difference_usd":check["d2"]["comparisons"]["early"]["difference_usd"] if check["d2"]["comparisons"] else None,
                "d2_remaining_difference_usd":check["d2"]["comparisons"]["remaining"]["difference_usd"] if check["d2"]["comparisons"] else None,
                "d3_early_difference_usd":check["d3"]["comparisons"]["early"]["difference_usd"] if check["d3"]["comparisons"] else None,
                "d3_remaining_difference_usd":check["d3"]["comparisons"]["remaining"]["difference_usd"] if check["d3"]["comparisons"] else None,
                "d7_difference_usd":metrics["comparisons"]["triggered_minus_untriggered"],"detail_sha256":entry["detail_sha256"],
                "reasons_json":json.dumps(entry["reasons"],ensure_ascii=False,separators=(",",":")),
                "predicate_json":json.dumps(detail["candidate"]["predicate"],ensure_ascii=False,sort_keys=True,separators=(",",":"))}
            writer.writerow({key:_safe(value) for key,value in row.items()})
    html_path=destination/"report_v3.html";html_path.write_bytes(_offline_html(payload))
    for suffix,path in (("json",json_path),("csv",csv_path),("html",html_path)):
        (destination/f"report.{suffix}").write_bytes(path.read_bytes())
    for path,digest in zip(source_paths,hashes):
        if file_hash(path)!=digest:raise IngestError("V3_REPORT_SOURCE_CHANGED")
    if segment_dir is not None and file_hash(Path(segment_dir)/"manifest.json")!=segment_hash:
        raise IngestError("V3_REPORT_SOURCE_CHANGED")
    artifacts=[]
    for path in (json_path,csv_path,html_path,destination/"report.json",destination/"report.csv",destination/"report.html"):
        artifacts.append({"name":path.stem,"path":path.name,"sha256":file_hash(path),"size_bytes":path.stat().st_size})
    for path in sorted(packaged.rglob("*.json")):
        artifacts.append({"name":"candidate_"+path.stem,"path":path.relative_to(destination).as_posix(),"sha256":file_hash(path),"size_bytes":path.stat().st_size})
    manifest={"schema_version":"3.0","analysis_version":"3.0-casual-game","stage":"report_v3","source_hashes":hashes,"artifacts":artifacts}
    partial=destination/"manifest.partial.json"
    with partial.open("x") as stream:json.dump(manifest,stream,sort_keys=True,indent=2);stream.flush();os.fsync(stream.fileno())
    os.link(partial,destination/"manifest.json");partial.unlink()
    return report
