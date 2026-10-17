import pytest
from server.analysis.connection import connect
from server.analysis.revenue_diagnostics import decompose_revenue,prepare_revenue_windows,decompose_prepared_membership


@pytest.mark.parametrize('window',[1,6,24,72,144,168])
def test_prepared_membership_microsecond_landmark_matches_sql(window):
    """The float epoch bridge must preserve both sides of the strict SQL endpoint."""
    with connect() as c:
        c.execute("""CREATE TABLE targets AS SELECT 'app' app_id,CAST(i AS VARCHAR) user_id,
            TIMESTAMPTZ '2026-01-01 00:00:00+00' installed_at,0.0 d7_revenue_usd,
            true is_mature,'holdout' split FROM range(3) x(i)""")
        c.execute("""CREATE TABLE events(app_id VARCHAR,user_id VARCHAR,event_name VARCHAR,
            event_time TIMESTAMPTZ,revenue_usd DOUBLE)""")
        c.execute("""CREATE TABLE triggers AS SELECT 'candidate' candidate_id,app_id,user_id,
            installed_at+?*INTERVAL '1 hour'+(CAST(user_id AS INTEGER)-1)*INTERVAL '1 microsecond' triggered_at
            FROM targets""",[window])
        prepared=prepare_revenue_windows(c,[window])[window]
        delays=dict(enumerate(row[0] for row in c.execute('''SELECT epoch(r.triggered_at-t.installed_at)
            FROM targets t JOIN triggers r USING(app_id,user_id) ORDER BY t.app_id,t.user_id''').fetchall()))
        actual=decompose_prepared_membership(prepared,delays,window,landmark=True)
        assert actual==decompose_revenue(c,'candidate',window,landmark=True)
        assert actual['groups']['triggered']['users']==1
        assert actual['groups']['untriggered']['users']==2


def test_d6_boundary_zero_user_and_unknown_revenue():
    with connect() as c:
        c.execute("""CREATE TABLE targets AS SELECT 'app' app_id,u user_id,TIMESTAMP '2026-01-01' installed_at,
            d7 d7_revenue_usd,true is_mature,'holdout' split FROM (VALUES ('hit',3.0),('zero',0.0),('unknown',NULL)) x(u,d7)""")
        c.execute("""CREATE TABLE triggers AS SELECT 'candidate' candidate_id,'app' app_id,'hit' user_id,
                     TIMESTAMP '2026-01-06 23:00:00' triggered_at""")
        c.execute("""CREATE TABLE events AS SELECT 'app' app_id,'hit' user_id,'ad_impression' event_name,
            TIMESTAMP '2026-01-01'+h*INTERVAL '1 hour' event_time,revenue revenue_usd
            FROM (VALUES (143,1.0),(144,2.0),(168,999.0)) x(h,revenue)""")
        result=decompose_revenue(c,'candidate',144)
        prepared=prepare_revenue_windows(c,[24,144,168])
        delays={index:143*3600 for index,row in enumerate(prepared[144]) if row[1]=='hit'}
        assert result==decompose_revenue(c,'candidate',144,prepared=True)
        for window in (24,144,168):
            for landmark in (False,True):
                assert decompose_revenue(c,'candidate',window,landmark=landmark)==decompose_revenue(
                    c,'candidate',window,landmark=landmark,prepared=True)
                assert decompose_revenue(c,'candidate',window,landmark=landmark)==decompose_prepared_membership(
                    prepared[window],delays,window,landmark=landmark)
        with pytest.raises(ValueError,match='INVALID_REVENUE_MEMBERSHIP'):
            decompose_prepared_membership(prepared[144],{len(prepared[144]):1},144)
        with pytest.raises(ValueError,match='REVENUE_WINDOW_NOT_PREPARED'):
            decompose_revenue(c,'candidate',12,prepared=True)
        hit=result['groups']['triggered']
        assert hit['before']['revenue_usd']==1 and hit['remaining']['revenue_usd']==2
        assert hit['d7']['revenue_usd']==3
        assert result['groups']['untriggered']['unknown_revenue_users']==1
        assert result['comparisons']['remaining']['difference_usd'] is None
        early=decompose_revenue(c,'candidate',24,landmark=True)
        assert early['groups']['triggered']['users']==0
        assert early['grouping']=='trigger_strictly_before_landmark'
        late=decompose_revenue(c,'candidate',144,landmark=True)
        assert late['groups']['triggered']['users']==1
        c.execute("UPDATE triggers SET triggered_at=TIMESTAMP '2026-01-07'")
        exact=decompose_revenue(c,'candidate',144,landmark=True)
        assert exact==decompose_revenue(c,'candidate',144,landmark=True,prepared=True)
        assert exact==decompose_prepared_membership(prepared[144],{index:144*3600 for index in delays},144,landmark=True)
        assert exact['groups']['triggered']['users']==0
        assert exact['groups']['untriggered']['users']==3
        c.execute("DELETE FROM targets WHERE user_id='unknown'")
        result=decompose_revenue(c,'candidate',168)
        assert result['groups']['triggered']['remaining']['revenue_usd']==0
        assert result['comparisons']['d7']['difference_usd']==3
        assert result['comparisons']['d7']['ratio'] is None
        c.execute("UPDATE targets SET d7_revenue_usd=4 WHERE user_id='hit'")
        with pytest.raises(ValueError,match='DECOMPOSITION_MISMATCH'):decompose_revenue(c,'candidate',144)
