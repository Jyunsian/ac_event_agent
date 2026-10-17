import copy

from server.analysis.priority import choose_priority


def row(identity, difference, coverage, speed, **extra):
    return dict(candidate_id=identity, difference_usd=difference, coverage=coverage,
                p90_seconds=speed, triggered_users=100, untriggered_users=100,
                window_hours=144, complexity=0, **extra)


def test_pareto_roles_overlap_and_deterministic_ties():
    rows=[row('value',10,.2,100),row('coverage',2,.9,200),row('speed',3,.3,1),
          row('dominated',1,.1,300),row('clone',9,.2,101)]
    sets={r['candidate_id']:set(range(i*100,(i+1)*100)) for i,r in enumerate(rows)}
    sets['clone']=sets['value']
    result=choose_priority(rows,sets)
    assert result['priority_ids']==['value','coverage','speed','dominated']
    assert result['selection']['value']['role']=='價值差較大'
    assert result['selection']['coverage']['role']=='覆蓋較廣'
    assert result['selection']['speed']['role']=='達標較快'
    assert result['selection']['clone']['similar_priority_id']=='value'
    assert result['selection']['clone']['jaccard']==1
    assert 'SIMILAR_ALTERNATIVE' in result['selection']['clone']['reasons']
    assert result==choose_priority(list(reversed(rows)),sets)


def test_ineligible_retained_and_boundary_not_prioritized():
    rows=[row('valid',1,.5,10),row('late',1,.5,10),row('small',1,.5,10),row('negative',-1,.5,10)]
    rows[1]['window_hours']=168;rows[2]['triggered_users']=99
    result=choose_priority(rows,{'valid':{1}})
    assert result['priority_ids']==['valid']
    assert len(result['selection'])==4
    assert not result['selection']['late']['eligible']
    assert not result['selection']['small']['eligible']
    assert not result['selection']['negative']['eligible']


def test_exact_ninety_percent_is_similar_and_complexity_breaks_ties():
    rows=[row('z_atom',2,.5,10),row('a_compound',2,.5,10)]
    rows[1]['complexity']=1
    result=choose_priority(rows,{'z_atom':set(range(10)), 'a_compound':set(range(9))})
    assert result['priority_ids']==['z_atom']
    assert result['selection']['a_compound']['jaccard']==.9
    changed=copy.deepcopy(rows);changed[1]['difference_usd']=None
    assert choose_priority(changed,{'z_atom':{1}})['priority_ids']==['z_atom']


def test_exact_bitmaps_match_reference_sets_including_high_bits_and_empty():
    rows=[row('value',10,.2,100),row('coverage',2,.9,200),row('speed',3,.3,1),
          row('clone',9,.2,101),row('empty',1,.1,300)]
    sets={'value':set(range(100000,100010)), 'coverage':set(range(10)),
          'speed':{3,9,100008},'clone':set(range(100000,100009)),'empty':set()}
    bitmaps={key:sum(1<<index for index in members) for key,members in sets.items()}
    assert choose_priority(rows,sets)==choose_priority(rows,bitmaps)
