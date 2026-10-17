"""Versioned Candidate V2 policy; no data-dependent policy decisions."""
import math

VERSION = '2.0'
WINDOWS = (1, 3, 6, 12, 24, 48, 72, 96, 120, 144)
LANDMARKS = (24, 72, 144)
QUANTILES = tuple(i / 100 for i in range(5, 100, 5))
FAMILY_WEIGHTS = {'atom': 50, 'compound': 30, 'sequence': 20}
MAX_CANDIDATES = 2000
MAX_PRIORITY = 10
PAGE_SIZE = 50


def validate_report_header(value, *, run_id=None, dataset_id=None):
    """Read v1 unchanged or a compact v2 header; never manufacture v2 evidence."""
    if not isinstance(value, dict) or value.get('schema_version') not in ('1.0', VERSION):
        raise ValueError('INVALID_REPORT_VERSION')
    for key, expected in (('run_id', run_id), ('dataset_id', dataset_id)):
        if not isinstance(value.get(key), str) or (expected is not None and value[key] != str(expected)):
            raise ValueError('REPORT_IDENTITY_MISMATCH')
    if not isinstance(value.get('candidates'), list) or len(value['candidates']) > MAX_PRIORITY:
        raise ValueError('INVALID_PRIORITY_COUNT')
    if not isinstance(value.get('summary'), dict) or not isinstance(value.get('audit'), dict):
        raise ValueError('INVALID_REPORT_HEADER')
    ids = [row.get('candidate_id') for row in value['candidates'] if isinstance(row, dict)]
    if len(ids) != len(value['candidates']) or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('INVALID_PRIORITY_IDENTITIES')
    if value['summary'].get('candidate_count') != len(ids):
        raise ValueError('PRIORITY_COUNT_MISMATCH')
    if value['schema_version'] == VERSION:
        ref = value.get('catalog')
        if not isinstance(ref, dict) or set(ref) != {'sha256', 'evaluated_count', 'priority_ids'}:
            raise ValueError('CATALOG_REFERENCE_REQUIRED')
        count = ref['evaluated_count']
        if type(count) is not int or not len(ids) <= count <= MAX_CANDIDATES or ref['priority_ids'] != ids:
            raise ValueError('CATALOG_REFERENCE_MISMATCH')
        _digest(ref['sha256'])
    return value


def _digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('INVALID_EVIDENCE_DIGEST')


def validate_metric_summary(value):
    """Numerical contract shared by exploration and holdout evidence.

    Null is an explicit unavailable result; it must never become zero on read.
    This validates arithmetic, not statistical eligibility (owned by validation).
    """
    if not isinstance(value, dict):
        raise ValueError('INVALID_METRIC_SUMMARY')
    def finite_tree(node):
        if isinstance(node, dict):
            for item in node.values(): finite_tree(item)
        elif isinstance(node, list):
            for item in node: finite_tree(item)
        elif isinstance(node, float) and not math.isfinite(node):
            raise ValueError('NONFINITE_METRIC')
    finite_tree(value)
    groups = value.get('groups')
    if not isinstance(groups, dict) or set(groups) != {'all', 'triggered', 'untriggered'}:
        raise ValueError('INVALID_METRIC_GROUPS')
    for group in groups.values():
        if not isinstance(group, dict) or set(group) != {'users', 'unknown_revenue_users', 'revenue_usd', 'arpu_usd'}:
            raise ValueError('INVALID_METRIC_GROUP')
        n, unknown = group['users'], group['unknown_revenue_users']
        if type(n) is not int or type(unknown) is not int or not 0 <= unknown <= n:
            raise ValueError('INVALID_GROUP_COUNT')
        total, mean = group['revenue_usd'], group['arpu_usd']
        if unknown or not n:
            if total is not None or mean is not None:
                raise ValueError('UNAVAILABLE_REVENUE_NOT_NULL')
        elif any(type(x) not in (float, int) or x < 0 for x in (total, mean)):
            raise ValueError('INVALID_GROUP_REVENUE')
        elif not math.isclose(total/n, mean, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError('GROUP_ARPU_MISMATCH')
    all_group, hit, miss = (groups[k] for k in ('all', 'triggered', 'untriggered'))
    for field in ('users', 'unknown_revenue_users'):
        if all_group[field] != hit[field]+miss[field]:
            raise ValueError('GROUP_PARTITION_MISMATCH')
    coverage = value.get('coverage')
    expected = hit['users']/all_group['users'] if all_group['users'] else None
    if expected is None:
        if coverage is not None: raise ValueError('INVALID_COVERAGE')
    elif type(coverage) not in (float, int) or not math.isclose(coverage, expected, abs_tol=1e-12):
        raise ValueError('INVALID_COVERAGE')
    if value.get('evidence_status') not in ('historically_validated', 'exploratory', 'insufficient_data'):
        raise ValueError('INVALID_EVIDENCE_STATUS')
    if not isinstance(value.get('reasons'), list) or not all(isinstance(r, str) for r in value['reasons']):
        raise ValueError('INVALID_REASONS')
    delays = value.get('delay_seconds')
    if not isinstance(delays, dict) or set(delays) != {'median', 'p90'}:
        raise ValueError('INVALID_DELAY_METRICS')
    if hit['users'] == 0:
        if any(x is not None for x in delays.values()): raise ValueError('INVALID_DELAY_METRICS')
    elif any(type(x) not in (int, float) or x < 0 for x in delays.values()) or delays['median'] > delays['p90']:
        raise ValueError('INVALID_DELAY_METRICS')
    return value


def validate_candidate_detail(value):
    """Stable v2 evidence envelope, bound to one candidate and frozen family."""
    required = {'schema_version', 'run_id', 'dataset_id', 'candidate_id', 'frozen_sha256',
                'event_spec', 'exploration', 'validation', 'revenue_decomposition',
                'source_diagnostics', 'selection', 'timing_status'}
    if not isinstance(value, dict) or set(value) != required or value['schema_version'] != VERSION:
        raise ValueError('INVALID_DETAIL_ENVELOPE')
    from uuid import UUID
    UUID(value['run_id']); UUID(value['dataset_id'])
    _digest(value['candidate_id']); _digest(value['frozen_sha256'])
    for field in ('event_spec', 'exploration', 'validation', 'selection'):
        if not isinstance(value[field], dict):
            raise ValueError('INVALID_DETAIL_SECTION')
    unavailable=value['validation'].get('metrics') is None
    if value['revenue_decomposition'] is None:
        if not unavailable: raise ValueError('MISSING_REVENUE_DECOMPOSITION')
    elif not isinstance(value['revenue_decomposition'],dict):raise ValueError('INVALID_REVENUE_DECOMPOSITION')
    if not isinstance(value['source_diagnostics'], list) and not (unavailable and value['source_diagnostics'] is None):
        raise ValueError('INVALID_SOURCE_DIAGNOSTICS')
    if value['timing_status'] not in ('observed', 'assumed_event_time'):
        raise ValueError('INVALID_TIMING_STATUS')
    if value['timing_status'] == 'assumed_event_time' and value['validation'].get('evidence_status') == 'historically_validated':
        raise ValueError('ASSUMED_TIMING_NOT_VALIDATED')
    validation=value['validation']
    if validation.get('candidate_id')!=value['candidate_id'] or validation.get('evidence_status') not in ('historically_validated','exploratory','insufficient_data'):
        raise ValueError('INVALID_DETAIL_VALIDATION')
    if unavailable:
        if not validation.get('reasons') or validation['evidence_status']=='historically_validated':
            raise ValueError('UNAVAILABLE_VALIDATION_STATUS')
    else:validate_metric_summary(validation['metrics'])
    exploration=value['exploration']
    if exploration.get('candidate_id')!=value['candidate_id']:
        raise ValueError('INVALID_EXPLORATION_ID')
    for key in ('triggered_users','untriggered_users'):
        if type(exploration.get(key)) is not int or exploration[key]<0:raise ValueError('INVALID_EXPLORATION_COUNT')
    # The existing candidate contract controls executable conditions, never arbitrary SQL.
    from server.analysis.predicates import validate_candidate
    spec = value['event_spec']
    validate_candidate({'schema_version':'1.0', 'candidate_id':value['candidate_id'],
                        **{k:spec[k] for k in ('window_hours', 'predicate', 'trigger_policy', 'dependencies')}})
    return value


def validate_catalog(value):
    """Validate the complete index independently of the compact report header.

    Detailed metric schemas are validated by their producing stages. This index
    binds every evaluated identity to its immutable evidence and priority role.
    """
    if not isinstance(value, dict) or set(value) != {
        'schema_version', 'run_id', 'dataset_id', 'frozen_sha256',
        'priority_ids', 'entries', 'evaluated_count',
    }:
        raise ValueError('INVALID_CATALOG_FIELDS')
    if value['schema_version'] != VERSION:
        raise ValueError('INVALID_CATALOG_VERSION')
    from uuid import UUID
    for key in ('run_id', 'dataset_id'):
        UUID(value[key])
    digest = value['frozen_sha256']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('INVALID_FREEZE_DIGEST')
    entries, priority = value['entries'], value['priority_ids']
    if not isinstance(entries, list) or len(entries) > MAX_CANDIDATES:
        raise ValueError('INVALID_CATALOG_SIZE')
    if type(value['evaluated_count']) is not int or value['evaluated_count'] != len(entries):
        raise ValueError('CATALOG_COUNT_MISMATCH')
    ids = []
    for entry in entries:
        fields = {'candidate_id', 'window_hours', 'evidence_status', 'reasons', 'detail_sha256'}
        if not isinstance(entry, dict) or set(entry) not in (fields, fields | {'summary'}):
            raise ValueError('INVALID_CATALOG_ENTRY')
        if 'summary' in entry:
            summary = entry['summary']
            if not isinstance(summary, dict) or summary.get('family') not in ('atom', 'compound', 'sequence'):
                raise ValueError('INVALID_CATALOG_SUMMARY')
            if summary.get('role') not in (None, '價值差較大', '覆蓋較廣', '達標較快'):
                raise ValueError('INVALID_CATALOG_ROLE')
            if not isinstance(summary.get('ad_formats'), list) or not all(isinstance(x, str) for x in summary['ad_formats']):
                raise ValueError('INVALID_CATALOG_FORMATS')
            for field in ('triggered_users', 'untriggered_users', 'triggered_arpu_usd', 'untriggered_arpu_usd',
                          'all_arpu_usd', 'difference_usd', 'coverage', 'median_seconds', 'p90_seconds'):
                number = summary.get(field)
                if number is not None and (type(number) not in (int, float) or not math.isfinite(number)):
                    raise ValueError('INVALID_CATALOG_NUMBER')
                if number is not None and field != 'difference_usd' and number < 0:
                    raise ValueError('NEGATIVE_CATALOG_NUMBER')
                if field in ('triggered_users', 'untriggered_users') and number is not None and type(number) is not int:
                    raise ValueError('INVALID_CATALOG_COUNT')
                if field == 'coverage' and number is not None and number > 1:
                    raise ValueError('INVALID_CATALOG_COVERAGE')
        for key in ('candidate_id', 'detail_sha256'):
            digest = entry[key]
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('INVALID_ENTRY_DIGEST')
        window = entry['window_hours']
        if type(window) not in (int, float) or not math.isfinite(window) or not 0 < window <= 168:
            raise ValueError('INVALID_WINDOW')
        if entry['evidence_status'] not in ('historically_validated', 'exploratory', 'insufficient_data'):
            raise ValueError('INVALID_EVIDENCE_STATUS')
        if not isinstance(entry['reasons'], list) or not all(isinstance(x, str) for x in entry['reasons']):
            raise ValueError('INVALID_REASONS')
        ids.append(entry['candidate_id'])
    if len(set(ids)) != len(ids):
        raise ValueError('DUPLICATE_CANDIDATE')
    if not isinstance(priority, list) or not all(isinstance(x, str) for x in priority):
        raise ValueError('INVALID_PRIORITY')
    if len(priority) > MAX_PRIORITY or len(set(priority)) != len(priority) or not set(priority) <= set(ids):
        raise ValueError('INVALID_PRIORITY')
    if any(e['window_hours'] == 168 and e['candidate_id'] in priority for e in entries):
        raise ValueError('BOUNDARY_NOT_PRIORITY')
    return value
