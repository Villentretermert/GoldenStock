"""Bounded, text-only annotation exchange. Workbook cells never execute code."""
import io
import json
import zipfile
import textwrap
from lxml import etree
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill,Alignment,Protection
from openpyxl.worksheet.datavalidation import DataValidation
from fastapi import HTTPException
from goldenstock.storage import validate_file
from goldenstock.lab_scoring import validate_reference
from goldenstock.normalization import METRICS

FORMAT='gs032-xlsx-v1'
MAX_BYTES=1024*1024
LABEL_FIELDS=['evidence_id','metric','number_text','quote','currency','scale','period','perimeter','definition']
HEADERS=dict(Labels=['slot','case',*LABEL_FIELDS],Cases=['case','company','review_status'],
    Sources=['case','evidence_id','part','source_sha256','locator','text'],Guide=['field','value'])
INSTRUCTIONS={
    'Labels':'Edit blue cells. Keep reported numbers as text. Use source IDs and verbatim quotes. Empty slots are unused.',
    'Cases':'Set each case to labelled or no_relevant_facts after checking its sources. Unreviewed cases cannot be imported.',
    'Sources':'Read-only original evidence. Text continues in numbered parts. Source hashes and locators must remain unchanged.',
    'Guide':'Return this workbook to its private workspace. Preview changes and explicitly confirm before saving a reference.',
}


def invalid(message): raise HTTPException(422,message)


def rows_for(exchange,payload):
    rows={name:[] for name in HEADERS}
    metadata=dict(format=FORMAT,exchange_id=exchange.id,manifest_sha256=exchange.fingerprint,
        title=payload['title'],kind=payload['kind'],split=payload['split'],
        parent_id=payload['parent_id'] or '',parent_sha256=payload['parent_hash'] or '',
        parent_revision=str(payload['parent_revision'] or ''),
        instructions='Use only the provided slots. Summary labels need only evidence_id; leave other label fields blank.',
        metric_codes=', '.join(METRICS),
        context='Copy only stated currency, scale, period, reporting perimeter and definition. Leave unsupported context empty.')
    rows['Guide']=[[k,v] for k,v in metadata.items()]
    for i,case in enumerate(payload['cases'],1):
        cid=f'C{i}';labels=case.get('expected',[])
        state=('labelled' if labels else 'no_relevant_facts') if payload['parent_id'] else 'unreviewed'
        rows['Cases'].append([cid,case['company_id'],state])
        for n in range(12):
            label=labels[n] if n<len(labels) else {}
            if isinstance(label,str): label=dict(evidence_id=label)
            rows['Labels'].append([f'{cid}-{n+1:02d}',cid,*[label.get(k) or '' for k in LABEL_FIELDS]])
        for evidence in case['evidence']:
            value=evidence['text']
            for part,start in enumerate(range(0,max(1,len(value)),650),1):
                rows['Sources'].append([cid,evidence['id'],str(part),evidence['source_sha256'],
                    json.dumps(evidence['location'],ensure_ascii=False,sort_keys=True),value[start:start+650]])
    return rows


def export_workbook(exchange,payload):
    book=Workbook();book.remove(book.active)
    widths=dict(Labels=[13,10,39,19,24,65,12,16,30,38,50],Cases=[12,20,28],Sources=[10,38,8,25,36,95],Guide=[25,115])
    for name,rows in rows_for(exchange,payload).items():
        sheet=book.create_sheet(name);headers=HEADERS[name]
        sheet.sheet_view.showGridLines=False;sheet.freeze_panes='C5' if name=='Labels' else 'A5'
        sheet.merge_cells(start_row=1,start_column=1,end_row=1,end_column=len(headers))
        sheet.merge_cells(start_row=2,start_column=1,end_row=2,end_column=len(headers))
        sheet.cell(1,1,f'{payload["title"]} / {name}');sheet.cell(2,1,INSTRUCTIONS[name])
        sheet.row_dimensions[1].height=30;sheet.row_dimensions[2].height=40
        for column,width in enumerate(widths[name],1): sheet.column_dimensions[sheet.cell(4,column).column_letter].width=width
        for col,header in enumerate(headers,1):
            cell=sheet.cell(4,col,header);cell.font=Font(name='Calibri',size=11,color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='193B30')
        for r,values in enumerate(rows,5):
            for c,value in enumerate(values,1):
                cell=sheet.cell(r,c,value);cell.data_type='s';cell.number_format='@'
                editable=(name=='Labels' and c>=3) or (name=='Cases' and c==3)
                cell.font=Font(name='Calibri',size=11,color='185CAB' if editable else '193B30')
                cell.fill=PatternFill('solid',fgColor='EEF5FF' if editable else 'F4F5F0')
                cell.alignment=Alignment(vertical='top',wrap_text=True)
                cell.protection=Protection(locked=not editable)
            lines=max(
                sum(max(1,len(textwrap.wrap(line,max(8,int(width)-3)))) for line in str(value).split('\n'))
                for value,width in zip(values,widths[name]))
            sheet.row_dimensions[r].height=min(409,max(44 if name=='Labels' else 34,lines*15+8))
        for r in (1,2):
            sheet.cell(r,1).data_type='s';sheet.cell(r,1).font=Font(name='Calibri',size=16 if r==1 else 11,bold=r==1,color='193B30')
            sheet.cell(r,1).alignment=Alignment(vertical='center',wrap_text=True)
        sheet.protection.sheet=True  # Editing aid only; server comparison is authoritative.
    validation=DataValidation(type='list',formula1='"unreviewed,labelled,no_relevant_facts"',allow_blank=False)
    validation.errorTitle='Choose a review status';validation.error='Select one of the three listed values.';validation.showErrorMessage=True
    book['Cases'].add_data_validation(validation);validation.add(f'C5:C{4+len(payload["cases"])}')
    stream=io.BytesIO();book.save(stream);book.close();return stream.getvalue()


def parse_book(content):
    """Bound ZIP/XML before openpyxl; reject formulas, links, objects and typed numbers."""
    if not content or len(content)>MAX_BYTES: raise HTTPException(413,'Annotation workbook limit is 1 MiB')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos=archive.infolist()
            if len(infos)>100 or len({i.filename for i in infos})!=len(infos) or sum(i.file_size for i in infos)>8*1024*1024:
                invalid('Annotation package exceeds limits')
            for info in infos:
                name=info.filename.lower()
                if any(part in name for part in ('vbaproject','externallinks','connections','querytables','macrosheets','embeddings','activex')):
                    invalid('Macros, external data and embedded objects are not allowed')
                if name.endswith(('.xml','.rels')):
                    root=etree.fromstring(archive.read(info),etree.XMLParser(resolve_entities=False,no_network=True))
                    if root.getroottree().docinfo.doctype: invalid('XML DTDs are not allowed')
                    nodes=list(root.iter())
                    if len(nodes)>40000: invalid('Annotation XML exceeds limits')
                    if any(etree.QName(n).localname=='f' for n in nodes): invalid('Formulas are not allowed; enter literal text')
                    for node in nodes:
                        tag=etree.QName(node).localname
                        if tag in {'formula','formula1','formula2'} and not (tag=='formula1' and node.text=='"unreviewed,labelled,no_relevant_facts"'):
                            invalid('Only the built-in review status list is supported')
                    if any(n.get('TargetMode')=='External' for n in nodes): invalid('External links are not allowed')
        validate_file('annotation.xlsx',content,MAX_BYTES)
        book=load_workbook(io.BytesIO(content),read_only=False,data_only=False,keep_links=False)
    except HTTPException: raise
    except Exception: invalid('Cannot read the annotation XLSX')
    try:
        if set(book.sheetnames)!=set(HEADERS) or any(s.sheet_state!='visible' for s in book): invalid('Keep the four visible exchange sheets')
        if book.defined_names: invalid('Custom defined names are not supported in annotation workbooks')
        result={}
        for sheet in book:
            if sheet.max_row>500 or sheet.max_column>16: invalid('Annotation sheet exceeds row or column limits')
            for row in sheet:
                for cell in row:
                    if cell.value is not None and (cell.data_type=='f' or not isinstance(cell.value,str)):
                        invalid(f'{sheet.title}!{cell.coordinate}: use literal text, including numbers and periods')
            header=HEADERS[sheet.title]
            if [sheet.cell(4,c).value for c in range(1,len(header)+1)]!=header: invalid(f'{sheet.title}: header changed')
            if any(sheet.cell(r,c).value is not None for r in range(1,sheet.max_row+1) for c in range(len(header)+1,sheet.max_column+1)):
                invalid('Unexpected annotation columns')
            values=[[sheet.cell(r,c).value or '' for c in range(1,len(header)+1)] for r in range(5,sheet.max_row+1)]
            while values and not any(values[-1]): values.pop()
            result[sheet.title]=values
        return result
    finally: book.close()


def labels_from_book(parsed,exchange,payload):
    original=rows_for(exchange,payload)
    if parsed['Guide']!=original['Guide'] or parsed['Sources']!=original['Sources']:
        invalid('Workbook metadata or source evidence changed; export again')
    wanted={r[0]:r[1] for r in original['Labels']};seen=set();labels={f'C{i}':[] for i in range(1,len(payload['cases'])+1)}
    for row in parsed['Labels']:
        slot,cid,*values=row
        if slot not in wanted or slot in seen or wanted[slot]!=cid: invalid('Unknown, duplicate or moved annotation slot')
        seen.add(slot)
        if not any(values): continue
        if payload['kind']=='summary':
            if not values[0] or any(values[1:]): invalid(f'{slot}: summary labels use evidence_id only')
            labels[cid].append(values[0])
        else: labels[cid].append({k:v or None for k,v in zip(LABEL_FIELDS,values)})
    if seen!=set(wanted): invalid('Missing annotation slots; clear editable cells instead of deleting rows')
    if len(parsed['Cases'])!=len(original['Cases']): invalid('Missing or extra review cases')
    results=[]
    for i,(current,expected,case) in enumerate(zip(parsed['Cases'],original['Cases'],payload['cases'])):
        if current[:2]!=expected[:2]: invalid('Case identity changed')
        status=current[2];values=labels[current[0]]
        if status not in {'labelled','no_relevant_facts'}: invalid(f'{current[0]}: finish review or explicitly mark no_relevant_facts')
        if (status=='labelled')!=bool(values): invalid(f'{current[0]}: review status does not match its labels')
        try: values=validate_reference(payload['kind'],values,case['evidence'])
        except (ValueError,TypeError,KeyError,ArithmeticError): invalid(f'{current[0]}: invalid or duplicate labels; check source ID, quote, number and context')
        results.append(dict(case,expected=values))
    return results
