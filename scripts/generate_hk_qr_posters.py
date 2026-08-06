"""One-off local helper: generate print-ready A4 poster PNGs (title + QR +
instruction + subtext) for the HK confirm app, one per hotel - same visual
style as scripts/generate_mh_qr_code.py's Mobile Host poster.

Not part of the deployed app. Overwrites qr_codes/<HOTEL>.png for the given
hotel codes (default: VGH, PLH, KOOYK - HAI intentionally excluded per
Daria's instruction when this was built).

Usage:
    pip install qrcode[pil]
    python scripts/generate_hk_qr_posters.py https://your-confirm-app.streamlit.app
    python scripts/generate_hk_qr_posters.py <url> --hotels VGH,PLH,KOOYK,HAI
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hk_dashboard.config import HOTEL_SHEETS  # noqa: E402

# A4 @ 300 DPI - matches generate_mh_qr_code.py exactly
PAGE_WIDTH = 2480
PAGE_HEIGHT = 3508
QR_SIZE = 1700

_FONT_CANDIDATES = {
    "bold": ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "regular": ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}

TITLE = "Scan before you go home every working day"
INSTRUCTION = "Scan with your phone camera to confirm your hours"
SUBTEXT = "Please do not forget to report finish time to Mobile Host"


def _load_font(kind: str, size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES[kind]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _make_poster(url: str, hotel_code: str, out_path: Path) -> None:
    import qrcode
    from PIL import Image, ImageDraw

    qr_img = qrcode.make(url, box_size=20, border=2).convert("RGB")
    qr_img = qr_img.resize((QR_SIZE, QR_SIZE))

    page = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(page)

    # Title wraps to 2 lines on this hotel's poster (longer sentence than
    # the Mobile Host one, so a single 90pt line would run off the page).
    title_font = _load_font("bold", 74)
    instruction_font = _load_font("regular", 60)
    subtext_font = _load_font("regular", 48)

    words = TITLE.split()
    mid = len(words) // 2
    # Balance the two lines around the natural midpoint rather than a hard
    # char-count wrap, so it doesn't break mid-phrase.
    line1, line2 = " ".join(words[:mid]), " ".join(words[mid:])

    line1_bbox = draw.textbbox((0, 0), line1, font=title_font)
    line2_bbox = draw.textbbox((0, 0), line2, font=title_font)
    instruction_bbox = draw.textbbox((0, 0), INSTRUCTION, font=instruction_font)
    subtext_bbox = draw.textbbox((0, 0), SUBTEXT, font=subtext_font)

    line1_h = line1_bbox[3] - line1_bbox[1]
    line2_h = line2_bbox[3] - line2_bbox[1]
    instruction_h = instruction_bbox[3] - instruction_bbox[1]
    subtext_h = subtext_bbox[3] - subtext_bbox[1]

    gap_title_lines = 20
    gap_title_qr, gap_qr_instruction, gap_instruction_subtext = 120, 100, 40
    content_h = (
        line1_h + gap_title_lines + line2_h + gap_title_qr + QR_SIZE
        + gap_qr_instruction + instruction_h + gap_instruction_subtext + subtext_h
    )
    y = (PAGE_HEIGHT - content_h) // 2

    line1_x = (PAGE_WIDTH - (line1_bbox[2] - line1_bbox[0])) // 2
    draw.text((line1_x, y), line1, fill="black", font=title_font)
    y += line1_h + gap_title_lines

    line2_x = (PAGE_WIDTH - (line2_bbox[2] - line2_bbox[0])) // 2
    draw.text((line2_x, y), line2, fill="black", font=title_font)
    y += line2_h + gap_title_qr

    qr_x = (PAGE_WIDTH - QR_SIZE) // 2
    page.paste(qr_img, (qr_x, y))
    y += QR_SIZE + gap_qr_instruction

    instruction_x = (PAGE_WIDTH - (instruction_bbox[2] - instruction_bbox[0])) // 2
    draw.text((instruction_x, y), INSTRUCTION, fill="black", font=instruction_font)
    y += instruction_h + gap_instruction_subtext

    subtext_x = (PAGE_WIDTH - (subtext_bbox[2] - subtext_bbox[0])) // 2
    draw.text((subtext_x, y), SUBTEXT, fill="#444444", font=subtext_font)

    # Small hotel-code label pinned near the page bottom (not part of the
    # centered content block above) - the three posters are otherwise
    # visually identical, so this is just to tell them apart at a glance.
    label_font = _load_font("bold", 40)
    label_bbox = draw.textbbox((0, 0), hotel_code, font=label_font)
    label_x = (PAGE_WIDTH - (label_bbox[2] - label_bbox[0])) // 2
    label_y = PAGE_HEIGHT - 220
    draw.text((label_x, label_y), hotel_code, fill="#888888", font=label_font)

    page.save(out_path)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/generate_hk_qr_posters.py <confirm-app-url> [--hotels VGH,PLH,KOOYK]")
        raise SystemExit(1)

    try:
        import qrcode  # noqa: F401
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except ImportError:
        print("Missing dependency - run: pip install qrcode[pil]")
        raise SystemExit(1)

    base_url = sys.argv[1].rstrip("/")
    hotels = ["VGH", "PLH", "KOOYK"]
    if len(sys.argv) > 2 and sys.argv[2] == "--hotels":
        hotels = sys.argv[3].split(",")

    unknown = [h for h in hotels if h not in HOTEL_SHEETS]
    if unknown:
        print(f"Unknown hotel code(s): {unknown}. Known: {list(HOTEL_SHEETS)}")
        raise SystemExit(1)

    out_dir = Path(__file__).resolve().parent.parent / "qr_codes"
    out_dir.mkdir(exist_ok=True)

    for hotel_code in hotels:
        url = f"{base_url}/?hotel={hotel_code}"
        out_path = out_dir / f"{hotel_code}.png"
        _make_poster(url, hotel_code, out_path)
        print(f"{hotel_code}: {url} -> {out_path}")


if __name__ == "__main__":
    main()
