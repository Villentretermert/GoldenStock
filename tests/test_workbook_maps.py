"""Ordinary Excel layouts: explicit conversion, isolation, revisions and replay."""
import io
import json
import zipfile
import pytest
from fastapi import HTTPException
from openpyxl import Workbook,load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_workspace import workspace
from goldenstock.models import WorkbookMapping
from goldenstock.workbook_mapping import inspect_workbook,preview,Mapping,BANK_METRICS
from goldenstock.template_contract import validate_template


def workbook(change=None):
    book=Workbook();sheet=book.active;sheet.title='Financial data'
    sheet.append(['USD millions / FY2025','Reported'])
    sheet.append(['Profit attributable to owners',120])
    sheet.append(['Total equity including NCI',600])
    sheet.append(['Assets',2400]);sheet.append(['NIM',2.5])
    derived=book.create_sheet('Ratios')
    derived['A1']='Simple profit / closing equity, not average ROE'
    derived['D20']="='Financial data'!$B$2/'Financial data'!B3"
    derived['D21']='=SUM(D20:D20)'
    if change: change(book)
    stream=io.BytesIO();book.save(stream);book.close();return stream.getvalue()


def mapping(key='profit',cell='B2',**kw):
    return dict(key=key,sheet='Financial data',cell=cell,unit='USD',scale='millions',period='FY2025',
                mode='input',definition='Profit attributable to owners, consolidated group',decision='')|kw


def entries(*maps): return [dict(mapping=m,confirmed=None) for m in maps]


def upload(client,raw=None,parent='',key='workbook-map-01'):
    response=client.post('/api/v1/workbook-maps',headers={'Idempotency-Key':key},data={'title':'Synthetic workbook','parent_id':parent},
        files={'file':('model.xlsx',raw or workbook(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code==201,response.text
    return response.json()


def edit(client,ident,m):
    data=client.get('/api/v1/workbook-maps/'+ident).json()
    return client.put('/api/v1/workbook-maps/'+ident+'/mapping',json={'revision':data['revision'],'mapping':m})


def finalize(client,ident):
    base='/api/v1/workbook-maps/'+ident;data=client.get(base).json();result=data['preview']
    assert not result['errors'],result['errors']
    keys=[r['mapping']['key'] for r in result['rows'] if not r['confirmed']]
    if keys:
        response=client.post(base+'/confirm',json=dict(revision=data['revision'],preview_hash=result['hash'],keys=keys,confirmed=True))
        assert response.status_code==200,response.text
    data=client.get(base).json()
    response=client.post(base+'/finalize',json=dict(revision=data['revision'],preview_hash=data['preview']['hash'],acknowledge_omitted=True))
    assert response.status_code==201,response.text
    return response.json()


def test_conversion_cross_sheet_formulas_and_canonical_recalculation():
    maps=entries(mapping(),mapping('equity','B3',definition='Total equity including NCI'),
        mapping('nim','B5',unit='ratio',scale='percent',definition='Reported NIM'),
        mapping('closing_return','D20',sheet='Ratios',mode='formula',unit='ratio',scale='units',definition='Simple closing-equity return'))
    result=preview(inspect_workbook(workbook()),maps)
    assert not result['errors'],result['errors']
    assert result['inputs']==dict(profit='120000000',equity='600000000',nim='0.025')
    assert result['sample']['scenarios']['base']['values']['closing_return']['value']=='0.2'
    assert result['omitted_formulas'][0]['cell']=='D21'
    assert len(BANK_METRICS)==9


@pytest.mark.parametrize('change,error',[
    ({'unit':'ratio'},'conflicts'),({'scale':'percent'},'require ratio'),
    ({'mode':'formula'},'formula cell'),({'cell':'A2'},'numeric'),
    ({'sheet':'Missing'},'missing'),({'definition':'=secret'},'literal'),
])
def test_mapping_context_errors(change,error):
    result=preview(inspect_workbook(workbook()),entries(mapping(**change)))
    assert error in ' '.join(result['errors'])


def test_unsupported_formula_needs_explicit_decision():
    book=inspect_workbook(workbook())
    m=mapping('custom_result','D21',sheet='Ratios',mode='formula',scale='units')
    assert preview(book,entries(m))['errors']
    m['mode']='input';assert preview(book,entries(m))['errors']
    m['mode']='manual';assert preview(book,entries(m))['errors']
    m['decision']='Analyst will enter independently checked result'
    result=preview(book,entries(m));assert not result['errors'];assert result['inputs']=={};assert result['sample'] is None


def test_cross_currency_formula_requires_explicit_resolution():
    maps=entries(mapping(),mapping('equity','B3',unit='EUR'),mapping('return_ratio','D20',sheet='Ratios',mode='formula',unit='ratio',scale='units'))
    assert 'Cross-currency' in ' '.join(preview(inspect_workbook(workbook()),maps)['errors'])


def test_array_formulas_and_out_of_grid_addresses_are_rejected():
    from openpyxl.worksheet.formula import ArrayFormula
    with pytest.raises(HTTPException): inspect_workbook(workbook(lambda b:setattr(b['Ratios']['D20'],'value',ArrayFormula(ref='D20:D21',text='=1'))))
    with pytest.raises(ValueError): Mapping.model_validate(mapping(cell='XFE1'))
    with pytest.raises(ValueError): Mapping.model_validate(mapping(cell='B1048577'))


def test_cycles_unmapped_dependencies_and_duplicate_cells():
    m=mapping('ratio','D20',sheet='Ratios',mode='formula',unit='ratio',scale='units')
    assert 'Map dependency' in ' '.join(preview(inspect_workbook(workbook()),entries(m))['errors'])
    raw=workbook(lambda b:setattr(b['Ratios']['D20'],'value','=D20'))
    assert 'Circular' in ' '.join(preview(inspect_workbook(raw),entries(m))['errors'])
    with pytest.raises(HTTPException): preview(inspect_workbook(workbook()),entries(mapping(),mapping('duplicate')))


@pytest.mark.parametrize('kind',['vba','external','dtd','oversized'])
def test_unsafe_workbook_package(kind):
    raw=workbook()
    if kind=='external': raw=workbook(lambda b:setattr(b['Financial data']['A2'],'hyperlink','https://example.com'))
    else:
        stream=io.BytesIO(raw)
        with zipfile.ZipFile(stream,'a') as archive:
            if kind=='vba': archive.writestr('xl/vbaProject.bin',b'not executable')
            elif kind=='dtd': archive.writestr('xl/test.xml',b'<!DOCTYPE test [<!ENTITY x "test">]><test/>')
            else: archive.writestr('xl/padding.bin',b'x'*(21*1024*1024))
        raw=stream.getvalue()
    with pytest.raises(HTTPException): inspect_workbook(raw)


def test_versions_changed_only_approval_and_numeric_input_review(workspace):
    _,connect=workspace;client=connect();one=upload(client)['id']
    for m in (mapping(),mapping('equity','B3'),mapping('return_ratio','D20',sheet='Ratios',mode='formula',unit='ratio',scale='units')):
        assert edit(client,one,m).status_code==200
    v1=finalize(client,one)
    assert edit(client,one,mapping()).status_code==409
    raw=workbook(lambda b:setattr(b['Financial data']['B2'],'value',130))
    two=upload(client,raw,one,'workbook-map-02')['id'];data=client.get('/api/v1/workbook-maps/'+two).json()
    assert all(r['confirmed'] and r['change']=='unchanged' for r in data['preview']['rows'])
    assert data['preview']['inputs']['profit']=='130000000'
    v2=finalize(client,two);assert v2['number']==2 and v2['template_id']==v1['template_id']
    raw=workbook(lambda b:setattr(b['Ratios']['D20'],'value',"='Financial data'!B2/('Financial data'!B3+1)"))
    three=upload(client,raw,two,'workbook-map-03')['id'];rows=client.get('/api/v1/workbook-maps/'+three).json()['preview']['rows']
    assert [r['mapping']['key'] for r in rows if not r['confirmed']]==['return_ratio']
    assert rows[2]['change']=='changed'
    assert client.get('/api/v1/workbook-maps/'+one).json()['preview']['inputs']['profit']=='120000000'


def test_dependency_context_changes_revoke_downstream_and_hidden_sheet_can_be_repaired():
    maps=entries(mapping(),mapping('equity','B3'),mapping('return_ratio','D20',sheet='Ratios',mode='formula',unit='ratio',scale='units'))
    first=preview(inspect_workbook(workbook()),maps)
    for m,row in zip(maps,first['rows']): m['confirmed']=row['fingerprint']
    changed=workbook(lambda b:setattr(b['Financial data']['B2'],'number_format','0.00'))
    rows=preview(inspect_workbook(changed),maps,maps)['rows']
    assert [r['mapping']['key'] for r in rows if not r['confirmed']]==['profit','return_ratio']
    hidden=workbook(lambda b:setattr(b['Ratios'],'sheet_state','hidden'))
    assert 'hidden' in ' '.join(preview(inspect_workbook(hidden),maps,maps)['errors'])


def test_api_privacy_sharing_and_clean_copy(workspace):
    app,connect=workspace;a,b,e=connect(),connect('bob'),connect('eve');ident=upload(a)['id'];base='/api/v1/workbook-maps/'+ident
    assert edit(a,ident,mapping()).status_code==200
    for client in (b,e):
        assert client.get(base).status_code==404 and client.get(base+'/original').status_code==404
        assert client.get('/api/v1/workbook-maps').json()==[]
        assert client.put(base+'/mapping',json=dict(revision=1,mapping=mapping())).status_code==404
    version=finalize(a,ident);tid=version['template_id'];vid=version['id']
    assert a.patch('/api/v1/templates/'+tid+'/visibility',json=dict(shared=True,revision=1)).status_code==200
    clean=b.get(f'/api/v1/templates/{tid}/versions/{vid}/structure');assert clean.status_code==200
    book=load_workbook(io.BytesIO(clean.content));assert set(book.sheetnames)=={'Model','GS_Map'} and book['Model']['B1'].value is None
    assert validate_template(clean.content)==version['contract']
    assert b.get(base).status_code==404 and b.get(f'/api/v1/templates/{tid}/versions/{vid}/original').status_code==404
    assert b.post('/api/v1/templates/'+tid+'/copy').status_code==201
    a.headers['x-csrf-token']='wrong';assert a.request('DELETE',base+'/mapping',json=dict(revision=3,key='profit')).status_code==403


def test_stale_preview_confirmation_and_idempotence(workspace):
    _,connect=workspace;client=connect();ident=upload(client)['id'];base='/api/v1/workbook-maps/'+ident
    assert upload(client)['id']==ident
    assert edit(client,ident,mapping()).status_code==200
    data=client.get(base).json()
    assert edit(client,ident,mapping(definition='Changed definition')).status_code==200
    response=client.post(base+'/confirm',json=dict(revision=data['revision'],preview_hash=data['preview']['hash'],keys=['profit'],confirmed=True))
    assert response.status_code==409
    data=client.get(base).json()
    assert client.post(base+'/finalize',json=dict(revision=data['revision'],preview_hash=data['preview']['hash'],acknowledge_omitted=True)).status_code==422
    v=finalize(client,ident)
    assert finalize(client,ident)['id']==v['id']


def test_saved_calculation_provenance_replay_and_mismatched_map(workspace):
    _,connect=workspace;client=connect();ident=upload(client)['id'];assert edit(client,ident,mapping()).status_code==200
    version=finalize(client,ident)
    payload=dict(title='Mapped original',company_id='jpm',template_id=version['template_id'],version_id=version['id'],workbook_map_id=ident,
        scenarios={'base':{'profit':dict(value='120000000',note='Explicit analyst assumption from private workbook',confirmed=True)}},checks=[])
    response=client.post('/api/v1/calculations',headers={'Idempotency-Key':'mapped-calculation-01'},json=payload)
    assert response.status_code==201,response.text
    run=response.json()['id'];data=client.get('/api/v1/calculations/'+run).json()
    assert data['input']['workbook_source']['original_inputs']['profit']=='120000000'
    assert data['input']['scenarios']['base']['profit']['source']=='manual_assumption'
    assert client.post('/api/v1/calculations/'+run+'/replay').json()['matched']
    other=upload(client,key='workbook-map-99')['id'];payload['workbook_map_id']=other
    assert client.post('/api/v1/calculations',headers={'Idempotency-Key':'mapped-calculation-02'},json=payload).status_code==422


def test_original_integrity_and_new_draft_preserves_shared_access_until_finalization(workspace):
    app,connect=workspace;a,b=connect(),connect('bob');ident=upload(a)['id'];assert edit(a,ident,mapping()).status_code==200
    version=finalize(a,ident);tid=version['template_id'];a.patch('/api/v1/templates/'+tid+'/visibility',json=dict(shared=True,revision=1))
    next_id=upload(a,parent=ident,key='workbook-map-new')['id']
    assert b.get('/api/v1/templates/'+tid).status_code==200
    finalize(a,next_id);assert b.get('/api/v1/templates/'+tid).status_code==404
    from goldenstock.storage import FileStore
    with Session(app.state.engine) as db:
        row=db.get(WorkbookMapping,ident);FileStore(app.state.settings.data_dir).path(row.blob_key).write_bytes(b'corrupted')
    assert a.get('/api/v1/workbook-maps/'+ident).status_code==409
