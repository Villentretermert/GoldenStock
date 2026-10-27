"""Bounded parser execution with lease renewal and sanitized subprocess environment."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from goldenstock.extraction import MAX_BYTES, ExtractionError


def run_parser(path, extension, renew, timeout=300):
    env = {k: v for k, v in os.environ.items() if k in
           {'PATH','PYTHONPATH','SYSTEMROOT','WINDIR','TEMP','TMP','LANG','LD_LIBRARY_PATH'}}
    env['OMP_THREAD_LIMIT'] = '1'
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen([sys.executable, '-m', 'goldenstock.extraction', str(path), extension],
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
