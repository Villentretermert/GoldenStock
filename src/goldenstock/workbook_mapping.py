"""Bounded workbook inspection and explicit mapping; never execute Excel code."""
import io
import math
import re
import zipfile
from decimal import Decimal, localcontext
from lxml import etree
from openpyxl import load_workbook
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from fastapi import HTTPException
from goldenstock.storage import validate_file
from goldenstock.normalization import METRICS
from goldenstock.calculation_engine import checksum, decimal_text, parse_number, parse_formula
from goldenstock.template_contract import clean_workbook, validate_template

POLICY='gs036-v1'
BANK_METRICS={k:v for k,v in METRICS.items() if k not in {'mau','ltv'}}
FACTORS={'units':'1','thousands':'1000','millions':'1000000','billions':'1000000000','percent':'0.01','bps':'0.0001'}
TEN='(1+1+1+1+1+1+1+1+1+1)'
SCALE_EXPR={'units':'1','thousands':f'({TEN}^(1+1+1))','millions':f'({TEN}^(1+1+1+1+1+1))',
            'billions':f'({TEN}^(1+1+1+1+1+1+1+1+1))','percent':f'(1/({TEN}^(1+1)))','bps':f'(1/({TEN}^(1+1+1+1)))'}
REF=re.compile(r"(?:(?:'((?:[^']|'')+)'|([^'!]+))!)?(\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})$")


def fail(message): raise HTTPException(422,message)


class Mapping(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key: str=Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')
    sheet: str=Field(min_length=1,max_length=31)
    cell: str=Field(pattern=r'^[A-Z]{1,3}[1-9][0-9]{0,6}$')
    mode: Literal['input','formula','manual']='input'
    unit: Literal['USD','EUR','GBP','RUB','ratio','multiple','count','years']
    scale: Literal['units','thousands','millions','billions','percent','bps']='units'
    period: str=Field(pattern=r'^(FY[0-9]{4}|assumption)$')
    definition: str=Field(min_length=3,max_length=160)
    decision: str=Field(default='',max_length=500)

    @model_validator(mode='after')
    def bounds(self):
        from openpyxl.utils.cell import coordinate_to_tuple
        row,column=coordinate_to_tuple(self.cell)
        if row>1048576 or column>16384: raise ValueError('Cell is outside XLSX worksheet bounds')
        return self


def inspect_workbook(raw):
    validate_file('workbook.xlsx',raw,50*1024*1024)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos=archive.infolist()
        if len(infos)>1000 or len({i.filename for i in infos})!=len(infos) or sum(i.file_size for i in infos)>20*1024*1024:
            fail('Mapping workbook exceeds 1000 parts or 20 MB expanded')
        for item in infos:
            name=item.filename.lower()
            if any(x in name for x in ('vbaproject','externallinks','connections','querytables','macrosheets','embeddings','activex')):
                fail('VBA, external connections and embedded objects are unsupported')
            if name.endswith(('.xml','.rels')):
                try:
                    tree=etree.fromstring(archive.read(item),etree.XMLParser(resolve_entities=False,no_network=True))
                    if tree.getroottree().docinfo.doctype: fail('XML DTDs are unsupported')
                    if name.endswith('.rels') and any(n.get('TargetMode')=='External' for n in tree.iter()): fail('External links are unsupported')
                except etree.XMLSyntaxError: fail('Invalid workbook XML')
    try: book=load_workbook(io.BytesIO(raw),data_only=False,keep_links=False)
    except Exception: fail('Cannot parse XLSX workbook')
    try:
        if len(book.sheetnames)>20 or (book.calculation and book.calculation.iterate): fail('Use up to 20 sheets without iterative calculation')
        sheets={};count=0
        for sheet in book:
            # Sparse cell traversal avoids materializing a forged huge worksheet rectangle.
            cells={}
            for cell in sheet._cells.values():
                value=cell.value
                if value is None: continue
                count+=1
                if count>20000: fail('Mapping preview supports up to 20000 populated cells')
                if isinstance(value,str) and len(value)>2000: fail('Cell text exceeds 2000 characters')
                if len(cell.number_format)>2000: fail('Cell number format exceeds 2000 characters')
                if cell.data_type=='f' and not isinstance(value,str): fail('Array and data-table formulas are unsupported')
                kind='formula' if cell.data_type=='f' else ('number' if type(value) in (int,float) and math.isfinite(value) else 'text')
                cells[cell.coordinate]=dict(value=str(value),kind=kind,format=cell.number_format,row=cell.row,column=cell.column)
            sheets[sheet.title]=dict(visible=sheet.sheet_state=='visible',cells=cells)
        return dict(policy=POLICY,sheets=sheets,defined_names=list(book.defined_names))
    finally: book.close()


def source_cell(book,mapping):
    sheet=book['sheets'].get(mapping['sheet'])
    if not sheet or not sheet['visible']: return dict(value='',kind='missing',format='',row=0,column=0)
    from openpyxl.utils.cell import coordinate_to_tuple
    row,column=coordinate_to_tuple(mapping['cell'])
    return sheet['cells'].get(mapping['cell'],dict(value='',kind='blank',format='General',row=row,column=column))


def structure(book,mapping):
    cell=source_cell(book,mapping);sheet=book['sheets'].get(mapping['sheet'],{}).get('cells',{})
    labels={k:v['value'] for k,v in sheet.items() if v['kind']=='text' and
            (v['row']<=10 or v['row']==cell['row'] or (v['column']==cell['column'] and v['row']<cell['row']))}
    return dict(kind='input' if cell['kind'] in {'number','blank'} else cell['kind'],
                formula=cell['value'] if cell['kind']=='formula' else None,format=cell['format'],labels=labels)


def preview(book,entries,previous=None):
    mappings=[Mapping.model_validate(e['mapping']).model_dump() for e in entries]
    if len(mappings)>40: fail('Map up to 40 cells')
    if len({m['key'] for m in mappings})!=len(mappings) or len({(m['sheet'],m['cell']) for m in mappings})!=len(mappings): fail('Keys and source cells must be unique')
    mapped={(m['sheet'],m['cell']):(m,f'B{i+1}') for i,m in enumerate(mappings)}
    specs={m['key']:checksum(dict(mapping=m,structure=structure(book,m))) for m in mappings}
    rows=[];fields=[];errors=[];dependencies={};values={}
    for index,m in enumerate(mappings):
        cell=source_cell(book,m);key=m['key'];target=f'B{index+1}';formula=None;deps=[];error=None
        try:
            if cell['kind']=='missing': fail('Source sheet is missing or hidden; remap or remove this field')
            if m['definition'].startswith(('=','+','-','@')): fail('Use literal mapping descriptions')
            if key.endswith('_mapped'): fail('Suffix _mapped is reserved for identity outputs')
            if key in BANK_METRICS:
                money=BANK_METRICS[key][1]=='money'
                if money!=(m['unit'] in {'USD','EUR','GBP','RUB'}) or (not money and m['unit']!='ratio'): fail('Bank metric unit conflicts with its definition')
            if m['scale'] in {'percent','bps'} and m['unit']!='ratio': fail('Percent and bps require ratio units')
            if m['unit']=='ratio' and m['scale'] not in {'units','percent','bps'}: fail('Ratios use units, percent or bps')
            if m['mode']=='formula':
                if cell['kind']!='formula': fail('Formula mode requires a formula cell')
                translated=[]
                for token in Tokenizer(cell['value']).items:
                    if token.type=='OPERAND' and token.subtype=='RANGE':
                        match=REF.fullmatch(token.value)
                        if not match: fail('Ranges, named references and external references are unsupported')
                        sheet=(match[1].replace("''", "'") if match[1] else match[2]) or m['sheet']
                        ref=match[3].replace('$','');binding=mapped.get((sheet,ref))
                        if not binding: fail(f'Map dependency {sheet}!{ref} first')
                        other,address=binding;deps.append(other['key'])
                        translated.append(address if other['scale']=='units' else f'({address}/{SCALE_EXPR[other["scale"]]})')
                    else: translated.append(token.value)
                currencies={x['unit'] for x in mappings if x['key'] in deps and x['unit'] in {'USD','EUR','GBP','RUB'}}
                if len(currencies)>1 or (currencies and m['unit'] in {'USD','EUR','GBP','RUB'} and m['unit'] not in currencies):
                    fail('Cross-currency formulas need a separately reviewed conversion; v1 does not perform FX conversion')
                formula='='+''.join(translated)
                if m['scale']!='units': formula='=('+formula[1:]+')*'+SCALE_EXPR[m['scale']]
                parse_formula(formula)
            elif cell['kind']=='formula':
                if m['mode']!='manual' or len(m['decision'].strip())<3: fail('Formula as input requires an explicit manual decision and reason')
            elif m['mode']=='manual':
                if len(m['decision'].strip())<3: fail('Explain the manual input decision')
            elif cell['kind'] not in {'number','blank'}: fail('Input must be numeric or blank')
            if cell['kind']=='number' and m['mode']!='formula':
                with localcontext() as ctx:
                    ctx.prec=60
                    values[key]=decimal_text(Decimal(cell['value'])*Decimal(FACTORS[m['scale']]))
                parse_number(values[key])
        except (HTTPException,ValueError,TokenizerError) as exc:
            error=str(exc.detail if isinstance(exc,HTTPException) else exc);errors.append(f'{key}: {error}')
        dependencies[key]=deps
        fields.append(dict(key=key,role='output' if m['mode']=='formula' else 'input',cell=target,unit=m['unit'],period=m['period'],definition=m['definition'],formula=formula))
        rows.append(dict(mapping=m,source=cell,normalized=values.get(key),error=error))
    # Dependency closure propagates changes to dependent formulas, even across sheets.
    fingerprints={}
    def fingerprint(key,seen):
        if key in seen: fail('Circular mappings are unsupported')
        if key not in fingerprints: fingerprints[key]=checksum([specs[key],[(d,fingerprint(d,seen|{key})) for d in dependencies[key]]])
        return fingerprints[key]
    for row,entry in zip(rows,entries):
        key=row['mapping']['key']
        try: row['fingerprint']=fingerprint(key,set())
        except HTTPException as exc:
            row['fingerprint']=None;errors.append(str(exc.detail))
        row['confirmed']=bool(row['fingerprint'] and entry.get('confirmed')==row['fingerprint'] and not row['error'])
        prior=next((p for p in (previous or []) if p['mapping']['key']==key),None)
        row['change']='new' if not prior else ('unchanged' if prior.get('confirmed')==row['fingerprint'] else 'changed')
    # Identity outputs let an input-only financial table enter the existing calculator.
    for field in list(fields):
        if field['role']=='input':
            fields.append(dict(field,key=field['key']+'_mapped',role='output',cell=f'B{len(fields)+1}',formula='='+field['cell'],definition='Mapped value; identity only, not a valuation.'))
    contract=None
    if fields and not errors:
        try: contract=validate_template(clean_workbook(dict(fields=fields)))
        except HTTPException as exc: errors.append(str(exc.detail))
    if not fields: errors.append('Add at least one mapping')
    selected={(m['sheet'],m['cell']) for m in mappings}
    omitted=[dict(sheet=s,cell=c,formula=v['value']) for s,data in book['sheets'].items() for c,v in data['cells'].items() if v['kind']=='formula' and (s,c) not in selected]
    result=dict(policy=POLICY,rows=rows,errors=errors,contract=contract,inputs=values,omitted_formulas=omitted,
                removed=[p['mapping']['key'] for p in previous or [] if p['mapping']['key'] not in specs])
    result['sample']=None
    if contract and all(f['key'] in values for f in contract['fields'] if f['role']=='input'):
        from goldenstock.calculation_engine import calculate
        result['sample']=calculate(contract,{'base':{k:dict(value=v) for k,v in values.items()}},[])
    result['hash']=checksum(result)
    return result
