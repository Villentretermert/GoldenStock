"""The release record cannot silently turn missing or synthetic evidence into GO."""
import copy
import pytest
from evaluation.acceptance import assess, GATES, POLICY


def complete_record():
    commit = 'a' * 40
    rows = [dict(id=key, status='passed', method=method, data_kind=kind,
                 reviewer='Synthetic unit-test role', reference='Synthetic unit-test receipt',
                 note='Unit test only', candidate_commit=commit)
            for key, (method, kind) in GATES.items()]
    next(row for row in rows if row['id'] == 'ai_quality')['metrics'] = dict(
        expected=100, correct=95, answered=100, emitted=100, documents=6,
        blind_holdout=True, protocol_approved=True, human_reviewed=True)
    return dict(policy=POLICY, candidate_commit=commit, as_of='2026-11-03',
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
