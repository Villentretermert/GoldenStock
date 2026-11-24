"""Timing evidence must include the complete workflow, never just inference time."""
from datetime import datetime, timedelta, timezone
import json
import pytest
from evaluation.update_benchmark import assess, blank_record, main, METRICS


def completed_record(duration=600):
    # Synthetic unit-test attestations only; never persist these as real evidence.
    record = blank_record('a' * 40, 'jpm')
    start = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
    stamp = lambda seconds: (start + timedelta(seconds=seconds)).isoformat()
    record['ready_model'] = dict(reference='fixture/before', source_sha256='b' * 64,
                                 confirmed_at=stamp(-60))
    record['updated_model'] = dict(reference='fixture/after', source_sha256='c' * 64)
    for row, offset in zip(record['events'], (0, 10, 90, 300, 480, 500, duration)):
        row['at'] = stamp(offset)
    for row in record['metrics']:
        row.update(status='passed', reviewer='Test analyst', reference='fixture/' + row['id'],
                   checked_at=stamp(450))
    for row in record['exports']:
        row.update(status='passed', reviewer='Test analyst', reference='fixture/' + row['id'],
                   checked_at=stamp(550), sha256='d' * 64)
    record['signoff'].update(status='passed', reviewer='Test analyst', reference='fixture/signoff',
                             checked_at=stamp(duration + 60))
    return record


def test_complete_timing_boundary_and_stage_sum():
    from decimal import Decimal
    result = assess(completed_record())
    assert result['decision'] == 'MEETS-TARGET'
    assert result['elapsed_seconds'] == '600'
    assert sum(Decimal(v) for v in result['stage_seconds'].values()) == 600
    assert result['stage_seconds']['extracted_to_ai_completed'] == '210'
    result = assess(completed_record(600.000001))
    assert result['blockers'] == ['over_600_seconds']
    assert result['elapsed_seconds'] == '600.000001'


def test_draft_has_no_measurement_and_no_automatic_human_decisions():
    draft = blank_record('a' * 40, 'jpm')
    result = assess(draft)
    assert result['decision'] == 'NOT-READY' and result['elapsed_seconds'] is None
    assert all('metric_' + key in result['blockers'] for key in METRICS)
    assert 'analyst_signoff' in result['blockers']


@pytest.mark.parametrize('collection', ['events', 'metrics', 'exports'])
@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unknown'])
def test_exact_coverage(collection, change):
    record = completed_record()
    rows = record[collection]
    if change == 'missing': rows.pop()
    if change == 'duplicate': rows[-1] = rows[0].copy()
    if change == 'unknown': rows[0]['id'] = 'unknown'
    with pytest.raises(ValueError): assess(record)


@pytest.mark.parametrize('collection', ['metrics', 'exports'])
def test_unreviewed_or_failed_evidence_never_passes(collection):
    record = completed_record()
    for state in ('pending', 'failed'):
        record[collection][0]['status'] = state
        assert assess(record)['decision'] == 'NOT-READY'
    record[collection][0].update(status='passed', reviewer='')
    with pytest.raises(ValueError): assess(record)


@pytest.mark.parametrize('change', ['synthetic', 'initial', 'same_version', 'same_source', 'unsigned'])
def test_wrong_scope_is_not_ready(change):
    record = completed_record()
    if change == 'synthetic': record['data_kind'] = 'synthetic'
    if change == 'initial': record['operation'] = 'initial_build'
    if change == 'same_version': record['updated_model']['reference'] = record['ready_model']['reference']
    if change == 'same_source': record['updated_model']['source_sha256'] = 'b' * 64
    if change == 'unsigned': record['signoff']['status'] = 'pending'
    assert assess(record)['decision'] == 'NOT-READY'


@pytest.mark.parametrize('change', [
    'naive', 'backwards', 'late_ready', 'early_review', 'late_review', 'late_export',
    'early_signoff', 'source_hash', 'export_hash', 'bool_time', 'late_start', 'wrong_candidate'])
def test_invalid_evidence_is_rejected(change):
    record = completed_record()
    if change == 'naive': record['events'][0]['at'] = '2026-11-24T12:00:00'
    if change == 'backwards': record['events'][1]['at'] = '2026-11-24T11:59:59Z'
    if change == 'late_ready': record['ready_model']['confirmed_at'] = '2026-11-24T12:01:00Z'
    if change == 'early_review': record['metrics'][0]['checked_at'] = '2026-11-24T12:00:00Z'
    if change == 'late_review': record['metrics'][0]['checked_at'] = '2026-11-24T12:09:00Z'
    if change == 'late_export': record['exports'][0]['checked_at'] = '2026-11-24T12:11:00Z'
    if change == 'early_signoff': record['signoff']['checked_at'] = '2026-11-24T12:00:00Z'
    if change == 'source_hash': record['ready_model']['source_sha256'] = 'bad'
    if change == 'export_hash': record['exports'][0]['sha256'] = ''
    if change == 'bool_time': record['events'][0]['at'] = True
    if change == 'late_start': record['start_condition'] = 'inference_started'
    if change == 'wrong_candidate': record['candidate_commit'] = 'e' * 40
    with pytest.raises(ValueError): assess(record, 'a' * 40)


def test_timezones_normalized_and_declared_duration_ignored():
    record = completed_record(601)
    record['events'][0]['at'] = '2026-11-24T13:00:00+01:00'
    record['elapsed_seconds'] = 1
    record['paused_seconds'] = 600
    result = assess(record)
    assert result['elapsed_seconds'] == '601' and result['decision'] == 'NOT-READY'


def test_cli_draft_refuses_overwrite_and_reports_exit_codes(tmp_path, capsys):
    path = tmp_path / 'private' / 'timing.json'
    args = ['init', str(path), '--candidate', 'a' * 40]
    assert main(args) == 0
    before = path.read_bytes()
    assert main(args) == 1 and path.read_bytes() == before
    assert main(['check', str(path)]) == 2
    path.write_text(json.dumps(completed_record()), encoding='utf-8')
    assert main(['check', str(path), '--candidate', 'a' * 40]) == 0
    assert main(['check', str(path), '--candidate', 'b' * 40]) == 1
    path.write_text('{invalid', encoding='utf-8')
    assert main(['check', str(path)]) == 1


def test_nine_metrics_match_application_bank_keys():
    from goldenstock.workbook_mapping import BANK_METRICS
    assert set(METRICS) == set(BANK_METRICS)
