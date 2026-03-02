#!/usr/bin/env python3
"""Local test: hybrid approach — DOCX text fill + PDF signature overlay.

This simulates the production flow:
1. Fill DOCX template with python-docx (text only, no signature image)
2. Convert to PDF (locally via Word export; in prod via Gotenberg)
3. Overlay signature image onto the PDF using reportlab

For local testing, we use the PDF template directly (already exported
from Word with placeholders) and overlay both test text replacements
AND the signature. In production, step 1-2 handle text and step 3
handles only the signature.

Usage:
    pyenv shell cyberx-backend
    python scripts/test_pdf_overlay.py
"""
import io
import os
import subprocess

from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import white, Color
from pypdf import PdfReader, PdfWriter

# --- Paths ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../../templates"))

TEMPLATE_PDF = os.path.join(TEMPLATES_DIR, "CyberX_CPE_Certificate_Template.pdf")
SIGNATURE_PNG = os.path.join(TEMPLATES_DIR, "signature.png")
OUTPUT_PDF = os.path.join(TEMPLATES_DIR, "test_overlay_output.pdf")

# --- Page dimensions (landscape US Letter) ---
PAGE_W = 792.0
PAGE_H = 612.0

# --- Signature overlay position (PDF points, origin at bottom-left) ---
# These coordinates position the signature image above the signature line
# in the bottom-left section of the certificate.
# The "Signature" label is at approximately:
#   page_x = 0.24 * 852.3 = 204.5, page_y = 0.24 * (-1357) + 465.12 = 139.4
# The signature line (bottom border of P0) is just above the label.
SIGNATURE_OVERLAY = {
    "x": 160,       # left edge of signature image
    "y": 145,       # bottom edge (just above the signature line)
    "width": 140,   # ~2 inches wide
}


def create_signature_overlay(
    signature_bytes: bytes,
    page_width: float,
    page_height: float,
) -> bytes:
    """Create a single-page PDF with just the signature image."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_width, page_height))

    img = ImageReader(io.BytesIO(signature_bytes))
    img_w, img_h = img.getSize()

    target_w = SIGNATURE_OVERLAY["width"]
    target_h = target_w * (img_h / img_w)  # maintain aspect ratio

    c.drawImage(
        img,
        SIGNATURE_OVERLAY["x"],
        SIGNATURE_OVERLAY["y"],
        width=target_w,
        height=target_h,
        mask="auto",  # preserve PNG transparency
    )

    c.save()
    return buf.getvalue()


def merge_overlay(base_pdf_bytes: bytes, overlay_bytes: bytes) -> bytes:
    """Merge a single-page overlay onto the first page of a PDF."""
    base_reader = PdfReader(io.BytesIO(base_pdf_bytes))
    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))

    page = base_reader.pages[0]
    page.merge_page(overlay_reader.pages[0])

    writer = PdfWriter()
    writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def main():
    print(f"Template: {TEMPLATE_PDF}")
    print(f"Signature: {SIGNATURE_PNG}")
    print(f"Output: {OUTPUT_PDF}")

    assert os.path.exists(TEMPLATE_PDF), f"Not found: {TEMPLATE_PDF}"
    assert os.path.exists(SIGNATURE_PNG), f"Not found: {SIGNATURE_PNG}"

    with open(TEMPLATE_PDF, "rb") as f:
        pdf_bytes = f.read()
    with open(SIGNATURE_PNG, "rb") as f:
        sig_bytes = f.read()

    # Read page dimensions from the actual PDF
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page = reader.pages[0]
    pw = float(page.mediabox.width)
    ph = float(page.mediabox.height)
    print(f"Page size: {pw} x {ph} points ({pw/72:.1f} x {ph/72:.1f} inches)")

    # Create signature overlay and merge
    overlay = create_signature_overlay(sig_bytes, pw, ph)
    final = merge_overlay(pdf_bytes, overlay)

    with open(OUTPUT_PDF, "wb") as f:
        f.write(final)

    print(f"\nSaved: {OUTPUT_PDF} ({len(final)} bytes)")
    print("Opening...")
    subprocess.run(["open", OUTPUT_PDF])


if __name__ == "__main__":
    main()
