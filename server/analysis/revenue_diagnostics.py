"""Fixed-window revenue decomposition, using event time for realized D7 value."""
import math


def prepare_revenue_windows(connection,windows):
    """Connection-local reuse for immutable validation targets/events, not memberships."""
    windows=sorted(set(windows))
    if any(type(w) not in (int,float) or not math.isfinite(w) or not 0<w<=168 for w in windows):
        raise ValueError('INVALID_REVENUE_WINDOW')
    connection.execute('''CREATE TEMP TABLE revenue_window_values(
        window_hours DOUBLE,app_id VARCHAR,user_id VARCHAR,installed_at TIMESTAMPTZ,
        d7_revenue_usd DOUBLE,before_usd DOUBLE,remaining_usd DOUBLE)''')
    connection.execute('CREATE TEMP TABLE prepared_revenue_windows(window_hours DOUBLE PRIMARY KEY)')
    for window in windows:
        connection.execute('''INSERT INTO revenue_window_values
            SELECT ?,t.app_id,t.user_id,t.installed_at,t.d7_revenue_usd,
            CASE WHEN t.d7_revenue_usd IS NULL THEN NULL ELSE
                coalesce(sum(e.revenue_usd ORDER BY e.revenue_usd) FILTER (WHERE e.event_time<t.installed_at+?*INTERVAL '1 hour'),0) END,
            CASE WHEN t.d7_revenue_usd IS NULL THEN NULL ELSE
                coalesce(sum(e.revenue_usd ORDER BY e.revenue_usd) FILTER (WHERE e.event_time>=t.installed_at+?*INTERVAL '1 hour'),0) END
            FROM targets t LEFT JOIN events e ON t.app_id=e.app_id AND t.user_id=e.user_id
                AND e.event_name='ad_impression' AND e.event_time>=t.installed_at
                AND e.event_time<t.installed_at+INTERVAL '168 hours'
            WHERE t.is_mature AND t.split='holdout'
            GROUP BY t.app_id,t.user_id,t.installed_at,t.d7_revenue_usd''',[window,window,window])
        connection.execute('INSERT INTO prepared_revenue_windows VALUES (?)',[window])
    return {window:connection.execute('''SELECT app_id,user_id,d7_revenue_usd,before_usd,remaining_usd
        FROM revenue_window_values WHERE window_hours=? ORDER BY app_id,user_id''',[window]).fetchall()
        for window in windows}


def decompose_prepared_membership(values,delays,window_hours,*,landmark=False):
    """Reuse immutable per-user values and the caller's exact aligned trigger delays."""
    if type(window_hours) not in (int,float) or not math.isfinite(window_hours) or not 0<window_hours<=168:
        raise ValueError('INVALID_REVENUE_WINDOW')
    if any(type(index) is not int or not 0<=index<len(values) or delay is None
           or not math.isfinite(delay) or delay<0 for index,delay in delays.items()):
        raise ValueError('INVALID_REVENUE_MEMBERSHIP')
    cutoff=round(window_hours*3600*1000000)
    records=[(app,user,index in delays and (not landmark or round(delays[index]*1000000)<cutoff),d7,before,remaining)
             for index,(app,user,d7,before,remaining) in enumerate(values)]
    return _summarize_records(records,window_hours,landmark)


def decompose_revenue(connection, candidate_id, window_hours, *, landmark=False,prepared=False):
    if type(window_hours) not in (int,float) or not math.isfinite(window_hours) or not 0<window_hours<=168:
        raise ValueError('INVALID_REVENUE_WINDOW')
    if prepared:
        if not connection.execute('SELECT 1 FROM prepared_revenue_windows WHERE window_hours=?',[window_hours]).fetchone():
            raise ValueError('REVENUE_WINDOW_NOT_PREPARED')
        records=connection.execute('''SELECT t.app_id,t.user_id,r.triggered_at IS NOT NULL,
            t.d7_revenue_usd,t.before_usd,t.remaining_usd
            FROM revenue_window_values t LEFT JOIN triggers r
                ON t.app_id=r.app_id AND t.user_id=r.user_id AND r.candidate_id=?
                AND (NOT ? OR r.triggered_at<t.installed_at+?*INTERVAL '1 hour')
            WHERE t.window_hours=? ORDER BY t.app_id,t.user_id''',
            [candidate_id,landmark,window_hours,window_hours]).fetchall()
    else:
        records=connection.execute("""SELECT t.app_id,t.user_id,r.triggered_at IS NOT NULL triggered,
        t.d7_revenue_usd,
        CASE WHEN t.d7_revenue_usd IS NULL THEN NULL ELSE
            coalesce(sum(e.revenue_usd ORDER BY e.revenue_usd) FILTER (WHERE e.event_time<t.installed_at+?*INTERVAL '1 hour'),0) END before_usd,
        CASE WHEN t.d7_revenue_usd IS NULL THEN NULL ELSE
            coalesce(sum(e.revenue_usd ORDER BY e.revenue_usd) FILTER (WHERE e.event_time>=t.installed_at+?*INTERVAL '1 hour'),0) END remaining_usd
        FROM targets t LEFT JOIN triggers r ON t.app_id=r.app_id AND t.user_id=r.user_id AND r.candidate_id=?
            AND (NOT ? OR r.triggered_at<t.installed_at+?*INTERVAL '1 hour')
        LEFT JOIN events e ON t.app_id=e.app_id AND t.user_id=e.user_id AND e.event_name='ad_impression'
            AND e.event_time>=t.installed_at AND e.event_time<t.installed_at+INTERVAL '168 hours'
        WHERE t.is_mature AND t.split='holdout'
        GROUP BY t.app_id,t.user_id,t.installed_at,t.d7_revenue_usd,r.triggered_at
        ORDER BY t.app_id,t.user_id""",[window_hours,window_hours,candidate_id,landmark,window_hours]).fetchall()
    return _summarize_records(records,window_hours,landmark)


def _summarize_records(records,window_hours,landmark):
    for _,_,_,d7,before,remaining in records:
        if d7 is not None and not math.isclose(before+remaining,d7,rel_tol=1e-9,abs_tol=1e-12):
            raise ValueError('REVENUE_DECOMPOSITION_MISMATCH')
    output={'window_hours':window_hours,'intervals':{'before':[0,window_hours],
            'remaining':[window_hours,168],'d7':[0,168]},'interval_semantics':'half_open_hours_from_install',
            'ratio_denominator':'untriggered','groups':{},'comparisons':{},
            'interpretation':'descriptive_same_groups_not_a_selection_gate'}
    output['grouping']='trigger_strictly_before_landmark' if landmark else 'candidate_fixed_window_membership'
    for label,subset in [('all',records),('triggered',[r for r in records if r[2]]),
                         ('untriggered',[r for r in records if not r[2]])]:
        group={'users':len(subset),'unknown_revenue_users':sum(r[3] is None for r in subset)}
        for field,index in [('d7',3),('before',4),('remaining',5)]:
            total=math.fsum(r[index] for r in subset) if subset and not group['unknown_revenue_users'] else None
            group[field]={'revenue_usd':total,'arpu_usd':total/len(subset) if total is not None else None}
        output['groups'][label]=group
    for field in ('before','remaining','d7'):
        a=output['groups']['triggered'][field]['arpu_usd'];b=output['groups']['untriggered'][field]['arpu_usd']
        output['comparisons'][field]={'difference_usd':a-b if a is not None and b is not None else None,
                                     'ratio':a/b if a is not None and b not in (None,0) else None}
    return output
