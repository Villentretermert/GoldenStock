"""Offline pilot release checklist. Exit 2 means NO-GO, 1 means invalid evidence."""
import argparse
from datetime import date
import json
from pathlib import Path
import re

# Human attestations remain necessary. This tool never grants network or app access.
GATES = {
    'regression': ('automated', 'synthetic'),
    'five_company_journey': ('automated', 'synthetic'),
    'recovery_rehearsal': ('automated', 'synthetic'),
    'source_coverage': ('analyst', 'real'),
    'real_company_journey': ('analyst', 'real'),
    'ai_quality': ('analyst', 'real'),
    'remote_access': ('operator', 'real'),
    'external_backup': ('operator', 'real'),
    'windows_restart': ('operator', 'real'),
    'daily_workload': ('operator', 'real'),
    'fund_signoff': ('owner', 'real'),
}
POLICY = 'gs024-v1'


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def assess(record):
    """Fail closed on omissions, duplicates, invalid counts and synthetic signoffs."""
    if not isinstance(record, dict) or record.get('policy') != POLICY:
        raise ValueError('Unknown acceptance policy')
    if not re.fullmatch('[0-9a-f]{40}', record.get('candidate_commit', '')):
        raise ValueError('A full candidate commit is required')
    date.fromisoformat(record['as_of'])
    rows = record.get('gates')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Expected a list of gate records')
    ids = [row.get('id') for row in rows]
    if any(not isinstance(key, str) for key in ids) or len(set(ids)) != len(ids) or set(ids) != set(GATES):
        raise ValueError('Every known gate must occur exactly once')
    blockers = []
    quality = None
    for row in rows:
        key = row['id']
        if row.get('status') not in ('passed', 'pending', 'failed') or not nonempty(row.get('note')):
            raise ValueError('Invalid status or missing note: ' + key)
        if row['status'] != 'passed':
            blockers.append(key)
            continue
        method, dataset = GATES[key]
        if (row.get('method'), row.get('data_kind')) != (method, dataset):
            raise ValueError('Wrong evidence type: ' + key)
        if any(not nonempty(row.get(field)) for field in ('reference', 'reviewer')):
            raise ValueError('Missing evidence reference or reviewer: ' + key)
        if row.get('candidate_commit') != record['candidate_commit']:
            raise ValueError('Evidence belongs to another candidate: ' + key)
        if key == 'ai_quality':
            m = row.get('metrics', {})
            if not isinstance(m, dict):
                raise ValueError('Quality metrics must be an object')
            names = ('expected', 'correct', 'answered', 'emitted', 'documents')
            if any(type(m.get(name)) is not int or m[name] < 0 for name in names):
                raise ValueError('Quality counts must be nonnegative integers')
            n, good, answered, emitted, documents = (m[name] for name in names)
            if not 0 <= good <= answered <= n or good > emitted or answered > emitted:
                raise ValueError('Inconsistent quality counts')
            # Provisional minimums must be ratified by the fund before signoff.
            quality = dict(accuracy=good / n if n else None,
                           precision=good / emitted if emitted else None,
                           coverage=answered / n if n else None,
                           expected=n, correct=good, documents=documents)
            if (n < 100 or documents < 6 or m.get('blind_holdout') is not True
                    or m.get('protocol_approved') is not True
                    or m.get('human_reviewed') is not True
                    or good * 100 < n * 95 or good * 100 < emitted * 95
                    or answered * 100 < n * 95):
                blockers.append(key)
    defects = record.get('open_critical_defects')
    if type(defects) is not int or defects < 0:
        raise ValueError('Critical defect count must be a nonnegative integer')
    if defects:
        blockers.append('critical_defects')
    return dict(policy=POLICY, candidate_commit=record['candidate_commit'], as_of=record['as_of'],
                decision='NO-GO' if blockers else 'GO', blockers=blockers, quality=quality,
                scope='Offline evidence review; operator and fund retain release authority')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    parser.add_argument('--validate-only', action='store_true',
                        help='Validate the record schema only; never a release authorization')
    args = parser.parse_args()
    try:
        result = assess(json.loads(args.record.read_text(encoding='utf-8')))
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({'decision': 'INVALID', 'error': str(error)}, ensure_ascii=False))
        return 1
    result['validation_only'] = args.validate_only
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.validate_only or result['decision'] == 'GO' else 2


if __name__ == '__main__':
    raise SystemExit(main())
