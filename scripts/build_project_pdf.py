"""Create a local PDF viewing copy from final, rendered presentation pages."""
import json
from pathlib import Path
import sys

from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import pypdfium2 as pdfium


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    presentation = Path(sys.argv[1]).resolve()
    output = presentation.with_suffix('.pdf')
    if output.exists():
        raise SystemExit('Choose a new final filename; existing PDF is preserved.')
    build = root / '.build-overview' / 'deck'
    index = json.loads((build / 'slide-index.json').read_text(encoding='utf-8'))
    document = canvas.Canvas(str(output), pagesize=(1200, 675), pageCompression=1)
    document.setTitle('GoldenStock — полный обзор проекта, 24 ноября 2026')
    document.setAuthor('GoldenStock')
    document.setSubject('76-slide viewing copy. Editable source: companion PPTX.')
    for entry in index:
        number = entry['slide']
        image = build / f'slide-{number:02d}.png'
        document.drawImage(ImageReader(str(image)), 0, 0, 1200, 675)
        anchor = f'slide-{number}'
        document.bookmarkPage(anchor)
        document.addOutlineEntry(f"{number}. {entry['title']}", anchor, level=0)
        document.showPage()
    document.save()
    # Validate every page with an independent PDF renderer.
    pdf = pdfium.PdfDocument(str(output))
    assert len(pdf) == len(index) == 76
    checks = []
    for number, page in enumerate(pdf, 1):
        bitmap = page.render(scale=4 / 3)
        rendered = bitmap.to_pil().convert('RGB')
        from PIL import Image, ImageChops, ImageStat
        source = Image.open(build / f'slide-{number:02d}.png').convert('RGB')
        assert rendered.size == source.size
        mean_error = max(ImageStat.Stat(ImageChops.difference(source, rendered)).mean)
        assert mean_error < 3, (number, mean_error)
        checks.append({'slide': number, 'max_channel_mean_error': mean_error})
        bitmap.close()
        page.close()
    pdf.close()
    (build / 'pdf-validation.json').write_text(json.dumps({
        'pages': len(checks), 'validation': 'all_pages_independently_rendered',
        'format': 'raster viewing copy from final PPTX render', 'checks': checks,
    }, indent=2), encoding='utf-8')
    print(f'PDF viewing copy: {len(checks)} pages; all independently rendered.')


if __name__ == '__main__':
    main()
