"""One-off local helper: generate one QR code PNG per hotel, pointing at the
deployed confirm_app.py URL with that hotel pre-selected.

Not part of the deployed app - run locally once the confirm app has a real
URL, then print the PNGs and place one at each hotel.

Usage:
    pip install qrcode[pil]
    python scripts/generate_qr_codes.py https://your-confirm-app.streamlit.app
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hk_dashboard.config import HOTEL_SHEETS  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/generate_qr_codes.py <confirm-app-url>")
        raise SystemExit(1)

    try:
        import qrcode
    except ImportError:
        print("Missing dependency - run: pip install qrcode[pil]")
        raise SystemExit(1)

    base_url = sys.argv[1].rstrip("/")
    out_dir = Path(__file__).resolve().parent.parent / "qr_codes"
    out_dir.mkdir(exist_ok=True)

    for hotel_code in HOTEL_SHEETS:
        url = f"{base_url}/?hotel={hotel_code}"
        img = qrcode.make(url)
        out_path = out_dir / f"{hotel_code}.png"
        img.save(out_path)
        print(f"{hotel_code}: {url} -> {out_path}")


if __name__ == "__main__":
    main()
