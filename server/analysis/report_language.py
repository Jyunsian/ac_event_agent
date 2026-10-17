"""Human labels only. No metric recomputation or persisted report mutation."""
import json
from datetime import datetime, timezone
from pathlib import Path

REASONS = json.loads((Path(__file__).resolve().parents[2] / 'contracts' / 'reason_labels.json').read_text())

STATEMENTS = {
    '歷史關聯不等於投放因果效果。': '過去收益較高，不代表採用這個事件投廣告一定更有效。',
    '描述性區間未做多重搜尋校正。': '同時嘗試很多條件，可能偶然找到看似較好的結果。報告中的收益差異範圍並未排除這種影響。',
    '探索診斷與holdout驗證使用不同人群，不能混用分母。': '尋找條件與檢查結果使用不同的用戶；閱讀比例時，請使用各表標示的比較人數。',
    '先考慮歷史證據、覆蓋與觸發速度，再檢查人群重疊；以目前優化事件為對照追蹤D7。這不是已驗證的投放提升或完整實驗設計。': '先看哪些條件有資料支持，再比較符合人數、達標時間，以及是否選到同一群人。投放測試時可與目前使用的事件比較，追蹤前 7 天廣告收益；這裡還不是已證實的投放改善，也不是完整的實驗設計。',
}


def statement_text(value):
    return STATEMENTS.get(value, value)


def date_text(value):
    if not isinstance(value, str):
        return '未提供'
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return '時間未註明時區，請查看來源資料'
        return parsed.astimezone(timezone.utc).isoformat(sep=' ').replace('+00:00', ' UTC')
    except ValueError:
        return '時間資料無法辨識，請查看來源資料'


def reasons_text(codes):
    return '；'.join(dict.fromkeys(REASONS.get(code, '另有尚待確認的資料或分析限制，請查看詳細資料或詢問助理。') for code in codes))


def family_name(family, threshold):
    if not family:
        return '多個行為組合或先後順序（詳見完整設定）'
    predicate = {**family, 'threshold': threshold}
    return f'前 {_duration(family["window_hours"]*3600)}，{condition_name(predicate)}'


def event_name(spec):
    if spec.get("analysis_version")=="4.0-time-aware" and isinstance(spec.get("name"),str):return spec["name"]
    origin={'first_open':'首次開啟 App','install':'安裝'}.get(spec['origin'],'開始使用 App')
    predicate=spec['predicate'];threshold=predicate.get('threshold');scope=predicate.get('scope',{})
    window=_duration(spec['window_hours']*3600)
    if predicate.get('node')=='atom' and isinstance(threshold,(int,float)) and predicate.get('metric')=='level_time_to_reach_seconds':
        level=scope.get('level_index');target=f'第 {_compact(level)} 關' if isinstance(level,(int,float)) else '指定關卡'
        if predicate.get('comparator')=='lte':return f'{origin}後 {_duration(threshold)}內到達{target}'
        return f'{origin}後，超過 {_duration(threshold)}才到達{target}（只觀察前 {window}）'
    if predicate.get('node')=='atom' and isinstance(threshold,(int,float)) and predicate.get('metric')=='first_return_delay_seconds':
        if predicate.get('comparator')=='lte':return f'{origin}後 {_duration(threshold)}內首次回來使用 App'
        return f'{origin}後，超過 {_duration(threshold)}才首次回來使用 App（只觀察前 {window}）'
    if predicate.get('node')=='atom' and predicate.get('metric')=='return_in_interval':return condition_name(predicate)
    return f'{origin}後 {window}內，{condition_name(predicate)}'


def _compact(value, digits=2):
    rounded=round(float(value),digits)
    return f'{rounded:g}'


def _duration(seconds):
    if not isinstance(seconds,(int,float)) or seconds<0:return '時間未知'
    total_seconds=round(seconds)
    if total_seconds<60:return f'{total_seconds} 秒'
    whole_minutes,seconds_left=divmod(total_seconds,60)
    if whole_minutes<60:return f'{whole_minutes} 分鐘 {seconds_left} 秒' if seconds_left else f'{whole_minutes} 分鐘'
    minutes=round(total_seconds/60)
    hours,remainder=divmod(minutes,60)
    return f'{hours} 小時 {remainder} 分鐘' if remainder else f'{hours} 小時'


def _dollars(value):
    digits=8 if value<.0001 else 5 if value<.01 else 4
    return '$'+f'{value:.{digits}f}'.rstrip('0').rstrip('.')


def _atom_name(p):
    threshold=p.get('threshold');scope=p.get('scope',{});metric=p.get('metric')
    if not isinstance(threshold,(int,float)):return '條件資料不完整'
    amount=_compact(threshold);lte=p.get('comparator')=='lte'
    formats={'rewarded':'獎勵式廣告','interstitial':'插頁式廣告','banner':'橫幅廣告','app_open':'開屏廣告','native':'原生廣告','other':'其他類型廣告','unknown':'未分類廣告'}
    ad=formats.get(scope.get('ad_format'),'') if scope.get('ad_format')!='all' else ''
    if metric=='ad_count':return f'看過至少 {amount} 次{ad or "廣告"}'
    if metric=='ad_revenue_sum':return f'{ad or "廣告"}累積收益至少 {_dollars(threshold)}'
    if metric=='session_count':return f'使用 App 至少 {amount} 次'
    if metric=='first_return_delay_seconds':return f'安裝後 {_duration(threshold)}內首次回來使用 App' if lte else f'首次回來使用 App 時，距離安裝至少 {_duration(threshold)}'
    if metric=='return_in_interval':
        start,end=scope.get('start_hours'),scope.get('end_hours')
        return f'在安裝後第 {_compact(start)}～{_compact(end)} 小時期間回來使用 App' if isinstance(start,(int,float)) and isinstance(end,(int,float)) else '在指定期間回來使用 App'
    if metric=='return_interval_count':return f'在至少 {amount} 個不同時段回來使用 App'
    if metric=='consecutive_return_days':return f'連續回來使用 App 至少 {amount} 天'
    if metric=='post_return_session_count':return f'首次回訪後，又使用 App 至少 {amount} 次'
    if metric=='post_return_engaged_seconds':return f'首次回訪後，累積有效使用至少 {_duration(threshold)}'
    if metric=='level_start_count':return f'開始關卡至少 {amount} 次'
    if metric=='level_complete_count':return f'完成關卡至少 {amount} 次'
    if metric=='level_fail_count':return f'關卡失敗至少 {amount} 次'
    if metric=='distinct_completed_levels':return f'完成至少 {amount} 個不同關卡'
    if metric in ('max_completed_level_index','completed_level','reached_level'):return f'至少玩到第 {amount} 關'
    if metric=='level_time_to_reach_seconds':
        level=scope.get('level_index');target=f'第 {_compact(level)} 關' if isinstance(level,(int,float)) else '指定關卡'
        return f'在 {_duration(threshold)}內到達{target}' if lte else f'花了至少 {_duration(threshold)}才到達{target}'
    if metric=='attempts_per_level':return f'平均每關嘗試不超過 {amount} 次' if lte else f'平均每關嘗試至少 {amount} 次'
    if metric=='completes_per_session':return f'平均每次使用完成不超過 {amount} 關' if lte else f'平均每次使用完成至少 {amount} 關'
    if metric=='complete_start_ratio':return f'開始的關卡中，完成比例不超過 {_compact(threshold*100)}%' if lte else f'開始的關卡中，至少 {_compact(threshold*100)}% 有完成'
    if metric=='fail_start_ratio':return f'開始的關卡中，失敗比例不超過 {_compact(threshold*100)}%' if lte else f'開始的關卡中，至少 {_compact(threshold*100)}% 以失敗結束'
    if metric=='completion_duration_seconds':return f'完成一關通常不超過 {_duration(threshold)}' if lte else f'完成一關通常要花至少 {_duration(threshold)}'
    if metric=='consecutive_failures':return f'曾經連續失敗至少 {amount} 次'
    if metric=='retry_same_level':return f'同一關失敗後重試至少 {amount} 次'
    if metric=='complete_after_fail':return f'關卡失敗後又完成至少 {amount} 次'
    if metric=='session_after_fail':return f'關卡失敗後，另一次回來使用 App 至少 {amount} 次'
    return f'其他玩家行為{"不超過" if lte else "至少"} {amount}'


def condition_name(p):
    if p.get('node')=='boolean':
        return ('，而且' if p['operator']=='and' else '，或者').join('（'+condition_name(c)+'）' for c in p['clauses'])
    if p.get('node')=='sequence':
        names={'level_start_to_complete':'開始關卡後完成同一關','level_fail_to_start':'關卡失敗後重試同一關','level_fail_to_complete':'關卡失敗後完成同一關','level_fail_to_session_end':'關卡失敗後離開 App','session_start_to_level_complete':'打開 App 後完成關卡','level_complete_to_ad_impression':'完成關卡後看到廣告','rewarded_ad_to_level_complete':'看完獎勵式廣告後完成關卡'}
        repeats=f'，至少出現 {_compact(p["repeats"])} 次' if p['repeats']>1 else ''
        return f'{names.get(p["template"],"指定行為依序發生")}，兩個行為相隔不超過 {_duration(p["max_gap_seconds"])}{repeats}'
    if p.get('node')=='atom':
        return _atom_name(p)
    op = p['op']
    if op in ('and', 'or'):
        return ('，而且' if op == 'and' else '，或者').join('（'+condition_name(c)+'）' for c in p['clauses'])
    events = {'ad_impression': '展示廣告', 'session_start': '開始使用 App', 'session_end': '結束這次使用'}
    if op == 'sequence':
        repeats=f'，至少出現 {_compact(p["repeats"])} 次' if p['repeats']>1 else ''
        return '，接著'.join(events.get(s, '指定行為') for s in p['steps'])+f'，兩個行為相隔不超過 {_duration(p["max_gap_seconds"])}{repeats}'
    formats = {'rewarded': '獎勵式廣告', 'interstitial': '插頁式廣告', 'banner': '橫幅廣告', 'app_open': '開屏廣告', 'native': '原生廣告', 'other': '其他類型廣告', 'unknown': '未分類廣告'}
    ad = formats.get(p.get('ad_format'), '廣告')
    threshold = p['threshold']
    if op == 'count':
        event = events.get(p.get('event_name'), '展示'+ad) if p.get('event_name') != 'ad_impression' else '展示'+ad
        return f'{event}至少 {_compact(threshold)} 次'
    if op == 'revenue_sum':
        return f'{ad}累積收益至少 {_dollars(threshold)}'
    if op == 'session_count':
        return f'使用 App 至少 {_compact(threshold)} 次'
    if op == 'engaged_seconds':
        return f'累積有效使用至少 {_duration(threshold)}'
    return '其他條件（請查看完整設定）'
