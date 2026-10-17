from server.analysis.report_language import condition_name, reasons_text, date_text, statement_text, family_name, event_name
from server.analysis.report_html import cell


def test_conditions_keep_semantics_and_escape_untrusted_text():
    assert condition_name({'op':'count','threshold':5,'ad_format':'rewarded'}) == '展示獎勵式廣告至少 5 次'
    assert '或者' in condition_name({'op':'or','clauses':[{'op':'count','threshold':1},{'op':'session_count','threshold':2}]})
    assert '至少出現 2 次' in condition_name({'op':'sequence','steps':['session_start','ad_impression'],'max_gap_seconds':120,'repeats':2})
    assert '&lt;script&gt;' in cell('<script>')


def test_common_summary_reason_and_readable_agent_window():
    assert '暫時不能選出優先測試' in reasons_text(['NO_HISTORICALLY_VALIDATED_CANDIDATES'])
    assert event_name({'origin':'first_open','window_hours':72.0,'predicate':{'op':'count','threshold':5}})=='首次開啟 App後 72 小時內，展示廣告至少 5 次'
    assert event_name({'origin':'install','window_hours':3.0,'predicate':{'node':'atom','metric':'level_time_to_reach_seconds','comparator':'gte','threshold':10216.99,'scope':{'level_index':3}}})=='安裝後，超過 2 小時 50 分鐘才到達第 3 關（只觀察前 3 小時）'


def test_unknown_is_not_zero_and_tiny_revenue_remains_visible():
    assert '未知' in cell(None, 'usd')
    assert '0.000000 美元' not in cell(1e-8, 'usd')
    assert 'data-value="1e-08"' in cell(1e-8, 'usd')
    assert '用戶太少' in reasons_text(['INSUFFICIENT_GROUP_USERS'])
    assert 'PRIVATE_CODE' not in reasons_text(['PRIVATE_CODE'])


def test_readable_time_and_family_preserve_meaning():
    assert date_text('2026-01-14T08:00:00+08:00') == '2026-01-14 00:00:00 UTC'
    assert '未註明時區' in date_text('2026-01-14T00:00:00')
    assert date_text(None) == '未提供'
    assert family_name({'op':'revenue_sum','ad_format':'rewarded','window_hours':3}, 0.00000001) == '前 3 小時，獎勵式廣告累積收益至少 $0.00000001'
    assert 'holdout' not in statement_text('探索診斷與holdout驗證使用不同人群，不能混用分母。')
    assert statement_text('客戶提供的其他限制') == '客戶提供的其他限制'
