import re

import pypdfium2 as pdfium

CEII = re.compile(r"critical energy infrastructure information|\bCEII\b", re.I)
PUBLIC = re.compile(r"public disclosure", re.I)


def read_pages(path):
    doc = pdfium.PdfDocument(str(path))
    return [doc[i].get_textpage().get_text_range().replace("\r\n", "\n").replace("\r", "\n") for i in range(len(doc))]


def page_allowed(text):
    return not CEII.search(text) or bool(PUBLIC.search(text))  # redacted public filings keep the CEII banner


def ceii_blocked(pages, first=3):
    return any(not page_allowed(p) for p in pages[:first])
