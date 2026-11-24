"""Record an isolated synthetic local tour. Credentials never enter artifacts or logs."""
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import io

from check_browser import DOCKER, SEED, REVOKE
from extraction_fixtures import simple_pdf
from workbook_fixture import synthetic_workbook


def compact_demo_sections():
    """Short tutorial input; deliberately not a speed or quality benchmark."""
    from reportlab.pdfgen import canvas
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(750, 1000))
    pages = [['DEMONSTRATION ONLY', 'Contents', 'Consolidated statements of income .... 2'],
             ['Consolidated statements of income', 'USD million; year ended 2025; consolidated IFRS'],
             ['Profit attributable to owners 120'], ['Consolidated balance sheets', 'Assets 900']]
    for lines in pages:
        pdf.setFont('Helvetica', 18)
        for index, line in enumerate(lines):
            pdf.drawString(35, 930-index*35, line)
        pdf.showPage()
    pdf.save()
    return output.getvalue()


def main():
    root = Path.cwd()
    build = root / '.build-overview'
    build.mkdir(exist_ok=True)
    runtime = Path(os.environ['GS_RUNTIME_ROOT'])
    binary = next((build / 'media-runtime/imageio_ffmpeg/binaries').glob('ffmpeg-*.exe'))
    login = 'demo_' + secrets.token_hex(5)
    password = secrets.token_urlsafe(32)
    identity = json.dumps(dict(login=login, password=password))
    subprocess.run(DOCKER + [SEED], input=identity, text=True, check=True)
    lines = [
        'DEMONSTRATION ONLY - fictional financial data',
        'Consolidated group, IFRS, year ended 2025. USD millions.',
        'Profit attributable to owners 100', 'Total equity including NCI 1,000',
        'Total assets 10,000', 'ROE 10%', 'ROA 1%', 'NIM 3.5%',
        'Cost income ratio 45%', 'NPL ratio 1.8%', 'Cost of risk 0.9%',
    ]
    stream = b'BT /F1 15 Tf 45 780 Td '
    for i, line in enumerate(lines):
        if i: stream += b'0 -31 Td '
        stream += b'(' + line.encode('ascii') + b') Tj '
    stream += b'ET'
    env = dict(os.environ, GS_QA_LOGIN=login, GS_QA_PASSWORD=password,
               GS_NODE_MODULES=str(runtime / 'node/node_modules'),
               GS_FFMPEG=str(binary), GS_APP_URL='http://127.0.0.1:8081',
               GS_DEMO_PDF=base64.b64encode(simple_pdf(stream)).decode(),
               GS_DEMO_SECTION=base64.b64encode(compact_demo_sections()).decode(),
               GS_QA_MAP_WORKBOOK=base64.b64encode(synthetic_workbook()).decode())
    try:
        subprocess.run([str(runtime / 'node/bin/node.exe'), 'scripts/record_project_demo.cjs'],
                       env=env, check=True)
    finally:
        subprocess.run(DOCKER + [REVOKE], input=json.dumps(dict(login=login)), text=True, check=True)
        print('Synthetic demonstration account revoked. Credentials were not saved.')


if __name__ == '__main__':
    main()
