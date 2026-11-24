"""Validate an analyst's private model-update timing record; never approve facts."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re

POLICY = 'gs024-update-v1'
METRICS = ('profit', 'equity', 'assets', 'roe', 'roa', 'nim', 'cost_income', 'npl', 'cost_risk')
FORMATS = ('xlsx', 'pdf', 'pptx')
EVENTS = ('started', 'uploaded', 'extracted', 'ai_completed', 'reviewed',
          'calculated', 'exports_checked')


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def digest(value, length):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value) is not None


def instant(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp must be an ISO-8601 string with timezone')
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Timezone is required for every timestamp')
    return result.astimezone(timezone.utc)


def seconds(delta):
    # Avoid float rounding near the 600-second boundary.
    return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1000000


def exact_rows(value, names, label):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError('Expected rows: ' + label)
    ids = [row.get('id') for row in value]
    if any(not isinstance(key, str) for key in ids) or len(ids) != len(names) or set(ids) != set(names):
        raise ValueError('Every required ID must occur exactly once: ' + label)
    return {row['id']: row for row in value}


def blank_record(candidate, company):
    """A draft has no timestamps, facts, reviewer or successful decisions."""
    return dict(policy=POLICY, candidate_commit=candidate, company=company, data_kind='real',
                operation='update', start_condition='local_file_selected',
                ready_model={'reference': '', 'source_sha256': '', 'confirmed_at': None},
                updated_model={'reference': '', 'source_sha256': ''},
                events=[dict(id=key, at=None) for key in EVENTS],
                metrics=[dict(id=key, status='pending', reviewer='', reference='', checked_at=None)
                         for key in METRICS],
                exports=[dict(id=key, status='pending', reviewer='', reference='', checked_at=None,
                              sha256='') for key in FORMATS],
                signoff={'status': 'pending', 'reviewer': '', 'reference': '', 'checked_at': None})


def assess(record, candidate=None):
    """Inspect supplied evidence. A valid draft is NOT-READY, not a measurement."""
    if not isinstance(record, dict) or record.get('policy') != POLICY:
        raise ValueError('Unknown update benchmark policy')
    commit = record.get('candidate_commit')
    if not digest(commit, 40) or (candidate is not None and commit != candidate):
        raise ValueError('Update benchmark belongs to an invalid or different candidate')
    if record.get('company') not in ('jpm', 'hsbc', 'nu'):
        raise ValueError('Expected a pilot company: jpm, hsbc or nu')
    if record.get('data_kind') not in ('real', 'synthetic'):
        raise ValueError('Unknown data kind')
    if record.get('operation') not in ('update', 'initial_build'):
        raise ValueError('Unknown operation')
    if record.get('start_condition') != 'local_file_selected':
        raise ValueError('This policy measures from selection of a locally available source file')
    blockers = []
    if record['data_kind'] != 'real':
        blockers.append('real_data_required')
    if record['operation'] != 'update':
        blockers.append('ready_model_update_required')
    models = []
    for name in ('ready_model', 'updated_model'):
        model = record.get(name)
        if not isinstance(model, dict):
            raise ValueError('Expected model evidence: ' + name)
        if not nonempty(model.get('reference')):
            blockers.append(name + '_reference')
        sha = model.get('source_sha256')
        if sha not in ('', None) and not digest(sha, 64):
            raise ValueError('Invalid source SHA-256: ' + name)
        if not sha:
            blockers.append(name + '_source')
        models.append(model)
    before, after = models
    if (nonempty(before.get('reference')) and before['reference'] == after.get('reference')):
        blockers.append('distinct_model_versions_required')
    if before.get('source_sha256') and before['source_sha256'] == after.get('source_sha256'):
        blockers.append('new_source_required')

    rows = exact_rows(record.get('events'), EVENTS, 'events')
    times = {}
    previous = None
    for name in EVENTS:
        raw = rows[name].get('at')
        if raw is None:
            blockers.append('event_' + name)
            continue
        at = instant(raw)
        if previous is not None and at < previous:
            raise ValueError('Events must be chronological, including queue and review time')
        times[name] = previous = at
    ready_at = before.get('confirmed_at')
    if ready_at is None:
        blockers.append('ready_model_confirmation')
    else:
        ready_at = instant(ready_at)
        if 'started' in times and ready_at > times['started']:
            raise ValueError('The baseline model must be ready before timing starts')

    def check_decision(row, label, start, end):
        if not isinstance(row, dict) or row.get('status') not in ('pending', 'failed', 'passed'):
            raise ValueError('Invalid human decision: ' + label)
        if row['status'] != 'passed':
            blockers.append(label)
            return
        if any(not nonempty(row.get(key)) for key in ('reviewer', 'reference')):
            raise ValueError('Missing human evidence: ' + label)
        checked = instant(row.get('checked_at'))
        if start in times and checked < times[start]:
            raise ValueError('Decision precedes its measured stage: ' + label)
        if end in times and checked > times[end]:
            raise ValueError('Decision falls outside its measured stage: ' + label)

    metrics = exact_rows(record.get('metrics'), METRICS, 'metrics')
    for name, row in metrics.items():
        check_decision(row, 'metric_' + name, 'ai_completed', 'reviewed')
    exports = exact_rows(record.get('exports'), FORMATS, 'exports')
    for name, row in exports.items():
        check_decision(row, 'export_' + name, 'calculated', 'exports_checked')
        if row['status'] == 'passed' and not digest(row.get('sha256'), 64):
            raise ValueError('A checked export requires its SHA-256: ' + name)
    # Signoff is allowed after the measured workflow, but not before its end.
    check_decision(record.get('signoff'), 'analyst_signoff', 'exports_checked', None)

    elapsed = None
    intervals = {}
    if len(times) == len(EVENTS):
        elapsed = seconds(times['exports_checked'] - times['started'])
        if elapsed <= 0:
            raise ValueError('A completed measurement must have positive duration')
        for left, right in zip(EVENTS, EVENTS[1:]):
            intervals[left + '_to_' + right] = str(seconds(times[right] - times[left]))
        if elapsed > 600:
            blockers.append('over_600_seconds')
    return dict(policy=POLICY, candidate_commit=commit, company=record['company'],
                decision='NOT-READY' if blockers else 'MEETS-TARGET', blockers=blockers,
                elapsed_seconds=str(elapsed) if elapsed is not None else None,
                stage_seconds=intervals, target_seconds=600,
                scope='One supplied timing record; not verified identity, AI quality or daily workload')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('init', help='Create a blank private record without overwriting')
    create.add_argument('path', type=Path)
    create.add_argument('--candidate', required=True)
    create.add_argument('--company', choices=('jpm', 'hsbc', 'nu'), default='jpm')
    check = commands.add_parser('check', help='Validate and report recorded elapsed time')
    check.add_argument('path', type=Path)
    check.add_argument('--candidate')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            record = blank_record(args.candidate, args.company)
            assess(record)
            args.path.parent.mkdir(parents=True, exist_ok=True)
            with args.path.open('x', encoding='utf-8') as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            result = {'decision': 'DRAFT', 'path': str(args.path)}
        else:
            result = assess(json.loads(args.path.read_text(encoding='utf-8')), args.candidate)
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({'decision': 'INVALID', 'error': str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['decision'] in ('DRAFT', 'MEETS-TARGET') else 2


if __name__ == '__main__':
    raise SystemExit(main())
