"""One-off local helper: generate a single, print-ready A4 PNG with the
Mobile Host confirm app's QR code and a short instruction line underneath.

Not part of the deployed app - run locally once the confirm app has a real
URL, then print the PNG (A4, no scaling) and put it up wherever Mobile Hosts
will see it. Unlike the HK confirm app, there's only ONE QR code here - no
per-hotel split, since Mobile Hosts float between locations rather than
being assigned to one (confirmed with Daria 2026-08-06).

Usage:
    pip install qrcode[pil]
    python scripts/generate_mh_qr_code.py https://your-mh-confirm-app.streamlit.app
"""
from __future__ import annotations

import sys
from pathlib import Path

# A4 @ 300 DPI
PAGE_WIDTH = 2480
PAGE_HEIGHT = 3508
MARGIN = 200
QR_SIZE = 1700

_FONT_CANDIDATES = {
    "bold": ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "regular": ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


def _load_font(kind: str, size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES[kind]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/generate_mh_qr_code.py <confirm-app-url>")
        raise SystemExit(1)

    try:
        import qrcode
        from PIL import Image, ImageDraw
    except ImportError:
        print("Missing dependency - run: pip install qrcode[pil]")
        raise SystemExit(1)

    url = sys.argv[1].rstrip("/")
    out_dir = Path(__file__).resolve().parent.parent / "qr_codes"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "mobile_host_confirm.png"

    qr_img = qrcode.make(url, box_size=20, border=2).convert("RGB")
    qr_img = qr_img.resize((QR_SIZE, QR_SIZE))

    page = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(page)

    title_font = _load_font("bold", 90)
    instruction_font = _load_font("regular", 60)
    subtext_font = _load_font("regular", 44)

    title = "Confirm Your Hours"
    instruction = "Scan with your phone camera to confirm your hours"
    subtext = "Available the 20th\u201323rd of each month"

    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    instruction_bbox = draw.textbbox((0, 0), instruction, font=instruction_font)
    subtext_bbox = draw.textbbox((0, 0), subtext, font=subtext_font)
    title_h = title_bbox[3] - title_bbox[1]
    instruction_h = instruction_bbox[3] - instruction_bbox[1]
    subtext_h = subtext_bbox[3] - subtext_bbox[1]

    gap_title_qr, gap_qr_instruction, gap_instruction_subtext = 140, 100, 40
    content_h = title_h + gap_title_qr + QR_SIZE + gap_qr_instruction + instruction_h + gap_instruction_subtext + subtext_h
    y = (PAGE_HEIGHT - content_h) // 2

    title_x = (PAGE_WIDTH - (title_bbox[2] - title_bbox[0])) // 2
    draw.text((title_x, y), title, fill="black", font=title_font)
    y += title_h + gap_title_qr

    qr_x = (PAGE_WIDTH - QR_SIZE) // 2
    page.paste(qr_img, (qr_x, y))
    y += QR_SIZE + gap_qr_instruction

    instruction_x = (PAGE_WIDTH - (instruction_bbox[2] - instruction_bbox[0])) // 2
    draw.text((instruction_x, y), instruction, fill="black", font=instruction_font)
    y += instruction_h + gap_instruction_subtext

    subtext_x = (PAGE_WIDTH - (subtext_bbox[2] - subtext_bbox[0])) // 2
    draw.text((subtext_x, y), subtext, fill="#444444", font=subtext_font)

    page.save(out_path)
    print(f"{url} -> {out_path}")


if __name__ == "__main__":
    main()
