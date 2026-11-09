"""Synthetic ordinary workbook used by browser and recovery checks; no company data."""
import io
from openpyxl import Workbook


def synthetic_workbook():
    book=Workbook();sheet=book.active;sheet.title='Financial data'
    sheet.append(['Synthetic group / FY2025 / money in USD millions','Raw values'])
    for label,value in [('Profit attributable to owners',120),('Total equity including NCI',600),('Assets',2400),
        ('ROE percent',20),('ROA percent',5),('NIM percent',2.5),('Cost income percent',40),('NPL percent',1),('Cost risk percent',.8)]:
        sheet.append([label,value])
    ratios=book.create_sheet('Ratios');ratios['A1']='Simple closing-equity return, not average ROE'
    ratios['D20']="='Financial data'!B2/'Financial data'!B3"
    ratios['D21']='=SUM(D20:D20)'
    stream=io.BytesIO();book.save(stream);book.close();return stream.getvalue()
