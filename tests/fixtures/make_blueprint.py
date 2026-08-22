"""Generate a SANITIZED synthetic mechanical blueprint PDF for SCS plan
intelligence tests + benchmark.

Contains no customer data. Structure mirrors a real small mechanical set:

    M0.1  Cover / drawing index
    M1.1  Mechanical general notes + legend
    M2.1  Air device schedule (13 supply devices across two studios)
    M2.2  Equipment schedule (RTU-5 / RTU-6 supply fans)
    M3.1  Workout Studio A mechanical plan (device tags + room label + CFM)
    M3.2  Workout Studio B mechanical plan
    E1.1  Electrical plan (for sheet-classification negative case)

Devices:
    Studio A  SD-1 type x6: SA-1..SA-6  (180,180,200,200,210,210 = 1180)
    Studio B  SD-2 type x7: SA-7..SA-13 (180,180,180,180,190,165,165 = 1240)
    Returns: RA-1 (Studio A), RA-2 (Studio B)
    Exhaust: EF-1 (Studio A), EF-2 (Studio B)
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF


def _grid(pdf, page, size, cols=4, label_top=None, footer=None):
    # draw a light grid + border to emulate a drafting sheet
    w, h = size.width, size.height
    border = fitz.Rect(18, 18, w - 18, h - 18)
    page.draw_rect(border, color=(0.2, 0.2, 0.2), width=0.5)
    step_x = (w - 40) / cols
    y = 40
    while y < h - 20:
        page.draw_line(fitz.Point(20, y), fitz.Point(w - 20, y),
                       color=(0.85, 0.85, 0.85), width=0.2)
        y += step_x * 0.7
    if label_top:
        page.insert_text(fitz.Point(24, 30), label_top,
                         fontsize=14, fontname="hebo")
    if footer:
        page.insert_text(fitz.Point(24, h - 24), footer,
                         fontsize=9, fontname="helv")


def _title_block(pdf, page, size, sheet_no, sheet_title):
    w, h = size.width, size.height
    page.insert_text(fitz.Point(w - 200, h - 24), f"{sheet_no}   {sheet_title}",
                     fontsize=11, fontname="hebo")


def _draw_table(page, x0, y0, col_widths, headers, rows, size):
    """Draw a table with visible gridlines + text (pdfplumber lines strategy)."""
    fontsize = 9
    row_h = 18
    width = sum(col_widths)
    height = (len(rows) + 1) * row_h
    # horizontal lines
    for i in range(len(rows) + 2):
        y = y0 + i * row_h
        page.draw_line(fitz.Point(x0, y), fitz.Point(x0 + width, y),
                       color=(0, 0, 0), width=1.0)
    # vertical lines
    x = x0
    for cw in col_widths:
        page.draw_line(fitz.Point(x, y0), fitz.Point(x, y0 + height),
                       color=(0, 0, 0), width=1.0)
        x += cw
    page.draw_line(fitz.Point(x, y0), fitz.Point(x, y0 + height),
                   color=(0, 0, 0), width=1.0)
    y = y0
    for i, header in enumerate(headers):
        page.insert_text(fitz.Point(x0 + 3 + sum(col_widths[:i]), y + 13),
                         header, fontsize=fontsize, fontname="hebo")
    y += row_h
    for row in rows:
        for i, cell in enumerate(row):
            if cell:
                page.insert_text(
                    fitz.Point(x0 + 3 + sum(col_widths[:i]), y + 13),
                    str(cell), fontsize=fontsize, fontname="helv")
        y += row_h
    return y


def build_blueprint(path: Path, *, supply_overrides: dict | None = None) -> Path:
    pdf = fitz.open()
    page_size = fitz.paper_rect("letter")
    overrides = supply_overrides or {}

    # ---- M0.1 cover / index ----------------------------------------------
    page = pdf.new_page(width=page_size.width, height=page_size.height)
    _grid(pdf, page, page_size, label_top="SUNSHINE CLIMATE SOLUTIONS LLC",
          footer="COVER SHEET")
    page.insert_text(fitz.Point(120, 200), "WORKOUT STUDIO AIRFLOW",
                     fontsize=20, fontname="hebo")
    page.insert_text(fitz.Point(120, 230), "MECHANICAL DRAWING SET",
                     fontsize=14, fontname="helv")
    for i, line in enumerate(["M0.1 COVER / INDEX", "M1.1 MECHANICAL GENERAL NOTES",
                              "M2.1 AIR DEVICE SCHEDULE", "M2.2 EQUIPMENT SCHEDULE",
                              "M3.1 MECHANICAL PLAN - STUDIO A",
                              "M3.2 MECHANICAL PLAN - STUDIO B"]):
        page.insert_text(fitz.Point(120, 280 + i * 22), line, fontsize=11)
    _title_block(pdf, page, page_size, "M0.1", "COVER / INDEX")

    # ---- M1.1 general notes ----------------------------------------------
    page = pdf.new_page(width=page_size.width, height=page_size.height)
    _grid(pdf, page, page_size, label_top="MECHANICAL GENERAL NOTES",
          footer="MECHANICAL GENERAL NOTES")
    notes = [
        "1. BALANCE ALL SUPPLY OUTLETS TO INDICATED CFM.",
        "2. SET OUTSIDE AIR TO SCHEDULED QUANTITY.",
        "3. BALANCE WITHIN PLUS OR MINUS 10 PERCENT OF DESIGN.",
        "4. COORDINATE WITH CONTROLS CONTRACTOR.",
        "5. VERIFY FAN ROTATION PRIOR TO STARTUP.",
    ]
    for i, note in enumerate(notes):
        page.insert_text(fitz.Point(40, 90 + i * 24), note, fontsize=11)
    _title_block(pdf, page, page_size, "M1.1", "GENERAL NOTES")

    # ---- M2.1 air device schedule ----------------------------------------
    page = pdf.new_page(width=page_size.width, height=page_size.height)
    _grid(pdf, page, page_size, label_top="AIR DEVICE SCHEDULE",
          footer="AIR DEVICE SCHEDULE")
    headers = ["TAG", "TYPE", "SERVICE", "NECK SIZE", "DESIGN CFM", "REMARKS"]
    col_w = [50, 130, 130, 70, 70, 110]
    rows = [
        ["SD-1", "4-WAY CEILING DIFFUSER", "SUPPLY", "10x10", "200", ""],
        ["SD-2", "4-WAY CEILING DIFFUSER", "SUPPLY", "8x8", "180", ""],
        ["SD-3", "LINEAR BAR GRILLE", "SUPPLY", "10x10", "210", ""],
        ["RA-1", "RETURN GRILLE", "RETURN", "24x12", "600", ""],
        ["RA-2", "RETURN GRILLE", "RETURN", "24x12", "650", ""],
        ["EF-1", "EXHAUST GRILLE", "EXHAUST", "8x8", "120", ""],
        ["EF-2", "EXHAUST GRILLE", "EXHAUST", "8x8", "120", ""],
    ]
    _draw_table(page, 40, 90, col_w, headers, rows, page_size)
    _title_block(pdf, page, page_size, "M2.1", "AIR DEVICE SCHEDULE")

    # ---- M2.2 equipment schedule -----------------------------------------
    page = pdf.new_page(width=page_size.width, height=page_size.height)
    _grid(pdf, page, page_size, label_top="EQUIPMENT SCHEDULE",
          footer="EQUIPMENT SCHEDULE")
    headers = ["TAG", "TYPE", "MANUFACTURER", "MODEL", "SUPPLY CFM", "ESP", "REMARKS"]
    col_w = [50, 90, 90, 70, 70, 50, 150]
    rows = [
        ["RTU-5", "RTU", "GREENHECK", "SQ-30", str(overrides.get("RTU-5", 1180)), "0.5", "SERVES WORKOUT STUDIO A"],
        ["RTU-6", "RTU", "GREENHECK", "SQ-30", str(overrides.get("RTU-6", 1240)), "0.5", "SERVES WORKOUT STUDIO B"],
    ]
    _draw_table(page, 40, 90, col_w, headers, rows, page_size)
    _title_block(pdf, page, page_size, "M2.2", "EQUIPMENT SCHEDULE")

    # ---- M3.1 mechanical plan Studio A -----------------------------------
    page = pdf.new_page(width=page_size.width, height=page_size.height)
    _grid(pdf, page, page_size, label_top="MECHANICAL PLAN",
          footer="MECHANICAL PLAN - WORKOUT STUDIO A")
    page.insert_text(fitz.Point(60, 120), "WORKOUT STUDIO A",
                     fontsize=16, fontname="hebo")
    devices_a = [
        ("SA-1", "SD-2", 180), ("SA-2", "SD-2", 180), ("SA-3", "SD-1", 200),
        ("SA-4", "SD-1", 200), ("SA-5", "SD-3", 210), ("SA-6", "SD-3", 210),
    ]
    y = 170
    for tag, dtype, cfm in devices_a:
        page.insert_text(fitz.Point(60, y), f"{tag}", fontsize=12, fontname="hebo")
        page.insert_text(fitz.Point(110, y), f"{dtype}", fontsize=9)
        page.insert_text(fitz.Point(190, y), f"{cfm}", fontsize=10)
        page.insert_text(fitz.Point(225, y), "CFM", fontsize=9)
        y += 34
    page.insert_text(fitz.Point(60, y + 4), "RA-1", fontsize=12, fontname="hebo")
    page.insert_text(fitz.Point(60, y + 40), "EF-1", fontsize=12, fontname="hebo")
    _title_block(pdf, page, page_size, "M3.1", "MECH PLAN - STUDIO A")

    # ---- M3.2 mechanical plan Studio B -----------------------------------
    page = pdf.new_page(width=page_size.width, height=page_size.height)
    _grid(pdf, page, page_size, label_top="MECHANICAL PLAN",
          footer="MECHANICAL PLAN - WORKOUT STUDIO B")
    page.insert_text(fitz.Point(60, 120), "WORKOUT STUDIO B",
                     fontsize=16, fontname="hebo")
    devices_b = [
        ("SA-7", "SD-2", 180), ("SA-8", "SD-2", 180), ("SA-9", "SD-2", 180),
        ("SA-10", "SD-2", 180), ("SA-11", "SD-3", 190), ("SA-12", "SD-1", 165),
        ("SA-13", "SD-1", 165),
    ]
    y = 170
    for tag, dtype, cfm in devices_b:
        page.insert_text(fitz.Point(60, y), f"{tag}", fontsize=12, fontname="hebo")
        page.insert_text(fitz.Point(110, y), f"{dtype}", fontsize=9)
        page.insert_text(fitz.Point(190, y), f"{cfm}", fontsize=10)
        page.insert_text(fitz.Point(225, y), "CFM", fontsize=9)
        y += 30
    page.insert_text(fitz.Point(60, y + 4), "RA-2", fontsize=12, fontname="hebo")
    page.insert_text(fitz.Point(60, y + 40), "EF-2", fontsize=12, fontname="hebo")
    _title_block(pdf, page, page_size, "M3.2", "MECH PLAN - STUDIO B")

    # ---- E1.1 electrical plan (negative classification case) -------------
    page = pdf.new_page(width=page_size.width, height=page_size.height)
    _grid(pdf, page, page_size, label_top="ELECTRICAL POWER PLAN",
          footer="ELECTRICAL POWER PLAN")
    page.insert_text(fitz.Point(60, 120), "POWER PLAN", fontsize=14,
                     fontname="hebo")
    for i, line in enumerate(["LIGHTING CONTACTOR", "PANEL LP-1", "BRANCH CIRCUITS"]):
        page.insert_text(fitz.Point(60, 160 + i * 22), line, fontsize=11)
    _title_block(pdf, page, page_size, "E1.1", "ELECTRICAL POWER PLAN")

    pdf.save(str(path))
    pdf.close()
    return path


def build_raster_blueprint(source_pdf: Path, path: Path, *, dpi: int = 200) -> Path:
    """Rasterize a blueprint PDF into an image-only PDF (scanned-print look).

    Each source page is rendered to a raster image and embedded so native-text
    extraction sees nothing; OCR is the only reader. Used for deterministic
    raster tests and the real-print acceptance.
    """
    src = fitz.open(str(source_pdf))
    out = fitz.open()
    zoom = dpi / 72.0
    for page in src:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img_png = pix.tobytes("png")
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(fitz.Rect(0, 0, page.rect.width, page.rect.height),
                              stream=img_png)
    src.close()
    out.save(str(path))
    out.close()
    return path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="blueprint_fixture.pdf")
    parser.add_argument("--raster", default=None,
                        help="also write a rasterized image-only copy to this path")
    args = parser.parse_args()
    built = build_blueprint(Path(args.out))
    print("wrote", args.out)
    if args.raster:
        build_raster_blueprint(built, Path(args.raster))
        print("wrote", args.raster)
