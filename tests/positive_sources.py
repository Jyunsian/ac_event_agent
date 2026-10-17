"""Deterministic IAA signal for integration paths requiring a real priority item."""
from tests.test_ingest import write_source
from tests.test_quality import EXPORT

POSITIVE_EXPORT={**EXPORT,'complete_through':'2026-01-20T00:00:00Z',
                 'exported_at':'2026-01-21T00:00:00Z'}

def positive_sources(directory,extras=None,*,adaptive=False):
    users=[];events=[]
    for day in range(1,5):
        for index in range(100):
            identity=f'positive-{day}-{index}';hour=1 if index<50 else 4
            users.append(dict(app_id='synthetic',user_id=identity,platform='android',country='US',
                installed_at=f'2026-01-{day:02}T00:00:00Z',acquisition_source='A' if index%2 else 'B'))
            events.append(dict(app_id='synthetic',user_id=identity,event_id=identity,event_name='ad_impression',
                event_time=f'2026-01-{day:02}T0{hour}:00:00Z',available_at=f'2026-01-{day:02}T0{hour}:00:00Z',
                ad_format=('rewarded' if index%50<25 else 'interstitial') if adaptive else 'rewarded',
                revenue_usd=((4,3,2,0)[index//25] if adaptive else (2 if index<50 else .1))+(index%7)*.001))
    return [write_source(directory,'users',users),write_source(directory,'events',events+(extras or []))]


def adaptive_sources(directory,extras=None):
    # Two distinct 50%-coverage signals at 24h: revenue>=3 and rewarded count>=1.
    # Their intersection is 25%; both have positive D7 differences. At 3h only
    # the early half is a sufficiently sized group. No validation gates change.
    return positive_sources(directory,extras,adaptive=True)
