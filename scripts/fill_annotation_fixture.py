"""Edit only the synthetic browser workbook; never used to label customer evidence."""
import sys
from pathlib import Path
from openpyxl import load_workbook

source,target=map(Path,sys.argv[1:3])
book=load_workbook(source)
assert book['Guide']['B8'].value=='Synthetic browser annotation'
evidence=book['Sources']['B5'].value
quote=book['Sources']['F5'].value
assert quote=='Profit: -120 USD million. Footnote 1.'
values=[evidence,'profit','-120',quote,'USD','millions','','','Synthetic browser label']
for col,value in enumerate(values,3):
    cell=book['Labels'].cell(5,col,value);cell.data_type='s';cell.number_format='@'
book['Cases']['C5']='labelled'
book.save(target);book.close()
