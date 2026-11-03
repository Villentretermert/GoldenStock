"""Five-company HTTP journey on synthetic documents, without an AI-quality claim."""
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

from goldenstock.jobs import process_one
from scripts.extraction_fixtures import simple_pdf
from test_workspace import workspace
from test_normalization import context
from test_reviews import decide
from test_templates import post as upload_template
from test_calculations import payload, run
from test_valuations import api_payload, create
from test_exports import downloaded, pdf_text, pptx_text


@pytest.mark.parametrize('company', ['sber', 'tinkoff', 'jpm', 'hsbc', 'nu'])
def test_document_to_review_calculation_and_exports(workspace, monkeypatch, company):
    app, connect = workspace
    analyst, colleague, outsider = connect(), connect('bob'), connect('eve')
    monkeypatch.setenv('PYTHONPATH', str(Path('src').resolve()))
    assert analyst.put('/api/v1/favorites/' + company).status_code == 200
    content = simple_pdf(b'BT /F1 16 Tf 50 750 Td '
                         b'(Synthetic profit attributable to owners: 100 USD. FY2025.) Tj ET')
    upload = analyst.post('/api/v1/documents', headers={'Idempotency-Key': 'uat-document-' + company},
                          data={'company_id': company}, files={'file': ('synthetic.pdf', content)})
    assert upload.status_code == 201, upload.text
    receipt = upload.json()
    process_one(app.state.engine, app.state.settings)  # Real integrity job and parser subprocess.
    job_url = '/api/v1/jobs/' + receipt['job_id']
    assert analyst.post(job_url + '/extract').status_code == 200
    process_one(app.state.engine, app.state.settings)
    extraction = analyst.get(job_url + '/extraction')
    assert extraction.status_code == 200, analyst.get(job_url).text
    assert extraction.json()['source_sha256'] == receipt['sha256']
    item_index = next(i for i, item in enumerate(extraction.json()['items'])
                      if '100 USD' in (item['text'] or ''))
    mapped = analyst.post('/api/v1/facts', json=context(
        job_id=receipt['job_id'], item_index=item_index, number_text='100', scale='units',
        definition='Profit attributable to owners'))
    assert mapped.status_code == 201, mapped.text
    fid = mapped.json()['id']

    def snapshot():
        state = analyst.get('/api/v1/review-state', params={'company_id': company}).json()
        return analyst.post('/api/v1/input-snapshots', json=dict(
            company_id=company, title='Synthetic UAT inputs', expected_state_hash=state['state_hash']))

    assert snapshot().status_code == 409  # No unreviewed inputs enter the calculation.
    assert decide(analyst, fid).status_code == 201
    saved = snapshot()
    assert saved.status_code == 201, saved.text
    template = upload_template(analyst).json()
    calculation = payload(template)
    calculation.update(company_id=company, snapshot_id=saved.json()['id'])
    calculation['scenarios']['base']['profit_owners'] = dict(
        fact_id=fid, note='Synthetic parent profit, period and USD units checked', confirmed=True)
    result = run(analyst, calculation)
    assert result.status_code == 201, result.text
    cid = result.json()['id']
    assert analyst.post('/api/v1/calculations/' + cid + '/replay').json()['matched']
    valuation = api_payload(cid)
    valuation['scenarios']['base']['profit_owners'] = dict(
        source_key='profit_owners', note='Parent profit linked to reviewed source', confirmed=True)
    valued = create(analyst, valuation)
    assert valued.status_code == 201, valued.text
    rid = valued.json()['id']
    detail = analyst.get('/api/v1/valuations/' + rid).json()
    assert detail['company_id'] == company
    assert detail['result']['scenarios']['base']['values']['per_share']['value'] == '90'
    assert analyst.post('/api/v1/valuations/' + rid + '/replay').json()['matched']
    for kind in ('xlsx', 'pdf', 'pptx'):
        raw = downloaded(analyst, rid, kind)
        if kind == 'xlsx':
            book = openpyxl.load_workbook(BytesIO(raw), data_only=True)
            assert book['Summary']['B8'].value == 90
            book.close()
        else:
            text = (pdf_text if kind == 'pdf' else pptx_text)(raw)
            assert '90.00' in text and detail['result_hash'] in text.replace('\n', '')
        for denied in (colleague, outsider):
            assert denied.get(f'/api/v1/valuations/{rid}/export/{kind}').status_code == 404
    assert analyst.get('/api/v1/companies/' + company).json()['latest_valuation']['id'] == rid
    for denied in (colleague, outsider):
        assert denied.get(job_url + '/extraction').status_code == 404
        assert denied.get('/api/v1/input-snapshots/' + saved.json()['id']).status_code == 404
    assert decide(analyst, fid, 'unreviewed', 1).status_code == 201
    assert run(analyst, calculation, 'uat-stale-' + company).status_code == 409
    assert 'HISTORICAL' in pdf_text(downloaded(analyst, rid, 'pdf'))
