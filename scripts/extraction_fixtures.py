"""Small synthetic documents for repeatable extraction checks."""
import io


def multipage_pdf(pages):
    from reportlab.pdfgen import canvas
    output = io.BytesIO()
    document = canvas.Canvas(output)
    for number in range(1, pages + 1):
        document.drawString(50, 750, f'Original page {number}. Profit: -120 USD million.')
        document.showPage()
    document.save()
    return output.getvalue()

def workbook_bytes():
    from openpyxl import Workbook
    book=Workbook(); sheet=book.active; sheet.title='Income'
    sheet.append(['Metric','FY2025','Note'])
    sheet.append(['Profit',-120,None])
    sheet.append(['Footnote 1: USD millions',None,None])
    sheet.merge_cells('A3:C3')
    sheet['B4']='=B2*2'
    out=io.BytesIO(); book.save(out); book.close()
    return out.getvalue()

def simple_pdf(stream=b'BT /F1 16 Tf 50 750 Td (Profit: -120 USD million. Footnote 1.) Tj ET'):
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    data=b'%PDF-1.4\n'; offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data)); data+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(data); data+=b'xref\n0 6\n0000000000 65535 f \n'
    data+=b''.join(f'{n:010d} 00000 n \n'.encode() for n in offsets)
    return data+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode()


def sparse_workbook_bytes():
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = 'Income'
    sheet['A1'] = 'Financial highlights'
    sheet.merge_cells('A1:C1')
    sheet['B2'] = 0
    sheet['B2'].number_format = '#,##0.00'
    sheet['B3'] = '=B2+5'
    sheet['Z1000'] = -7
    other = book.create_sheet('Appendix')
    other.sheet_state = 'hidden'
    other['Z1000'] = 'Closing note'
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()
def long_ai_pdf():
    """One synthetic native page that needs multiple bounded AI windows."""
    import io
    from reportlab.pdfgen import canvas
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(750, 1900))
    pdf.setFont('Helvetica', 10)
    pdf.drawString(30, 1860, 'For the year ended December 31, 2025, consolidated IFRS profit was USD 120 million.')
    for line in range(115):
        pdf.drawString(30, 1835-line*15, 'Synthetic narrative for interface testing. This line contains no additional financial metrics.')
    pdf.save()
    return output.getvalue()
