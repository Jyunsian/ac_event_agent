from decimal import Decimal
from pathlib import Path
import pytest
from scripts.benchmark import independent_truth,capacity_preflight,REQUIRED_STAGES,full_pipeline_completed
from scripts.generate_fixture import generate


def test_benchmark_exception_diagnostic_omits_messages_and_locals(monkeypatch,capsys):
    import json
    import scripts.benchmark as benchmark
    secret='synthetic-private-exception-payload'
    failure=ValueError(secret)
    def fail(payload):
        raise failure
    monkeypatch.setattr(benchmark,'baseline_handler',fail)
    with pytest.raises(ValueError) as caught:benchmark.benchmark_handler({'private':secret})
    assert caught.value is failure
    output=capsys.readouterr()
    assert not output.out and secret not in output.err
    diagnostic=json.loads(output.err)
    assert diagnostic['benchmark_exception_type']=='ValueError'
    assert diagnostic['frames'][-1]['function']=='fail'
    assert all(set(frame)=={'file','line','function'} and '/' not in frame['file']
               for frame in diagnostic['frames'])
    monkeypatch.setattr(benchmark,'baseline_handler',lambda payload:payload)
    assert benchmark.benchmark_handler({'ok':True})=={'ok':True}


def test_independent_truth_keeps_zero_event_users(tmp_path):
    source=generate(tmp_path/'data',20,0)
    truth=independent_truth(source)
    assert truth=={'users':20,'events':0,'raw_events':0,'duplicate_events':0,'zero_event_users':20,'mature_users':20,'d7_revenue_usd':'0'}


def test_stage_timings_keep_results_errors_and_omit_payloads(monkeypatch,capsys):
    import json
    from server.checkpoints import StageRunner
    from scripts.benchmark import stage_timings
    secret='synthetic-private-stage-argument'
    result=object();failure=ValueError(secret)
    def original(self,stage,*args,**kwargs):
        assert args==(secret,)
        if stage==secret:raise failure
        return result
    monkeypatch.setattr(StageRunner,'run',original)
    runner=object.__new__(StageRunner)
    with stage_timings():
        assert runner.run('selection',secret) is result
        with pytest.raises(ValueError) as caught:runner.run(secret,secret)
        assert caught.value is failure
    assert StageRunner.run is original
    output=capsys.readouterr();assert secret not in output.out and not output.err
    rows=[json.loads(line) for line in output.out.splitlines()]
    assert [(r['benchmark_stage'],r['completed']) for r in rows]==[('selection',True),('other',False)]
    assert all(r['inclusive_cpu_seconds']>=0 and r['inclusive_wall_seconds']>=0 for r in rows)


def test_stage_timings_measure_builder_without_changing_arguments(monkeypatch,capsys):
    import json
    from server.checkpoints import StageRunner
    from scripts.benchmark import stage_timings
    target=object();value=object()
    def original(self,stage,version,builder,*,upstream):
        assert (stage,version,upstream)==('selection','1.0',{'hash':'unchanged'})
        return builder(target)
    def build(output):
        assert output is target
        return value
    monkeypatch.setattr(StageRunner,'run',original)
    with stage_timings():
        assert object.__new__(StageRunner).run('selection','1.0',build,upstream={'hash':'unchanged'}) is value
    row=json.loads(capsys.readouterr().out)
    assert row['completed']
    assert 0<=row['builder_cpu_seconds']<=row['inclusive_cpu_seconds']
    assert 0<=row['builder_wall_seconds']<=row['inclusive_wall_seconds']
    assert StageRunner.run is original


def test_stage_timings_persist_completed_records_without_overwriting(tmp_path,monkeypatch,capsys):
    import json
    from server.checkpoints import StageRunner
    from scripts.benchmark import stage_timings
    path=tmp_path/'timings.jsonl'
    def original(self,stage,*args):return 'unchanged'
    monkeypatch.setattr(StageRunner,'run',original)
    with stage_timings(path):
        assert object.__new__(StageRunner).run('selection')=='unchanged'
        # Read while context remains live: prior records survive a later kill.
        row=json.loads(path.read_text())
        assert row['benchmark_stage']=='selection' and row['completed']
    previous=path.read_bytes()
    with pytest.raises(FileExistsError):
        with stage_timings(path):pass
    assert path.read_bytes()==previous and StageRunner.run is original
    assert json.loads(capsys.readouterr().out)==row


def test_decimal_reference_uses_half_open_d7_window(tmp_path):
    (tmp_path/'users.csv').write_text('user_id,installed_at\na,2026-01-01T00:00:00Z\nb,2026-01-01T00:00:00Z\n')
    (tmp_path/'events.csv').write_text('user_id,event_time,revenue_usd\na,2026-01-01T00:00:00Z,0.1\na,2026-01-07T23:59:59Z,0.2\na,2026-01-08T00:00:00Z,99\n')
    truth=independent_truth(tmp_path)
    assert Decimal(truth['d7_revenue_usd'])==Decimal('0.3')
    assert truth['zero_event_users']==1 and truth['events']==3


def test_invalid_preflight_never_creates_directory(tmp_path):
    target=tmp_path/'not-created'
    with pytest.raises(ValueError,match='INVALID_BENCHMARK_COUNTS'):capacity_preflight(target,0,100)
    assert not target.exists()


def test_full_pipeline_requires_every_stage():
    assert full_pipeline_completed({'completed_stages':list(REQUIRED_STAGES)})
    assert not full_pipeline_completed({})
    for missing in REQUIRED_STAGES:
        assert not full_pipeline_completed({'completed_stages':list(REQUIRED_STAGES-{missing})})


def test_stress_profile_is_deterministic_and_reference_deduplicates(tmp_path):
    import csv
    first=generate(tmp_path/'first',100,1000,id_padding=64,duplicate_every=10)
    second=generate(tmp_path/'second',100,1000,id_padding=64,duplicate_every=10)
    assert (first/'events.csv').read_bytes()==(second/'events.csv').read_bytes()
    rows=list(csv.DictReader((first/'events.csv').open()))
    assert len(rows)==1000 and len(rows[0]['user_id'])>=66 and len(rows[0]['event_id'])>=66
    truth=independent_truth(first)
    assert truth['events']==900 and truth['raw_events']==1000 and truth['duplicate_events']==100
    unique={row['event_id']:row for row in rows}
    assert len(unique)==900
    assert sum(row['user_id'].startswith('u0x') for row in unique.values())>=450
    assert any(a['event_time']>b['event_time'] for a,b in zip(rows,rows[1:]))
    assert truth['zero_event_users']>=1


def test_stress_preflight_counts_width_before_allocating(tmp_path,monkeypatch):
    from server.resources import Limits
    observed=[]
    monkeypatch.setattr(Limits,'preflight',lambda self,size,path:observed.append(size) or {})
    target=tmp_path/'absent'
    capacity_preflight(target,100,1000,64,10)
    assert observed==[1000*320+100*192+1024] and not target.exists()
    with pytest.raises(ValueError,match='INVALID_STRESS_PROFILE'):capacity_preflight(target,100,1000,64,1)
    assert not target.exists()


def test_duplicate_revenue_counted_once_and_conflicts_rejected(tmp_path):
    (tmp_path/'users.csv').write_text('user_id,installed_at\na,2026-01-01T00:00:00Z\n')
    header='app_id,event_id,user_id,event_time,revenue_usd\n'
    row='synthetic,e1,a,2026-01-01T00:00:00Z,0.1\n'
    (tmp_path/'events.csv').write_text(header+row+row)
    truth=independent_truth(tmp_path)
    assert truth['events']==1 and truth['duplicate_events']==1
    assert truth['d7_revenue_usd']=='0.1'
    (tmp_path/'events.csv').write_text(header+row+row.replace('0.1\n','0.2\n'))
    with pytest.raises(ValueError,match='CONFLICTING_REFERENCE_EVENT'):independent_truth(tmp_path)


def test_disk_reference_matches_memory_and_never_overwrites(tmp_path):
    source=generate(tmp_path/'source',100,1000,id_padding=64,duplicate_every=10)
    index=tmp_path/'reference.sqlite'
    assert independent_truth(source,index)==independent_truth(source)
    assert index.stat().st_mode&0o777==0o600
    before=index.read_bytes()
    with pytest.raises(FileExistsError):independent_truth(source,index)
    assert index.read_bytes()==before


def test_disk_reference_rejects_conflicting_duplicate(tmp_path):
    (tmp_path/'users.csv').write_text('user_id,installed_at\na,2026-01-01T00:00:00Z\n')
    (tmp_path/'events.csv').write_text('app_id,event_id,user_id,event_time,revenue_usd\nx,e,a,2026-01-01T00:00:00Z,0.1\nx,e,a,2026-01-01T00:00:00Z,0.2\n')
    with pytest.raises(ValueError,match='CONFLICTING_REFERENCE_EVENT'):independent_truth(tmp_path,tmp_path/'reference.sqlite')
