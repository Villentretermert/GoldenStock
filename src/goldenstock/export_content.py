"""Common facts and wording for the three local report formats."""
import json
import re
from decimal import Decimal, localcontext
from goldenstock.valuation_engine import METHODS


def clean(value):
    # Strip control characters, preserving text as text in XML/PDF rather than active markup.
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', str(value))


def number(value, percent=False):
    if value is None: return 'Unavailable'
    with localcontext() as ctx:
        ctx.prec = 160
        d = Decimal(value) * (100 if percent else 1)
        text = f'{d:,.2f}' if abs(d) < Decimal('1e15') else f'{d:.8E}'
    return text + ('%' if percent else '')


def review_label(report):
    if report['inputs_current'] is False: return 'HISTORICAL: source review changed; create a new valuation'
    if report['inputs_current'] is True: return 'Source review current at export; assumptions confirmed by author'
    return 'Manual inputs: no verified source snapshot; assumptions confirmed by author'


def evidence(report):
    """Each bound input retains its full source context, including review and document locators."""
    data = report['input']; source = data['source']['input']; result = []
    for name, inputs in source['scenarios'].items():
        for key, item in inputs.items():
            lines = [f'{name} / {key}: {item["value"]} ({item["source"]})',
                     'Reason: ' + item['note'], 'Confirmed by: ' + item['actor_id']]
            if item.get('fact'):
                # All source metadata is retained; omit neither scale nor rounding nor review history.
                lines += [f'{k}: {json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v}'
                          for k, v in item['fact'].items()]
            result.append(('Calculation input', lines))
    for name, inputs in data['scenarios'].items():
        fields = {f['key']: f for f in data['contract']['fields']}
        for key, item in inputs.items():
            f = fields[key]
            lines = [f'{name} / {key}: {item["value"]} {f["unit"]} / {f["period"]}', f['definition'],
                     'Source: ' + item['source'], 'Reason: ' + item['note'], 'Confirmed by: ' + item['actor_id']]
            if item.get('source_key'): lines.append('Calculation field: ' + item['source_key'] + ' / ' + item['source_definition'])
            result.append(('Valuation input', lines))
    return result


def sections(report):
    data = report['input']; source = data['source']; currency = data['currency']
    yield ('Assessment and limitations', [review_label(report), *data['warnings'],
        'This report reproduces an analyst-confirmed model, not independent investment approval.',
        'User economics is separate from common equity value. No automatic currency or ADR conversion.',
        'PDF/PPTX are saved results. XLSX is an editable copy; edits do not update this receipt.'])
    yield ('Method and perimeter', [METHODS[data['method']], 'Valuation date: ' + data['valuation_date'],
        'Currency: ' + currency + ' (whole units)', 'Reference year: ' + str(data['reference_year']),
        'Method: ' + data['method_note'], 'Perimeter: ' + data['scope_note'], 'Shares: ' + data['shares_note']])
    if data['quote']:
        q = data['quote']
        yield ('Market comparison', [f'{q["instrument"]}: {q["price"]} {q["currency"]} on {q["date"]}', q['source']])
    if data['operating']:
        yield ('Monthly user economics', ['Operating month: ' + data['operating_month'], data['operating_note'],
            'Constant retention; first contribution at month-one end; acquisition costs excluded.'])
    for name, scenario in report['result']['scenarios'].items():
        yield (name.title() + ': calculated fields', [f'{f["key"]}: {scenario["values"][f["key"]]["display"]} {f["unit"]}. {f["definition"]}'
            for f in data['contract']['fields'] if f['role'] == 'output'])
    controls = []
    for name, scenario in source['result']['scenarios'].items():
        controls.append(name + ': ' + scenario['state'])
        for c in scenario['checks']:
            controls.append(f'{c["key"]}: expected {c["expected"]}; tolerance {c["tolerance"]}; residual {c["residual"]}; passed {c["passed"]}. {c["note"]}')
    yield ('Source calculation checks', controls)
    for category in ('Calculation input', 'Valuation input'):
        combined = []
        for title, lines in evidence(report):
            if title == category: combined += lines + ['']
        yield (category + 's: source appendix', combined)
    yield ('Version and provenance', [
        'Valuation ID: ' + report['id'], 'Company: ' + report['company_id'],
        'Exported at: ' + report['exported_at'], 'Export format: ' + report['export_version'],
        'Valuation policy: ' + report['policy'], 'Calculation engine: ' + data['engine'],
        'Valuation input SHA-256: ' + report['input_hash'], 'Valuation result SHA-256: ' + report['result_hash'],
        'Calculation ID: ' + source['id'], 'Calculation input SHA-256: ' + source['input_hash'],
        'Calculation result SHA-256: ' + source['result_hash'],
        'Template version: ' + source['input']['template']['version_id'],
        'Template SHA-256: ' + source['input']['template']['clean_sha256'],
        'Review snapshot: ' + json.dumps(source['input']['snapshot'], sort_keys=True)])


def summary_table(report):
    rows = [['Scenario', 'Per share', 'Common equity', 'Upside']]
    for name, s in report['result']['scenarios'].items():
        rows.append([name.title(), number(s['values']['per_share']['value']),
                     number(s['values']['equity_value']['value']), number(s.get('upside'), True)])
    return rows


def sensitivity_tables(report):
    for name, s in report['result']['scenarios'].items():
        dcf = report['method'] in ('ddm', 'fcfe')
        rows = [['Cost of equity', 'Terminal growth', 'Per share']] if dcf else [['Multiple', 'Per share']]
        for point in s['sensitivity']:
            inputs = point['inputs']
            row = ([number(inputs['cost_equity'], True), number(inputs['terminal_growth'], True)] if dcf else [number(inputs['multiple'])])
            rows.append(row + [number(point['per_share']['value']) if point['per_share'] else 'Blocked'])
        yield (name.title() + ': sensitivity (' + report['input']['currency'] + ')', rows)
