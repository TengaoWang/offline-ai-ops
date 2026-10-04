"""Generate portable page previews from the bundled manual."""
from pathlib import Path
import re

import pymupdf

from engine import SCENES

ROOT = Path(__file__).resolve().parent
MANUAL = ROOT / 'assets' / '华为S系列园区交换机维护宝典.pdf'
OUTPUT = ROOT / 'assets' / 'manual-pages'


def cited_pages():
    pages = set()
    for scene in SCENES.values():
        for source in scene['sources']:
            numbers = [int(value) for value in re.findall(r'\d+', source['pdf_pages'])]
            pages.update(range(numbers[0], numbers[-1] + 1))
    return sorted(pages)


def main():
    if not MANUAL.is_file():
        raise SystemExit(f'Missing bundled manual: {MANUAL}')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    pages = cited_pages()
    with pymupdf.open(MANUAL) as document:
        for page_number in pages:
            if not 1 <= page_number <= len(document):
                raise SystemExit(f'Invalid PDF page: {page_number}')
            pixmap = document[page_number - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
            pixmap.save(OUTPUT / f'{page_number}.png')
    print(f'Rendered {len(pages)} cited pages to {OUTPUT}')


if __name__ == '__main__':
    main()
