"""Synthetic XLSX round trips, explicit review, revisions and private source boundaries."""
import io
import json
import zipfile
import pytest
from openpyxl import load_workbook
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from test_workspace import workspace
from test_ai_lab import dataset_payload,create,launch
from goldenstock.models import LabDataset,LabImport,Extraction
from goldenstock.lab_workbook import LABEL_FIELDS

BASE='/api/v1/lab/exchange'


def draft(client,payload):
    data={k:payload[k] for k in ('title','kind','split','cases')}
    data['cases']=[dict(c,expected=[]) for c in data['cases']]
    response=client.post(BASE+'/drafts',json=data)
    assert response.status_code==201,response.text
    return response.json()['id']


def workbook(client,key,labels=None,mutate=None,status='labelled'):
    content=client.get(f'{BASE}/drafts/{key}/download').content
    book=load_workbook(io.BytesIO(content))
    if labels is not None:
        for r,label in enumerate(labels,5):
            label={'evidence_id':label} if isinstance(label,str) else label
            for c,field in enumerate(LABEL_FIELDS,3):
                cell=book['Labels'].cell(r,c,label.get(field) or '')
                cell.data_type='s';cell.number_format='@'
        book['Cases']['C5']=status
    if mutate: mutate(book)
    output=io.BytesIO();book.save(output);book.close()
    return output.getvalue()


def preview(client,content,expected=201):
    response=client.post(BASE+'/imports',files={'file':('labels.xlsx',content)})
    assert response.status_code==expected,response.text
    return response.json()


def confirm(client,key,**changes):
    receipt=client.get(f'{BASE}/imports/{key}').json()
    data=dict(candidate_hash=receipt['candidate_hash'],reference_confirmed=True,reason='Checked synthetic labels against source')|changes
    return client.post(f'{BASE}/imports/{key}/confirm',json=data)


@pytest.mark.parametrize('kind',['proposals','summary'])
def test_draft_preview_confirmation_roundtrip_and_private_original(workspace,kind):
    app,connect=workspace;client=connect();payload=dataset_payload(client,app,kind=kind)
    key=draft(client,payload)
    assert draft(client,payload)==key
    assert client.get('/api/v1/lab/datasets').json()==[]
    preview(client,workbook(client,key),422)  # Unreviewed is never a negative example.
    content=workbook(client,key,payload['cases'][0]['expected'])
    imported=preview(client,content)['id']
    assert preview(client,content)['id']==imported
    assert client.get('/api/v1/lab/datasets').json()==[]
    assert confirm(client,imported,reference_confirmed=False).status_code==422
    assert confirm(client,imported,candidate_hash='0'*64).status_code==409
    saved=confirm(client,imported);assert saved.status_code==200,saved.text
    result=saved.json()
    assert result['revision']==1 and result['snapshot']['cases'][0]['expected']==payload['cases'][0]['expected']
    assert confirm(client,imported).json()['id']==result['id']
    assert client.get(f'{BASE}/imports/{imported}/original').content==content
    for other in (connect('bob'),connect('eve')):
        assert other.get(BASE+'/drafts').json()==[]
        for path in (f'/drafts/{key}',f'/drafts/{key}/download',f'/imports/{imported}',f'/imports/{imported}/original'):
            assert other.get(BASE+path).status_code==404
        preview(other,content,404)
        assert other.post(f'{BASE}/datasets/{result["id"]}').status_code==404
    client.headers.pop('x-csrf-token')
    preview(client,content,403)
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(LabDataset))==1
        assert db.scalar(select(func.count()).select_from(LabImport))==1


def test_revision_immutable_and_stale_preview_conflict(workspace):
    app,connect=workspace;client=connect();payload=dataset_payload(client,app)
    base=create(client,payload)
    key=client.post(f'{BASE}/datasets/{base["id"]}').json()['id']
    unchanged=preview(client,workbook(client,key))['id']
    assert confirm(client,unchanged).json()['id']==base['id']
    changed=payload['cases'][0]['expected'][0]|{'definition':'Profit attributable to shareholders'}
    content=workbook(client,key,[changed]);first=preview(client,content)['id']
    second=preview(client,workbook(client,key,[changed|{'definition':'Different synthetic definition'}]))['id']
    saved=confirm(client,first).json();assert saved['revision']==2 and saved['parent_id']==base['id']
    assert confirm(client,second).status_code==409
    assert client.get(f'{BASE}/imports/{second}').json()['conflict']
    assert confirm(client,first).json()['id']==saved['id']
    assert preview(client,content)['id']==first
    assert client.get('/api/v1/lab/datasets/'+base['id']).json()==base
    assert client.post(f'{BASE}/datasets/{base["id"]}').status_code==409


@pytest.mark.parametrize('field,value',[
    ('Labels!E5',2),('Labels!E5','=1+1'),('Guide!B10','holdout'),
    ('Sources!F5','Altered evidence'),('Labels!A6','C1-01'),('Labels!C5','foreign-id'),
    ('Labels!E5','3'),('Cases!C5','unreviewed'),('Cases!B5','hsbc')])
def test_invalid_workbook_is_atomic(workspace,field,value):
    app,connect=workspace;client=connect();payload=dataset_payload(client,app);key=draft(client,payload)
    sheet,cell=field.split('!')
    def mutate(book): book[sheet][cell]=value
    preview(client,workbook(client,key,payload['cases'][0]['expected'],mutate),422)
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(LabImport))==0
        assert db.scalar(select(func.count()).select_from(LabDataset))==0


def test_source_change_between_preview_and_confirmation(workspace):
    app,connect=workspace;client=connect();payload=dataset_payload(client,app);key=draft(client,payload)
    imported=preview(client,workbook(client,key,payload['cases'][0]['expected']))['id']
    with Session(app.state.engine) as db,db.begin():
        row=db.scalar(select(Extraction));data=json.loads(row.payload)
        data['items'][0]['text']+=' Additional context';row.payload=json.dumps(data)
    assert confirm(client,imported).status_code==409
    assert client.get('/api/v1/lab/datasets').json()==[]


def test_holdout_reserved_before_labels_and_consumed_after_preview(workspace):
    app,connect=workspace;client=connect();payload=dataset_payload(client,app,split='holdout')
    key=draft(client,payload)
    opposite={k:payload[k] for k in ('title','kind','split','cases')};opposite['split']='development'
    opposite['cases']=[dict(payload['cases'][0],expected=[])]
    assert client.post(BASE+'/drafts',json=opposite).status_code==409
    dataset=create(client,payload)
    key=client.post(f'{BASE}/datasets/{dataset["id"]}').json()['id']
    imported=preview(client,workbook(client,key))['id']
    launch(client,dataset)
    assert confirm(client,imported).status_code==409
    assert client.post(f'{BASE}/datasets/{dataset["id"]}').status_code==409


def test_explicit_negative_case_and_literal_precision(workspace):
    app,connect=workspace;client=connect();payload=dataset_payload(client,app)
    with Session(app.state.engine) as db,db.begin():
        row=db.scalar(select(Extraction));data=json.loads(row.payload)
        data['items'][0]['text']='Synthetic equity (123,456,789,012,345,678.50) — consolidated group'
        row.payload=json.dumps(data)
    key=draft(client,payload);evidence=client.get(f'{BASE}/drafts/{key}').json()['cases'][0]['evidence'][0]
    label=dict(evidence_id=evidence['id'],metric='equity',number_text='(123,456,789,012,345,678.50)',
        quote=evidence['text'],currency='USD',scale='units',period='2025-12-31',perimeter='group',definition='Total equity including NCI')
    imported=preview(client,workbook(client,key,[label]))['id']
    result=confirm(client,imported).json()
    assert result['snapshot']['cases'][0]['expected']==[label]
    key=client.post(f'{BASE}/datasets/{result["id"]}').json()['id']
    def clear(book):
        for row in book['Labels'].iter_rows(min_row=5,min_col=3):
            for cell in row: cell.value=None
    content=workbook(client,key,[],clear,status='no_relevant_facts')
    empty=confirm(client,preview(client,content)['id']).json()
    assert empty['revision']==2 and empty['snapshot']['cases'][0]['expected']==[]


@pytest.mark.parametrize('attack',['external','dtd','macro','huge_sheet','extra_sheet','numeric_date','validation_formula','malformed','oversize'])
def test_package_limits_and_active_content(workspace,attack):
    app,connect=workspace;client=connect();payload=dataset_payload(client,app);key=draft(client,payload)
    def mutate(book):
        if attack=='huge_sheet': book['Labels']['A501']='outside limit'
        if attack=='extra_sheet': book.create_sheet('Unexpected')
        if attack=='validation_formula': book['Cases'].data_validations.dataValidation[0].formula1='WEBSERVICE("https://example.invalid")'
        if attack=='numeric_date':
            import datetime
            book['Labels']['I5']=datetime.datetime(2025,12,31)
    content=workbook(client,key,payload['cases'][0]['expected'],mutate)
    if attack in {'external','dtd','macro'}:
        old=zipfile.ZipFile(io.BytesIO(content));out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as new:
            for name in old.namelist(): new.writestr(name,old.read(name))
            if attack=='external': new.writestr('xl/worksheets/_rels/sheet1.xml.rels','<Relationships><Relationship TargetMode="External" Target="https://example.invalid"/></Relationships>')
            if attack=='dtd': new.writestr('custom.xml','<!DOCTYPE a [<!ENTITY x "bad">]><a>&x;</a>')
            if attack=='macro': new.writestr('xl/vbaProject.bin',b'not executable')
        old.close();content=out.getvalue()
    if attack=='malformed': content=b'not a workbook'
    if attack=='oversize': content=b'x'*(1024*1024+1)
    preview(client,content,413 if attack=='oversize' else 422)
