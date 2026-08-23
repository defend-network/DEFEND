"""Generate synthetic TAB benchmark images with known ground truth.

Used ONLY until real owner photos are provided. Every image is rendered
with PIL from known text, so ground truth is exact. Blur/rotation variants
are included to exercise robustness and honest abstention.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = Path(r"C:\Windows\Fonts")
SANS = str(FONT_DIR / "arial.ttf")
SANS_BOLD = str(FONT_DIR / "arialbd.ttf")
MONO = str(FONT_DIR / "courbd.ttf")
SERIF_ITALIC = str(FONT_DIR / "timesi.ttf")

OUT = Path(r"C:\SCS_DATA\vision-benchmark\images")
GT_PATH = Path(r"C:\SCS_DATA\vision-benchmark\ground_truth.json")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default(size)


def _label(draw: ImageDraw.ImageDraw, xy, text: str, font, fill=(10, 10, 10), anchor="mm"):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _plate(text_lines: list[str], *, w: int, h: int, bg=(220, 222, 228), border=(90, 95, 110), size: int = 28, font_file: str = SANS_BOLD) -> Image.Image:
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w - 1, h - 1], outline=border, width=4)
    font = _font(font_file, size)
    y = h // 2 - (size * len(text_lines)) // 2
    for i, line in enumerate(text_lines):
        _label(draw, (w // 2, y + i * (size + 6)), line, font)
    return img


def _display(readings: list[str], *, label: str = "", w: int = 420, h: int = 220, bg=(28, 32, 38), fg=(0, 255, 120)) -> Image.Image:
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([6, 6, w - 7, h - 7], outline=(70, 80, 90), width=3)
    if label:
        _label(draw, (w // 2, 42), label, _font(SANS, 30), fill=(220, 225, 230))
    big = _font(MONO, 86)
    y = h // 2 + 14 if label else h // 2
    for i, reading in enumerate(readings):
        _label(draw, (w // 2, y + i * 96), reading, big, fill=fg)
    return img


def build() -> list[dict]:
    images: list[tuple[str, Image.Image]] = []
    gt: list[dict] = []

    def add(name: str, img: Image.Image, ground: dict) -> None:
        images.append((name, img))
        gt.append({"file": name, **ground})

    # 1-2. equipment nameplates
    add("carrier_nameplate.png", _plate(["CARRIER", "MODEL 48TC-11A", "SERIAL 2612C41501"], w=720, h=300, size=34),
        {"classification": "NAMEPLATE", "model": "48TC-11A", "serial": "2612C41501", "equipment_type": "RTU"})
    add("trane_nameplate.png", _plate(["TRANE", "MODEL YCD060A1", "SERIAL 4833F2159"], w=760, h=320, bg=(240, 238, 230), size=34),
        {"classification": "NAMEPLATE", "model": "YCD060A1", "serial": "4833F2159", "equipment_type": "AHU"})

    # 3-7. instrument displays
    add("alnor_display.png", _display(["12.4", "CFM"], label="ALNOR AVM440"),
        {"classification": "INSTRUMENT_READING", "readings": [{"value": "12.4", "unit": "CFM"}]})
    add("tsi_display.png", _display(["255", "FPM"], label="TSI 9545"),
        {"classification": "AIRFLOW_READING", "readings": [{"value": "255", "unit": "FPM"}]})
    add("pressure_display.png", _display(["-0.15", "IN.WG"], label="PRESSURE"),
        {"classification": "PRESSURE_READING", "readings": [{"value": "-0.15", "unit": "IN.WG"}]})
    add("temp_rh_display.png", _display(["74.2", "51%RH"], label="TEMP/RH"),
        {"classification": "TEMP_RH_READING", "readings": [{"value": "74.2", "unit": "°F"}, {"value": "51", "unit": "%RH"}]})
    add("controller_display.png", _display(["74.3", "SP 72.0"], label="ZONE 1"),
        {"classification": "INSTRUMENT_READING", "readings": [{"value": "74.3", "unit": "°F"}]})

    # 8-9. no-text photos: classification only, facts must ABSTAIN
    duct = Image.new("RGB", (640, 480), (120, 124, 132))
    ImageDraw.Draw(duct).rectangle([40, 40, 600, 440], outline=(70, 72, 78), width=10)
    add("duct_photo.png", duct, {"classification": "DUCTWORK", "model": None, "serial": None, "readings": []})
    unit = Image.new("RGB", (640, 480), (96, 102, 110))
    d = ImageDraw.Draw(unit)
    d.rectangle([120, 180, 520, 420], outline=(40, 42, 48), width=12)
    d.ellipse([430, 230, 470, 270], outline=(60, 62, 70), width=6)
    add("equipment_photo.png", unit, {"classification": "EQUIPMENT", "model": None, "serial": None, "readings": []})

    # 10. handwritten notes: no structured facts; must NOT invent readings
    notes = Image.new("RGB", (640, 220), (255, 253, 248))
    dn = ImageDraw.Draw(notes)
    _label(dn, (20, 60), "OA damper closed -", _font(SERIF_ITALIC, 44), fill=(30, 30, 40), anchor="lm")
    _label(dn, (20, 130), "verify actuator", _font(SERIF_ITALIC, 44), fill=(30, 30, 40), anchor="lm")
    add("handwritten_notes.png", notes, {"classification": "UNKNOWN", "model": None, "serial": None, "readings": [], "notes_text": "OA damper closed verify actuator"})

    # 11. blurry display: classification expected, values NEED_CONFIRMATION
    blur = _display(["255", "FPM"], label="TSI 9545").filter(ImageFilter.GaussianBlur(6))
    add("blurry_display.png", blur, {"classification": "AIRFLOW_READING", "readings": [{"value": "255", "unit": "FPM"}], "degraded": True})

    # 12. angled display: robustness
    ang = _display(["12.4", "CFM"], label="ALNOR AVM440").rotate(8, expand=True, fillcolor=(28, 32, 38))
    add("angled_display.png", ang, {"classification": "INSTRUMENT_READING", "readings": [{"value": "12.4", "unit": "CFM"}]})

    OUT.mkdir(parents=True, exist_ok=True)
    for name, img in images:
        img.save(OUT / name)
    GT_PATH.write_text(json.dumps(gt, indent=2), encoding="utf-8")
    return gt


if __name__ == "__main__":
    gt = build()
    print(f"wrote {len(gt)} images to {OUT}")
    print(f"ground truth: {GT_PATH}")