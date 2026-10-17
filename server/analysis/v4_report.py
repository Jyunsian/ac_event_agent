"""One aggregate truth for Web, CSV, offline HTML and Agent references."""
import csv
import html
import json
import shutil
from pathlib import Path
from uuid import UUID
from server.analysis.v4_contract import ANALYSIS_VERSION
from server.analysis.v4_features import write_json
from server.analysis.ingest import file_hash
from server.analysis.v4_metrics import compact_evidence

LABELS={'ad_count':'廣告展示次數','ad_revenue_sum':'累積廣告收入（美元）','session_count':'不同遊玩次數',
        'level_start_count':'開始關卡次數','level_complete_count':'完成關卡次數','level_fail_count':'關卡失敗次數',
        'distinct_completed_levels':'完成不同關卡數','max_completed_level_index':'最高完成關卡','completed_level':'完成關卡進度',
        'reached_level':'到達關卡進度','retry_same_level':'失敗後重試次數','complete_after_fail':'失敗後完成次數',
        'session_after_fail':'失敗後再次開啟遊戲次數','consecutive_failures':'同關卡連續失敗次數',
        'return_in_interval':'指定時段回訪','return_interval_count':'回訪時段數','consecutive_return_days':'連續回訪日數',
        'post_return_session_count':'回訪後遊玩次數','post_return_engaged_seconds':'回訪後遊玩秒數',
        'first_return_delay_seconds':'首次回訪所需秒數','level_time_to_reach_seconds':'到達關卡所需秒數',
        'complete_start_ratio':'關卡完成比例','fail_start_ratio':'關卡失敗比例','attempts_per_level':'每關平均嘗試次數',
        'completion_duration_seconds':'完成關卡耗時中位數','completes_per_session':'每次遊玩完成關卡數',
        'level_start_to_complete':'開始關卡後完成','level_fail_to_start':'失敗後重試','level_fail_to_complete':'失敗後完成',
        'level_fail_to_session_end':'失敗後結束遊玩','session_start_to_level_complete':'開始遊玩後完成關卡',
        'level_complete_to_ad_impression':'完成關卡後觀看廣告','rewarded_ad_to_level_complete':'觀看獎勵廣告後完成關卡'}
STATUS={'historically_supported':'部分比較在另一批用戶也有相同結果，請看各時間點',
        'insufficient_data':'另一批用戶人數不足，還不能判斷','not_supported':'另一批用戶尚未支持這個結果','exploratory':'目前只作觀察，需要新資料確認'}


def rule_name(rule):
    def atom(p):
        name=LABELS.get(p['metric'],p['metric']);scope=p['scope'];suffix=''
        if scope.get('ad_format') not in (None,'all'):suffix="（"+{'rewarded':'獎勵廣告','interstitial':'插頁廣告','banner':'橫幅廣告','app_open':'開屏廣告','native':'原生廣告','other':'其他廣告','unknown':'格式未知'}.get(scope['ad_format'],scope['ad_format'])+"）"
        if 'level_index' in scope:suffix=f"（第 {scope['level_index']:g} 關）"
        if 'start_hours' in scope:suffix=f"（安裝後 {scope['start_hours']}～{scope['end_hours']} 小時）"
        return f"{name}{suffix}{'至少' if p['comparator']=='gte' else '至多'} {p['threshold']:g}"
    p=rule['predicate']
    if p['node']=='boolean':name=('，而且' if p['operator']=='and' else '，或').join(atom(c) for c in p['clauses'])
    elif p['node']=='sequence':name=f"{LABELS[p['template']]}，間隔不超過 {p['max_gap_seconds']/60:g} 分鐘，至少 {p['repeats']} 次"
    else:name=atom(p)
    return ('任意連續 24 小時內，' if rule['mode']=='rolling' else '')+name


def projection(row):
    point=row['observation'][0]
    return {'groups':point['groups'],'coverage':point['coverage'],'delay_seconds':point['delay_seconds'],
            'comparisons':{'triggered_minus_untriggered':point['difference_usd']},'display_checkpoint_hours':24,
            'observation_scope':'all_mature_users','time_comparisons':row['observation']}


def validate_report(value,run_id=None,dataset_id=None):
    if value.get('schema_version')!='4.0' or value.get('analysis_version')!=ANALYSIS_VERSION:raise ValueError('V4_REPORT_VERSION')
    for key,expected in [('run_id',run_id),('dataset_id',dataset_id)]:
        parsed=UUID(value[key])
        if expected is not None and parsed!=UUID(str(expected)):raise ValueError('V4_REPORT_IDENTITY')
    ids=[r['candidate_id'] for r in value['candidates']]
    if ids!=value['catalog']['priority_ids'] or len(set(ids))!=len(ids) or len(ids)>10:raise ValueError('V4_REPORT_PRIORITY')
    if not len(ids)<=value['catalog']['evaluated_count']<=2000 or not 0<=value['summary']['formal_comparison_count']<=2000:raise ValueError('V4_REPORT_COUNT')
    for digest in [value['catalog']['sha256'],value['audit']['frozen_sha256']]:
        if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('V4_REPORT_HASH')
    return value


def validate_catalog(value):
    if value.get('schema_version')!='4.0' or value.get('analysis_version')!=ANALYSIS_VERSION:raise ValueError('V4_CATALOG_VERSION')
    ids=[r['candidate_id'] for r in value['entries']]
    if len(ids)!=value['evaluated_count'] or len(ids)!=len(set(ids)) or len(ids)>2000 or not set(value['priority_ids'])<=set(ids):raise ValueError('V4_CATALOG_COUNT')
    return value


def table_html(row,scope='observation'):
    def num(v):return '尚無法判斷' if v is None else f'{v:,.4f}'.rstrip('0').rstrip('.') if isinstance(v,float) else str(v)
    columns=['觀察期限','目前符合玩家','這一天新增玩家','新增玩家七天平均收入','新增玩家七天總收入（美元）','占本群七天收入比例','比第一天多找到的玩家','比較點後平均收入','此時退出條件的玩家']
    body=[]
    for point in row[scope]:
        g=point['groups'];values=[f"{'首次開啟後' if row.get('origin')=='first_open' else '安裝後'} {point['hours']} 小時",g['triggered']['users'],g['added']['users'],g['added']['arpu_usd'],g['added']['revenue_usd'],g['added']['share_of_total_d7'],('此條件不適用 24 小時比較' if point.get('baseline_24h_applicable') is False else '第一天：比較基準' if point['hours']==24 else g['added_since_24h']['users']),g['triggered']['remaining_arpu_usd'],g['exited']['users']]
        body.append('<tr>'+''.join(f'<td>{html.escape(num(v))}</td>' for v in values)+'</tr>')
    return ('<p>此條件在指定時間重新判斷，玩家可能符合、退出或再次符合；不是持續累積的人群。</p>' if row[scope] and row[scope][0]['transition_kind']=='entered_exited' else '')+'<table><thead><tr>'+''.join(f'<th>{v}</th>' for v in columns)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table>'


def comparison_html(row):
    def n(v):return '尚無法判斷' if v is None else f'{v:g}'
    result='<h3>相比單純收入門檻，有什麼不同？</h3><p>同一時間比較；收入對照只在尋找條件的資料中選擇。實際覆蓋率可能不同。</p>'
    for scope,label in [('observation','全量玩家'),('exploration','找規律的玩家（探索集）'),('holdout','Holdout 驗證集')]:
        result+='<h4>'+label+'</h4><table><tr><th>觀察到（小時）</th><th>行為覆蓋比例</th><th>行為七天平均收入</th><th>收入對照條件</th><th>對照覆蓋比例</th><th>對照七天平均收入</th></tr>'
        for p in row.get(scope,[]):
            c=row['controls'].get(str(p['hours']),{});cp=c.get(scope,{})
            vals=[p['hours'],p['coverage'],p['groups']['triggered']['arpu_usd'],rule_name(c['rule']) if c else '無可靠對照',cp.get('coverage'),cp.get('groups',{}).get('triggered',{}).get('arpu_usd')]
            result+='<tr>'+''.join('<td>'+html.escape(v if isinstance(v,str) else n(v))+'</td>' for v in vals)+'</tr>'
        result+='</table>'
    if row.get('cumulative_comparison'):
        result+='<h3>集中遊玩和慢慢累積，有什麼不同？</h3><p>以下是同門檻的累積方案；與上面的集中達標人群比較，屬於描述結果。</p>'
        for scope,label in [('observation','全量玩家'),('exploration','找規律的玩家（探索集）'),('holdout','Holdout 驗證集')]:
            if scope in row['cumulative_comparison']:result+='<h4>'+label+'</h4>'+table_html({**row['cumulative_comparison'],'origin':row.get('origin')},scope)
    return result


def build_report(search_dir,validation_dir,run_id,dataset_id,destination):
    search_dir,validation_dir,root=map(Path,(search_dir,validation_dir,destination));root.mkdir(parents=True,exist_ok=False)
    search=json.loads((search_dir/'manifest.json').read_text());v=json.loads((validation_dir/'manifest.json').read_text())
    if not v['family_correction_complete'] or v['frozen_sha256']!=search['frozen_sha256']:raise ValueError('V4_REPORT_UNFINISHED_FAMILY')
    frozen=json.loads((search_dir/'frozen.json').read_text());explore={r['rule']['rule_id']:r for r in search['rules']}
    details={};entries=[]
    for record in v['results']:
        source=validation_dir/record['path']
        if file_hash(source)!=record['sha256']:raise ValueError('V4_DETAIL_CHECKSUM')
        row=json.loads(source.read_text());rid=row['candidate_id'];rule=row['rule'];metrics=projection(row)
        spec={'analysis_version':ANALYSIS_VERSION,'name':rule_name(rule),'event_name':'ac4_'+rid[:24],'origin':row['origin'],
              'window_hours':144,'predicate':rule['predicate'],'mode':rule['mode'],'rolling_hours':rule['rolling_hours'],
              'per_user_limit':1,'deadline_policy':'compare_24_48_72_96_120_144_not_automatically_recommended'}
        detail={'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'run_id':str(run_id),'dataset_id':str(dataset_id),
                'candidate_id':rid,'frozen_sha256':v['frozen_sha256'],'event_spec':spec,'candidate':rule,
                'validation':{**row,'metrics':metrics},'exploration':explore[rid],
                'selection':{'priority':rid in v['priority_ids']},'timing_status':'observed','diagnostics':[]}
        path=root/'catalog/details'/f'{rid}.json';write_json(path,detail);details[rid]=detail
        p=row['observation'][0];g=p['groups']
        summary={'event_spec':spec,'family':'compound' if rule['predicate']['node']=='boolean' else rule['predicate']['node'],
                 'ad_formats':sorted({c['scope']['ad_format'] for c in rule['predicate'].get('clauses',[rule['predicate']]) if c.get('scope',{}).get('ad_format')}),
                 'role':None,'selection':detail['selection'],'timing_status':'observed','triggered_users':g['triggered']['users'],
                 'untriggered_users':g['untriggered']['users'],'triggered_arpu_usd':g['triggered']['arpu_usd'],
                 'untriggered_arpu_usd':g['untriggered']['arpu_usd'],'all_arpu_usd':g['all']['arpu_usd'],
                 'difference_usd':p['difference_usd'],'coverage':p['coverage'],'mean_seconds':p['delay_seconds'].get('mean'),'median_seconds':p['delay_seconds']['median'],
                 'time_scopes':{scope:row[scope] for scope in ('exploration','holdout') if scope in row},'time_controls':row['controls'],'time_evidence':compact_evidence(row),'p90_seconds':p['delay_seconds']['p90'],'display_checkpoint_hours':24,'time_comparisons':row['observation']}
        entries.append({'candidate_id':rid,'window_hours':144,'category':rule['category'],'mode':rule['mode'],
                        'evidence_status':row['evidence_status'],'reasons':row['reasons'],'detail_sha256':file_hash(path),'summary':summary})
    catalog={'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'run_id':str(run_id),'dataset_id':str(dataset_id),
             'frozen_sha256':v['frozen_sha256'],'priority_ids':v['priority_ids'],'evaluated_count':len(entries),'entries':entries}
    validate_catalog(catalog);write_json(root/'catalog/catalog.json',catalog)
    # Complete exploration results are a separate export, not inflated into the report index.
    write_json(root/'catalog/search.json',{k:val for k,val in search.items() if k!='rules'})
    shutil.copyfile(search_dir/'manifest.json',root/'discovery.json')
    priority=[]
    for rid in v['priority_ids']:
        d=details[rid];row=d['validation']
        priority.append({'candidate_id':rid,'event_spec':d['event_spec'],'metrics':row['metrics'],
                         'evidence_status':row['evidence_status'],'reasons':row['reasons'],'evidence':{},
                         'time_analysis':{k:row[k] for k in ('observation','holdout','controls','inference','existing','origin','exploration') if k in row},'name':d['event_spec']['name']})
        if 'cumulative_comparison' in row:priority[-1]['time_analysis']['cumulative_comparison']=row['cumulative_comparison']
    model={'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'run_id':str(run_id),'dataset_id':str(dataset_id),
           'synthetic':v['synthetic'],'analysis_status':'analyzed','title':'找出有價值的行為，說清楚需要觀察多久',
           'candidates':priority,'catalog':{'sha256':file_hash(root/'catalog/catalog.json'),'priority_ids':v['priority_ids'],'evaluated_count':len(entries)},
           'summary':{'candidate_count':len(priority),'historically_validated_count':sum(r['evidence_status']=='historically_supported' for r in priority),
                      'searched_candidate_count':search['discovery_count'],'formal_comparison_count':v['family_size'],'reasons':[],
                      'quality':v['quality'],'data_profile':{'events':v['quality']['counts']['events']['retained_rows'],'users':v['quality']['counts']['users']['retained_rows'],'complete_through':v['targets']['split_definition']['complete_through']},'targets':v['targets']},
           'limitations':['本批觀察包含尋找條件的用戶，不能當作新用戶效果。','非收益行為依匯入事件時間判斷，未推測資料未提供的額外傳輸延遲；遊玩時長在結束事件後才可得。','新增辨識的收益不是額外創造的收入。',
                           '不同時間剩餘觀察長度不同，不直接比較剩餘收入選冠軍。','未自動選出唯一回傳期限，未驗證投放提升。'],
           'audit':{'frozen_sha256':v['frozen_sha256'],'search_sha256':file_hash(search_dir/'manifest.json'),
                    'validation_sha256':file_hash(validation_dir/'manifest.json'),'analysis_version':ANALYSIS_VERSION}}
    validate_report(model);write_json(root/'report.json',model)
    if (root/'report.json').stat().st_size>16*1024*1024:raise ValueError('V4_REPORT_INDEX_TOO_LARGE')
    columns=['rule_id','name','mode','scope','hours','triggered_users','untriggered_users','unknown_users','added_users',
             'added_d7_revenue','added_d7_arpu','added_d7_share','added_since_24h_users','baseline_24h_applicable','baseline_24h_unknown_users','exited_users','coverage',
             'd7_arpu','remaining_arpu','mean_seconds','median_seconds','p90_seconds','control_id','control_coverage','control_d7_arpu','evidence_status','tests_json','point_evidence_json']
    with (root/'report.csv').open('x',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for rid,d in details.items():
            row=d['validation']
            for scope in ('observation','exploration','holdout'):
                if scope not in row:continue
                for p in row.get(scope,[]):
                    g=p['groups'];control=row['controls'].get(str(p['hours']),{});cp=control.get(scope,{})
                    out={'rule_id':rid,'name':d['event_spec']['name'],'mode':d['candidate']['mode'],'scope':scope,'hours':p['hours'],
                         'triggered_users':g['triggered']['users'],'untriggered_users':g['untriggered']['users'],'unknown_users':g['unknown']['users'],
                         'added_users':g['added']['users'],'added_d7_revenue':g['added']['revenue_usd'],'added_d7_arpu':g['added']['arpu_usd'],
                         'added_d7_share':g['added']['share_of_total_d7'],'added_since_24h_users':g['added_since_24h']['users'],'baseline_24h_applicable':p.get('baseline_24h_applicable'),'baseline_24h_unknown_users':p.get('baseline_24h_unknown_users'),'exited_users':g['exited']['users'],
                         'coverage':p['coverage'],'d7_arpu':g['triggered']['arpu_usd'],'remaining_arpu':g['triggered']['remaining_arpu_usd'],
                         'mean_seconds':p['delay_seconds'].get('mean'),'median_seconds':p['delay_seconds']['median'],'p90_seconds':p['delay_seconds']['p90'],
                         'control_id':control.get('rule_id'),'control_coverage':cp.get('coverage'),
                         'control_d7_arpu':cp.get('groups',{}).get('triggered',{}).get('arpu_usd'),'evidence_status':row['evidence_status'],
                         'tests_json':json.dumps([t for t in row['inference'] if t['hours']==p['hours']],ensure_ascii=False) if scope=='holdout' else ''}
                    out['point_evidence_json']=json.dumps({'point':p,'control':control.get(scope),'cumulative_comparison':next((c for c in row.get('cumulative_comparison',{}).get(scope,[]) if c['hours']==p['hours']),None)},ensure_ascii=False)
                    writer.writerow(out)
    body='<h1>'+model['title']+'</h1><p>'+('合成資料示範。' if v['synthetic'] else '')+'所有金額為美元；完整七天收入是比較目標，不是投放提升。</p>'
    body+='<h2>這批資料可以分析什麼？</h2><p>已搜尋 '+str(search['discovery_count'])+' 條基本規則；正式比較 '+str(v['family_size'])+' 項。未完整驗證的規則保留於搜尋匯出。</p>'
    body+='<h2>多觀察一天，能多找到誰？</h2>'
    for rid,d in details.items():
        row=d['validation'];body+='<details><summary>'+html.escape(d['event_spec']['name'])+'</summary><p>本批觀察</p>'+table_html(row)
        if 'exploration' in row:body+='<h3>找規律的玩家（探索集）</h3>'+table_html(row,'exploration')
        body+='<h3>Holdout 驗證集</h3>'+table_html(row,'holdout')+comparison_html(row)
        body+='<p>'+STATUS[row['evidence_status']]+'</p><details><summary>另一批用戶及收入對照的完整證據</summary><pre>'+html.escape(json.dumps(row,ensure_ascii=False,indent=2))+'</pre></details></details>'
    body+='<h2>目前值得比較哪些方案？</h2><p>同一時間比較人數、七天收益和收入對照，再決定等待時間。樣本不足時先保留觀察；沒有唯一最佳期限。</p>'
    (root/'report.html').write_text('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V4 行為與時間分析</title><style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:24px;color:#20252b}details{margin:16px 0;overflow:auto}table{border-collapse:collapse;min-width:680px}td,th{padding:12px;text-align:left;border-bottom:1px solid #ddd}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer;font-weight:600}</style>'+body+'</html>')
    write_json(root/'manifest.json',{'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'stage':'report_v4',
                                  'artifacts':[{'path':p.relative_to(root).as_posix(),'sha256':file_hash(p),'size_bytes':p.stat().st_size} for p in sorted(root.rglob('*')) if p.is_file()]})
    return model
