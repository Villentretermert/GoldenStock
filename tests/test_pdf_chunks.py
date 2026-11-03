"""Long originals and interrupted prefixes must retain stable, private provenance."""
import hashlib
import json
import time
from pathlib import Path
import pytest
from sqlalchemy.orm import Session
from goldenstock import jobs, parser_process
from goldenstock.extraction import ExtractionError, PDF_PARSER_VERSION
from goldenstock.models import Job, Extraction, ExtractionCheckpoint, User, DocumentVersion
from scripts.extraction_fixtures import multipage_pdf
from tests.test_workspace import workspace, upload


@pytest.fixture(autouse=True)
def module_path(monkeypatch):
    monkeypatch.setenv('PYTHONPATH', str(Path('src').resolve()))


def queue_pdf(workspace, pages=51):
    app, connect = workspace
    client = connect()
    receipt = upload(client, content=multipage_pdf(pages), name='annual.pdf').json()
    jobs.process_one(app.state.engine, app.state.settings)
    assert client.post(f'/api/v1/jobs/{receipt["job_id"]}/extract').status_code == 200
    return app, client, receipt


def test_long_pdf_original_pages_and_bounded_ranges(tmp_path, monkeypatch):
    path = tmp_path/'annual.pdf'
    path.write_bytes(multipage_pdf(261))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    checkpoints = []
    result = parser_process.run_parser(path, '.pdf', lambda: True,
        save_checkpoint=lambda payload: checkpoints.append(payload['coverage']['last_page']))
    assert checkpoints == [*range(25, 251, 25), 261]
    assert result['coverage'] == dict(first_page=1, last_page=261, total_pages=261, status='complete')
    assert [i['location']['page'] for i in result['items']] == list(range(1, 262))
    assert all(f'Original page {n}.' in i['text'] for n, i in enumerate(result['items'], 1))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    path.write_bytes(multipage_pdf(1001))
    with pytest.raises(ExtractionError, match='extraction_limit'):
        parser_process.run_parser(path, '.pdf', lambda: True)


def test_failure_resume_privacy_and_stable_item_indices(workspace, monkeypatch):
    from goldenstock.ui import mount_ui
    app, client, receipt = queue_pdf(workspace)
    mount_ui(app)
    job_url = '/api/v1/jobs/'+receipt['job_id']
    original = parser_process.run_part
    calls = []
    def interrupted(*args):
        calls.append(args[-1][0])
        if len(calls) == 2:
            raise ExtractionError('extraction_timeout')
        return original(*args)
    monkeypatch.setattr(parser_process, 'run_part', interrupted)
    jobs.process_one(app.state.engine, app.state.settings)
    status = client.get(job_url).json()
    assert status['state'] == 'failed' and status['error_code'] == 'extraction_timeout'
    assert status['progress'] == dict(status='partial', completed_pages=25, total_pages=51)
    assert 'Incomplete extraction: 25 / 51' in client.get('/files').text
    assert client.get(job_url+'/extraction').status_code == 409
    assert client.get(f'/normalize/{receipt["job_id"]}/0').status_code == 409
    for login in ('bob', 'eve'):
        other = workspace[1](login)
        for action in ('retry', 'cancel', 'extract'):
            assert other.post(job_url+'/'+action).status_code == 404
        assert other.get(job_url).status_code == 404
        assert other.get(job_url+'/extraction').status_code == 404
    assert client.post(job_url+'/retry').status_code == 200
    jobs.process_one(app.state.engine, app.state.settings)
    result = client.get(job_url+'/extraction').json()
    assert calls == [1, 26, 26, 51]
    assert result['source_sha256'] == receipt['sha256']
    assert result['coverage']['status'] == 'complete'
    assert [i['location']['page'] for i in result['items']] == list(range(1, 52))
    assert 'Original page 26.' in result['items'][25]['text']
    assert 'Complete PDF: 51 original pages' in client.get(f'/extraction/{receipt["job_id"]}').text
    assert client.post(job_url+'/extract').status_code == 200
    assert jobs.claim(app.state.engine) is None
    with Session(app.state.engine) as db:
        assert db.get(ExtractionCheckpoint, receipt['version_id']) is None


def test_cancel_keeps_prefix_and_retry_resumes(workspace, monkeypatch):
    app, client, receipt = queue_pdf(workspace, 26)
    url = '/api/v1/jobs/'+receipt['job_id']
    save = jobs.save_pdf_checkpoint
    def cancelling(*args):
        save(*args)
        assert client.post(url+'/cancel').status_code == 200
    monkeypatch.setattr(jobs, 'save_pdf_checkpoint', cancelling)
    jobs.process_one(app.state.engine, app.state.settings)
    assert client.get(url).json()['state'] == 'cancelled'
    assert client.get(url).json()['progress']['completed_pages'] == 25
    assert client.get(url+'/extraction').status_code == 409
    monkeypatch.setattr(jobs, 'save_pdf_checkpoint', save)
    assert client.post(url+'/retry').status_code == 200
    jobs.process_one(app.state.engine, app.state.settings)
    assert client.get(url+'/extraction').json()['total'] == 26


@pytest.mark.parametrize('change', ['replace_lease', 'expire', 'revoke'])
def test_checkpoint_and_final_result_are_fenced(workspace, monkeypatch, change):
    app, client, receipt = queue_pdf(workspace, 1)
    save = jobs.save_pdf_checkpoint
    def fenced(*args):
        with Session(app.state.engine) as db, db.begin():
            job = db.get(Job, receipt['job_id'])
            if change == 'replace_lease':
                job.lease_token = 'replacement'
            elif change == 'expire':
                job.lease_until = time.time()-1
            else:
                db.get(User, job.actor_id).active = False
        save(*args)
    monkeypatch.setattr(jobs, 'save_pdf_checkpoint', fenced)
    jobs.process_one(app.state.engine, app.state.settings)
    with Session(app.state.engine) as db:
        assert db.get(ExtractionCheckpoint, receipt['version_id']) is None
        assert db.get(Extraction, receipt['version_id']) is None


def test_crash_after_last_checkpoint_and_integrity_validation(workspace, monkeypatch):
    app, client, receipt = queue_pdf(workspace, 1)
    save = jobs.save_pdf_checkpoint
    def crashed(*args):
        save(*args)
        raise RuntimeError('Synthetic worker crash')
    monkeypatch.setattr(jobs, 'save_pdf_checkpoint', crashed)
    with pytest.raises(RuntimeError):
        jobs.process_one(app.state.engine, app.state.settings)
    with Session(app.state.engine) as db, db.begin():
        db.get(Job, receipt['job_id']).lease_until = time.time()-1
        row = db.get(ExtractionCheckpoint, receipt['version_id'])
        good = row.payload
        row.payload = '{}'
    jobs.process_one(app.state.engine, app.state.settings)
    url = '/api/v1/jobs/'+receipt['job_id']
    assert client.get(url).json()['error_code'] == 'invalid_pdf_checkpoint'
    with Session(app.state.engine) as db, db.begin():
        db.get(ExtractionCheckpoint, receipt['version_id']).payload = good
    assert client.post(url+'/retry').status_code == 200
    def no_repeat(*args):
        raise AssertionError('Completed prefix was parsed again')
    monkeypatch.setattr(parser_process, 'run_part', no_repeat)
    jobs.process_one(app.state.engine, app.state.settings)
    assert client.get(url+'/extraction').json()['coverage']['status'] == 'complete'


@pytest.mark.parametrize('limit', ['MAX_ITEMS', 'MAX_PDF_BYTES'])
def test_aggregate_limits_apply_across_chunks(tmp_path, monkeypatch, limit):
    path = tmp_path/'annual.pdf'
    path.write_bytes(multipage_pdf(26))
    prefixes = []
    def checkpoint(payload):
        prefixes.append(payload)
        # The next chunk fits its own limits but must exceed the aggregate limit.
        value = len(payload['items']) if limit == 'MAX_ITEMS' else len(json.dumps(payload).encode())+1
        monkeypatch.setattr(parser_process, limit, value)
    with pytest.raises(ExtractionError, match='extraction_limit'):
        parser_process.run_parser(path, '.pdf', lambda: True, save_checkpoint=checkpoint)
    assert len(prefixes) == 1 and prefixes[0]['coverage']['last_page'] == 25


def test_malformed_chunk_is_not_a_complete_result(workspace, monkeypatch):
    app, client, receipt = queue_pdf(workspace, 1)
    original = parser_process.run_part
    def interrupted(*args):
        result = original(*args)
        result['coverage']['last_page'] = 0
        return result
    monkeypatch.setattr(parser_process, 'run_part', interrupted)
    jobs.process_one(app.state.engine, app.state.settings)
    assert client.get('/api/v1/jobs/'+receipt['job_id']).json()['error_code'] == 'invalid_pdf_checkpoint'
    with Session(app.state.engine) as db:
        assert db.get(Extraction, receipt['version_id']) is None


def test_source_change_during_parse_blocks_completion(workspace, monkeypatch):
    from goldenstock.storage import FileStore
    app, client, receipt = queue_pdf(workspace, 1)
    save = jobs.save_pdf_checkpoint
    def damaged(*args):
        save(*args)
        with Session(app.state.engine) as db:
            version = db.get(DocumentVersion, receipt['version_id'])
            FileStore(app.state.settings.data_dir).path(version.blob_key).write_bytes(b'Synthetic damage')
    monkeypatch.setattr(jobs, 'save_pdf_checkpoint', damaged)
    jobs.process_one(app.state.engine, app.state.settings)
    url = '/api/v1/jobs/'+receipt['job_id']
    assert client.get(url).json()['error_code'] == 'checksum_mismatch'
    assert client.get(url+'/extraction').status_code == 409
