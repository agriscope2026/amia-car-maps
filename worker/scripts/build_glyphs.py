"""Generate MapLibre SDF glyph tiles (PBF) for the bundled Montserrat fonts.

MapLibre needs glyph PBFs for map labels; generating them from the OFL font files keeps the dashboard on
Montserrat without a third-party glyph server. Output: ../web/public/glyphs/<Font Name>/<start>-<end>.pbf
Run:  python -m scripts.build_glyphs      (needs scipy: pip install scipy)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "assets" / "fonts"
OUT = ROOT.parent / "web" / "public" / "glyphs"

SIZE, BUFFER, RADIUS, CUTOFF = 24, 3, 8, 0.25
RANGES = [(0, 255), (256, 511), (8192, 8447)]   # Latin-1, Latin Extended-A, punctuation (– ’ …)
STACKS = {"Montserrat Regular": "Montserrat-Regular.ttf", "Montserrat Medium": "Montserrat-Medium.ttf",
          "Montserrat SemiBold": "Montserrat-SemiBold.ttf", "Montserrat Bold": "Montserrat-Bold.ttf"}


# -- minimal protobuf writer (glyphs.proto: glyphs{1: fontstack{1: name, 2: range, 3: glyph{…}}}) --
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 31)


def _field_varint(no: int, v: int) -> bytes:
    return _varint(no << 3) + _varint(v)


def _field_bytes(no: int, b: bytes) -> bytes:
    return _varint((no << 3) | 2) + _varint(len(b)) + b


def sdf_glyph(font: ImageFont.FreeTypeFont, ch: str):
    ascent, _ = font.getmetrics()
    advance = round(font.getlength(ch))
    bbox = font.getbbox(ch, anchor="ls")            # relative to the baseline (y up is negative)
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return {"width": 0, "height": 0, "left": 0, "top": -26, "advance": advance, "bitmap": b""}
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    W, H = w + 2 * BUFFER, h + 2 * BUFFER
    img = Image.new("L", (W, H), 0)
    ImageDraw.Draw(img).text((BUFFER - bbox[0], BUFFER - bbox[1]), ch, font=font, fill=255, anchor="ls")
    a = np.asarray(img, dtype=np.float64) / 255.0
    inside = a > 0.5
    d_out = distance_transform_edt(~inside)
    d_in = distance_transform_edt(inside)
    dist = d_out - d_in + (0.5 - a)                 # sub-pixel correction from antialiasing
    val = np.clip(255 - 255 * (dist / RADIUS + CUTOFF), 0, 255).round().astype(np.uint8)
    # MapLibre metric convention: top = glyph top above the baseline minus 26 (24 px glyph tiles, fontnik)
    return {"width": w, "height": h, "left": bbox[0], "top": -bbox[1] - 26, "advance": advance,
            "bitmap": val.tobytes()}


def glyph_message(cid: int, g: dict) -> bytes:
    b = _field_varint(1, cid)
    if g["bitmap"]:
        b += _field_bytes(2, g["bitmap"])
    b += _field_varint(3, g["width"]) + _field_varint(4, g["height"])
    b += _field_varint(5, _zigzag(g["left"])) + _field_varint(6, _zigzag(g["top"])) + _field_varint(7, g["advance"])
    return b


def build_range(name: str, font: ImageFont.FreeTypeFont, start: int, end: int) -> bytes:
    body = _field_bytes(1, name.encode()) + _field_bytes(2, f"{start}-{end}".encode())
    for cid in range(start, end + 1):
        ch = chr(cid)
        if cid < 32 and cid not in (9, 10):
            continue
        try:
            g = sdf_glyph(font, ch)
        except Exception:  # noqa: BLE001
            continue
        body += _field_bytes(3, glyph_message(cid, g))
    return _field_bytes(1, body)


def main():
    for name, file in STACKS.items():
        font = ImageFont.truetype(str(FONTS / file), SIZE)
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        for s, e in RANGES:
            (d / f"{s}-{e}.pbf").write_bytes(build_range(name, font, s, e))
        print("glyphs:", name)


if __name__ == "__main__":
    sys.exit(main())
