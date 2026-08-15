"""Split an uploaded PDF into one PNG per page so each page flows through
the same pipeline as a photographed order sheet."""
from pathlib import Path
import pymupdf as fitz  # PyMuPDF

import config


def pdf_to_images(pdf_path: str, dpi: int = 220) -> list[str]:
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    out_paths = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=matrix)
        out_path = config.PROCESSED_DIR / f"{pdf_path.stem}_p{i+1}.png"
        pix.save(str(out_path))
        out_paths.append(str(out_path))
    doc.close()
    return out_paths
