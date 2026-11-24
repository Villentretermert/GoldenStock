"""The release record cannot silently turn missing or synthetic evidence into GO."""
import copy
import pytest
from evaluation.acceptance import assess, GATES, POLICY
from test_update_benchmark import completed_record


def complete_record():
    commit = 'a' * 40
    rows = [dict(id=key, status='passed', method=method, data_kind=kind,
                 reviewer='Synthetic unit-test role', reference='Synthetic unit-test receipt',
                 note='Unit test only', candidate_commit=commit)
            for key, (method, kind) in GATES.items()]
    next(row for row in rows if row['id'] == 'ai_quality')['metrics'] = dict(
        expected=100, correct=95, answered=100, emitted=100, documents=6,
        blind_holdout=True, protocol_approved=True, human_reviewed=True)
    next(row for row in rows if row['id'] == 'daily_workload')['update_benchmark'] = completed_record()
    return dict(policy=POLICY, candidate_commit=commit, as_of='2026-11-24',
                open_critical_defects=0, gates=rows)


def test_acceptance_boundary_and_critical_defects():
    record = complete_record()
    assert assess(record)['decision'] == 'GO'
    assert assess(record)['quality']['accuracy'] == .95
    record['open_critical_defects'] = 1
    assert assess(record)['blockers'] == ['critical_defects']
    for row in record['gates']:
        row['status'] = 'pending'
    assert len(assess(record)['blockers']) == len(GATES) + 1


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unknown', 'synthetic', 'revision', 'status', 'reviewer'])
def test_invalid_acceptance_evidence(change):
    record = complete_record()
    row = next(r for r in record['gates'] if r['id'] == 'remote_access')
    if change == 'missing': record['gates'].pop()
    if change == 'duplicate': record['gates'].append(copy.deepcopy(row))
    if change == 'unknown': row['id'] = 'unexpected'
    if change == 'synthetic': row['data_kind'] = 'synthetic'
    if change == 'revision': row['candidate_commit'] = 'b' * 40
    if change == 'status': row['status'] = 'waived'
    if change == 'reviewer': row['reviewer'] = ' '
    with pytest.raises(ValueError): assess(record)


@pytest.mark.parametrize('field,value', [
    ('correct',94), ('expected',99), ('documents',5), ('emitted',101),
    ('blind_holdout',False), ('protocol_approved',False), ('human_reviewed',False)])
def test_insufficient_real_quality_is_no_go(field, value):
    record = complete_record()
    m = next(row for row in record['gates'] if row['id'] == 'ai_quality')['metrics']
    m[field] = value
    if field == 'expected': m['answered'] = 99
    assert assess(record)['blockers'] == ['ai_quality']


@pytest.mark.parametrize('field,value', [('correct',True), ('emitted',float('nan')), ('expected',-1), ('answered',94)])
def test_impossible_quality_counts_rejected(field, value):
    record = complete_record()
    next(row for row in record['gates'] if row['id'] == 'ai_quality')['metrics'][field] = value
    with pytest.raises(ValueError): assess(record)


def test_daily_workload_requires_actual_update_evidence():
    record = complete_record()
    row = next(row for row in record['gates'] if row['id'] == 'daily_workload')
    row.pop('update_benchmark')
    with pytest.raises(ValueError): assess(record)
    row['update_benchmark'] = completed_record(601)
    result = assess(record)
    assert result['blockers'] == ['daily_workload']
    assert result['update_measurement']['elapsed_seconds'] == '601'
    row['update_benchmark']['candidate_commit'] = 'b' * 40
    with pytest.raises(ValueError): assess(record)


def test_legacy_policy_is_not_silently_accepted():
    record = complete_record()
    record['policy'] = 'gs024-v1'
    with pytest.raises(ValueError): assess(record)


def test_future_measurement_cannot_sign_an_older_release_record():
    record = complete_record()
    record['as_of'] = '2026-11-23'
    with pytest.raises(ValueError): assess(record)
