"""Bounded parser execution with lease renewal and sanitized subprocess environment."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from goldenstock.extraction import (MAX_BYTES, MAX_ITEMS, MAX_PDF_BYTES, MAX_PDF_PAGES,
    PDF_CHUNK_PAGES, PDF_PARSER_VERSION, ExtractionError)


def run_part(path, extension, renew, timeout, page_args=()):
    if timeout <= 0:
        raise ExtractionError('extraction_timeout')
    if not renew():
        raise ExtractionError('lease_or_access_lost')
    env = {k: v for k, v in os.environ.items() if k in
           {'PATH','PYTHONPATH','SYSTEMROOT','WINDIR','TEMP','TMP','LANG','LD_LIBRARY_PATH'}}
    env['OMP_THREAD_LIMIT'] = '1'
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen([sys.executable, '-m', 'goldenstock.extraction', str(path), extension,
                                    *map(str, page_args)],
            stdout=output, stderr=subprocess.DEVNULL, env=env, start_new_session=os.name != 'nt')
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    process.wait(timeout=min(5, max(.01, deadline-time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise ExtractionError('extraction_timeout')
                    if not renew():
                        raise ExtractionError('lease_or_access_lost')
                    if output.tell() > MAX_BYTES:
                        raise ExtractionError('extraction_limit')
            output.seek(0)
            data = output.read(MAX_BYTES+1)
            if process.returncode or len(data)>MAX_BYTES:
                raise ExtractionError('parser_process_failed')
            try:
                result = json.loads(data)
            except (ValueError, UnicodeError):
                raise ExtractionError('parser_process_failed') from None
            if 'error' in result:
                raise ExtractionError(result['error'])
            return result
        finally:
            if process.poll() is None:
                if os.name != 'nt':
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()


def validate_pdf_payload(payload, first_page=1):
    """Check saved prefixes and subprocess boundaries before accepting any evidence."""
    try:
        coverage = payload['coverage']
        start, end, total = (coverage[k] for k in ('first_page', 'last_page', 'total_pages'))
        if (any(type(n) is not int for n in (start, end, total)) or
                start != first_page or not start <= end <= total <= MAX_PDF_PAGES or
                coverage['status'] not in {'partial', 'complete'} or
                payload['parser_version'] != PDF_PARSER_VERSION or
                payload['review_status'] != 'unreviewed' or not isinstance(payload['warnings'], list)):
            raise ValueError
        items = payload['items']
        if not isinstance(items, list) or len(items) > MAX_ITEMS or len(json.dumps(payload).encode()) > MAX_PDF_BYTES:
            raise ValueError
        previous = start
        for item in items:
            page = item['location']['page']
            if type(page) is not int or not previous <= page <= end or item['review_status'] != 'unreviewed':
                raise ValueError
            previous = page
        return end, total
    except (KeyError, TypeError, ValueError):
        raise ExtractionError('invalid_pdf_checkpoint') from None


def run_parser(path, extension, renew, timeout=None, *, checkpoint=None, save_checkpoint=None):
    if extension != '.pdf':
        return run_part(path, extension, renew, 300 if timeout is None else timeout)
    deadline = time.monotonic() + (600 if timeout is None else timeout)
    combined = checkpoint
    end, total = validate_pdf_payload(combined) if combined is not None else (0, None)
    while total is None or end < total:
        part = run_part(path, extension, renew, min(180, deadline-time.monotonic()),
                        (end + 1, PDF_CHUNK_PAGES))
        part_end, part_total = validate_pdf_payload(part, end + 1)
        if (total is not None and total != part_total) or part_end != min(part_total, end + PDF_CHUNK_PAGES):
            raise ExtractionError('invalid_pdf_checkpoint')
        if combined is None:
            combined = dict(part, items=[], warnings=[])
        # Build a new prefix: a failed checkpoint never mutates the last durable one.
        combined = dict(combined, items=combined['items'] + part['items'],
            warnings=sorted(set(combined['warnings']) | set(part['warnings'])),
            coverage=dict(first_page=1, last_page=part_end, total_pages=part_total, status='partial'))
        if len(combined['items']) > MAX_ITEMS or len(json.dumps(combined).encode()) > MAX_PDF_BYTES - 1000:
            raise ExtractionError('extraction_limit')
        if not renew():
            raise ExtractionError('lease_or_access_lost')
        if save_checkpoint:
            save_checkpoint(combined)
        end, total = part_end, part_total
    if not combined['items']:
        raise ExtractionError('no_extractable_content')
    if not renew():
        raise ExtractionError('lease_or_access_lost')
    return dict(combined, coverage=dict(combined['coverage'], status='complete'))
