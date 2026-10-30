"""Authenticated, in-memory exports from the same immutable valuation receipt."""
from datetime import datetime, timezone
import hashlib
from typing import Literal
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from goldenstock.auth import authenticate, audit
from goldenstock.models import Company
from goldenstock.valuations import owned_valuation, read_receipt, source_current, receipt
from goldenstock.calculation_engine import checksum, ENGINE, calculate
from goldenstock.valuation_engine import POLICY, value_scenarios

router = APIRouter(prefix='/api/v1/valuations')
EXPORT_VERSION = 'gs020-v1'
MIME = {'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'pdf': 'application/pdf',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}


@router.get('/{run_id}/export/{kind}')
def download(run_id: str, kind: Literal['xlsx', 'pdf', 'pptx'], request: Request):
    actor = authenticate(request)
    with Session(request.app.state.engine) as db, db.begin():
        row = owned_valuation(db, actor, run_id)
        # The company lock makes the observed review status consistent with analyst decisions.
        company = db.scalar(select(Company).where(Company.id == row.company_id).with_for_update())
        data, result = read_receipt(row)
        source = data['source']
        if data['engine'] != ENGINE or row.policy != POLICY:
            raise HTTPException(409, 'Original calculation and valuation versions required for export')
        if checksum(source['input']) != source['input_hash'] or checksum(source['result']) != source['result_hash']:
            raise HTTPException(409, 'Source calculation integrity check failed')
        if result['state'] == 'blocked' or source['result']['state'] == 'blocked':
            raise HTTPException(409, 'Resolve blocked scenarios before exporting')
        if (checksum(value_scenarios(data)) != row.result_hash or
            checksum(calculate(source['input']['template']['contract'], source['input']['scenarios'],
                               source['input']['checks'])) != source['result_hash']):
            raise HTTPException(409, 'Saved result could not be reproduced')
        current = source_current(db, actor, row.company_id, source)
        report = dict(receipt(row), input=data, result=result, company=company.name,
                      inputs_current=current, export_version=EXPORT_VERSION,
                      exported_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    # Rendering uses only captured data. No file paths, URLs or AI are evaluated.
    from goldenstock.export_workbook import workbook_bytes
    from goldenstock.export_documents import pdf_bytes, pptx_bytes
    body = {'xlsx': workbook_bytes, 'pdf': pdf_bytes, 'pptx': pptx_bytes}[kind](report)
    digest = hashlib.sha256(body).hexdigest()
    with Session(request.app.state.engine) as db, db.begin():
        audit(db, actor, 'valuation.export', run_id,
              f'format={kind};version={EXPORT_VERSION};sha256={digest};review_current={current}')
    return Response(body, media_type=MIME[kind], headers={
        'Content-Disposition': f'attachment; filename="GoldenStock-{run_id}.{kind}"',
        'X-Content-SHA256': digest, 'X-Valuation-Result-SHA256': report['result_hash'],
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
