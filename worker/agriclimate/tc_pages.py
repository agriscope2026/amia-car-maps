"""Special Farm Weather Outlook and Advisory (tropical cyclone) – the exported images.

  * **A4, one page, for printing** (PDF + PNG, 1240 × 1754 design units → 3720 × 5262 px = A4 at 450 dpi): everything
    on one sheet – the storm, the track map with its buffer (extent of the strong winds), the CAR wind-signal map, the
    storm's position / movement / strength, the CAR areas under each signal, what CAR can expect, the farm actions
    and the crop advice. Text shrinks as far as needed so that it always fits the one page.
  * **Facebook posts** (4:5, 1080 × 1350 → 2160 × 2700 px, the portrait size Facebook shows uncropped): title page
    (legend and the outlook in a few lines), the advisory (track map, CAR map, facts, signals), summary and
    recommendations.

Everything keeps a 40-unit margin from the edges, so nothing is cut when Facebook or a printer trims the image.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from PIL import Image

from . import pages, reference
from .envi.presentation import GREEN, GREEN_DARK, INK, LIGHT, MUTED, PANEL_TEXT, _hex
from .pages import _canvas, _fit, _footer, _header, _save

log = logging.getLogger("agriclimate.tc_pages")
A4 = pages.PORTRAIT                   # 1240 × 1754 design units (A4 portrait)
A4_DPI = 450                          # 3720 px over 210 mm
FACEBOOK = (1080, 1350)               # 4:5
FACEBOOK_PX = (2160, 2700)
NAVY = (13, 39, 77)
ORANGE = (150, 60, 0)


def track_image(payload: dict, out_dir: Path) -> Path | None:
    """PAGASA's track and intensity forecast image (the one on the bulletin page), downloaded once per export."""
    url = (payload.get("tc") or {}).get("track_image")
    if not url:
        return None
    path = out_dir / "pagasa_track.png"
    if path.exists():
        return path
    try:
        import io
        from .pagasa_seasonal import _get
        Image.open(io.BytesIO(_get(url, retries=2, timeout=40))).convert("RGB").save(path)
        return path
    except Exception as e:  # noqa: BLE001
        log.warning("PAGASA track image %s not available: %s", url, e)
        return None


# ------------------------------------------------------------------- pieces ---

def car_map(payload: dict, out_dir: Path) -> Path:
    path = out_dir / "tc_car_map.png"
    if not path.exists():
        from .exports import _map_only
        _map_only(payload, payload["layers"][0], path)
    return path


def track_map(payload: dict, out_dir: Path, w: float, h: float, tag: str, units_per_inch: float = 110,
              legend: bool = True) -> Path:
    """The track map for a panel of w × h design units, drawn at the size it is shown: on the A4 1 inch = 150 units
    (1240 units = 210 mm), so the map's font sizes are the printed sizes; Facebook (seen on phones) uses fewer
    units per inch, i.e. relatively larger text."""
    from . import tc_map
    path = out_dir / f"tc_track_map_{tag}.png"
    if not path.exists():
        tc_map.render(payload, path, (w / units_per_inch, h / units_per_inch), dpi=450, legend=legend)
    return path


def _crop_transparent(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    box = im.getbbox()
    return im.crop(box) if box else im


def _signal_rows(payload: dict) -> list[tuple[int, str, list[str]]]:
    """[(signal, province, [municipalities])] – highest signal first."""
    out = []
    for n, keys in sorted(((int(n), ks) for n, ks in (payload["summary"].get("car_by_signal") or {}).items()), reverse=True):
        by: dict[str, list[str]] = {}
        for k in keys:
            by.setdefault(reference.province_display(reference.province_of(k)), []).append(reference.area_label(k))
        for prov, towns in sorted(by.items()):
            out.append((n, prov, sorted(towns)))
    return out


def _signal_color(payload: dict, n: int) -> tuple:
    lg = payload["layers"][0]["legend"]["classes"]
    return _hex(next((c["color"] for c in lg if c["label"] == f"Wind Signal No. {n}"), "#cccccc"))


def _actions(payload: dict) -> list[str]:
    rec = payload.get("texts", {}).get("recommendations") or ""
    return [re.sub(r"^\d+\.\s*", "", l.strip()) for l in rec.split("\n") if re.match(r"^\d+\.", l.strip())]


def _storm(payload: dict) -> str:
    tc = payload.get("tc") or {}
    return f"{tc.get('category') or 'Tropical cyclone'} “{(tc.get('name') or '').title()}”"


def _storm_band(cv, payload: dict, y: float, x: float = 40, w: float | None = None, big: float = 40) -> float:
    tc = payload.get("tc") or {}
    w = w or cv.W - 80
    meta = f"PAGASA TC Bulletin #{tc.get('bulletin_no') or '?'}  ·  {tc.get('issued_text') or ''}"
    head = tc.get("headline") or ""
    hl = cv.wrap(head, "semibold", big * 0.52, w - 48)[:2] if head else []
    h = big * 1.25 + big * 0.55 * 1.5 + 22 + len(hl) * big * 0.52 * 1.32
    cv.rrect(x, y, w, h, NAVY, r=18)
    title = _storm(payload).upper()
    cv.text(x + 24, y + 14, title, "bold", _fit(cv, title, "bold", big, w - 48, 18), PANEL_TEXT)
    cv.text(x + 24, y + 16 + big * 1.25, meta, "semibold", _fit(cv, meta, "semibold", big * 0.55, w - 48, 12), (175, 205, 240))
    yy = y + 20 + big * 1.25 + big * 0.55 * 1.5
    for l in hl:
        cv.text(x + 24, yy, l, "semibold", big * 0.52, (255, 214, 102))
        yy += big * 0.52 * 1.32
    return y + h + 16


def _fact(cv, x, y, w, h, title: str, body: str, color=GREEN_DARK, size: float = 21):
    cv.rrect(x, y, w, h, LIGHT, r=14)
    cv.rect(x, y + 14, 6, h - 28, color)
    cv.text(x + 20, y + 12, title.upper(), "bold", size * 0.8, color)
    while size > 12 and len(cv.wrap(body, "semibold", size, w - 36)) * size * 1.28 > h - size * 0.8 - 30:
        size -= 1
    cv.para(x + 20, y + 20 + size * 0.8, body, w - 36, style="semibold", size=size, fill=INK, lh=1.28)


def _panel(cv, img: Path | Image.Image | None, x, y, w, h, caption: str, missing: str = ""):
    cv.rrect(x, y, w, h, (255, 255, 255), r=14, outline=(214, 222, 216), width=2)
    cv.text(x + 16, y + 10, caption, "bold", _fit(cv, caption, "bold", 20, w - 32, 12), GREEN_DARK)
    if img is None:
        cv.para(x + 16, y + 56, missing, w - 32, size=17, fill=MUTED)
        return
    cv.paste(img, x + 8, y + 40, w - 16, h - 48)


def _facts(payload: dict) -> list[tuple[str, str]]:
    tc = payload.get("tc") or {}
    d = (payload.get("summary") or {}).get("car_distance") or {}
    nxt = (tc.get("next_bulletin") or "").replace("Valid for broadcast until the next advisory to be issued at ", "")
    strength = (f"{tc['max_wind_kmh']:.0f} km/h winds, gusts up to {tc['gust_kmh']:.0f} km/h" if tc.get("max_wind_kmh")
                else tc.get("strength") or "–")
    out = [("Location", tc.get("location_text") or "–"), ("Movement", (tc.get("movement") or "–").replace("Moving ", "")),
           ("Strength", strength)]
    if d.get("closest_km") is not None:
        from .tc_map import _short_time
        out.append(("Closest to CAR", f"About {d['closest_km']:,} km ({_short_time(d.get('closest_time') or '')})"))
    else:
        out.append(("Next bulletin", nxt or "Every 6 hours"))
    return out


# -------------------------------------------- text columns (fit to a box) ---

def _column(cv, x, y, w, blocks: list[tuple], fs: float, draw: bool = True) -> float:
    """Draw (or only measure) text blocks top to bottom; returns the bottom y.

    blocks: ("head", text) | ("sub", text) | ("para", text[, style, color]) | ("num", n, text) | ("bullet", text) |
            ("swatch", color, head, body) | ("crop", label, color, text) | ("gap", h)"""
    for b in blocks:
        kind = b[0]
        if kind == "gap":
            y += b[1]
        elif kind == "head":
            lines = cv.wrap(b[1], "bold", fs + 2, w)
            for i, l in enumerate(lines):
                if draw:
                    cv.text(x, y, l, "bold", fs + 2, GREEN_DARK)
                y += (fs + 2) * (1.22 if i < len(lines) - 1 else 1.5)
        elif kind == "sub":
            lines = cv.wrap(b[1], "bold", fs, w)
            y += 4
            for l in lines:
                if draw:
                    cv.text(x, y, l, "bold", fs, ORANGE)
                y += fs * 1.3
            y += 3
        elif kind == "para":
            style = b[2] if len(b) > 2 else "regular"
            color = b[3] if len(b) > 3 else INK
            for l in cv.wrap(b[1], style, fs - 1, w):
                if draw:
                    cv.text(x, y, l, style, fs - 1, color)
                y += (fs - 1) * 1.3
            y += 6
        elif kind in ("num", "bullet"):
            ind = fs * 1.6
            lines = cv.wrap(b[2] if kind == "num" else b[1], "regular", fs - 1, w - ind)
            if draw:
                if kind == "num":
                    cv.text(x, y, f"{b[1]}.", "bold", fs - 1, GREEN)
                else:
                    r = fs * 0.17
                    cv.d.ellipse([(x + 5 - r) * cv.s, (y + fs * 0.55 - r) * cv.s, (x + 5 + r) * cv.s,
                                  (y + fs * 0.55 + r) * cv.s], fill=GREEN)
                for i, l in enumerate(lines):
                    cv.text(x + ind, y + i * (fs - 1) * 1.3, l, "regular", fs - 1, INK)
            y += len(lines) * (fs - 1) * 1.3 + 5
        elif kind == "swatch":
            _, color, head, body = b
            if draw:
                cv.rect(x, y + 3, fs * 1.1, fs * 0.85, color, outline=(90, 90, 90))
                cv.text(x + fs * 1.6, y, head, "bold", fs, INK)
            y += fs * 1.32
            for l in cv.wrap(body, "regular", fs - 2, w - fs * 1.6):
                if draw:
                    cv.text(x + fs * 1.6, y, l, "regular", fs - 2, INK)
                y += (fs - 2) * 1.3
            y += 6
        elif kind == "crop":
            _, label, color, text = b
            lab = f"{label}: "
            lw = cv.width(lab, "bold", fs - 1)
            lines = cv.wrap(text, "regular", fs - 1, w - lw)
            if draw:
                cv.text(x, y, lab, "bold", fs - 1, color)
                for i, l in enumerate(lines):
                    cv.text(x + lw, y + i * (fs - 1) * 1.3, l, "regular", fs - 1, INK)
            y += len(lines) * (fs - 1) * 1.3 + 5
    return y


def _fit_columns(cv, cols: list[tuple[float, float, list[tuple]]], y: float, bottom: float, hi: float = 22, lo: float = 12) -> float:
    """Largest font size (hi → lo) with which every column fits between y and bottom; draws them."""
    fs = hi
    while fs > lo and any(_column(cv, x, y, w, blocks, fs, draw=False) > bottom for x, w, blocks in cols):
        fs -= 0.5
    for x, w, blocks in cols:
        _column(cv, x, y, w, blocks, fs)
    return fs


def _signal_blocks(payload: dict) -> list[tuple]:
    from .pagasa_tc import LEAD, WINDS
    rows = _signal_rows(payload)
    out: list[tuple] = [("head", "WIND SIGNALS IN CAR")]
    if not rows:
        out.append(("para", "No Tropical Cyclone Wind Signal is raised over the Cordillera Administrative Region in this "
                            "bulletin.", "semibold"))
    for n, prov, towns in rows:
        out.append(("swatch", _signal_color(payload, n), f"Signal No. {n} – {prov}", ", ".join(towns)))
    for n in sorted({n for n, _, _ in rows}, reverse=True):
        out.append(("para", f"Signal No. {n}: winds of {WINDS[n]} within {LEAD[n]}.", "italic", MUTED))
    s = payload.get("summary") or {}
    if s.get("car_gusts"):
        days = ", ".join(f"{g['day']} ({g['date']})" for g in s["car_gusts"])
        out.append(("para", f"Strong to gale-force gusts in CAR: {days}, especially in upland and exposed areas.",
                    "semibold", ORANGE))
    if s.get("car_rain") and not s.get("car_rainfall"):
        out.append(("para", "Heavy rain is expected over parts of CAR – see the PAGASA rainfall advisory.", "semibold", ORANGE))
    return out


def _crop_blocks(payload: dict) -> list[tuple]:
    t = payload.get("texts", {})
    return [("crop", lab, _hex(col), t[k]) for k, lab, col in pages._ADVICE if t.get(k)]


def in_short(payload: dict) -> list[str]:
    """The outlook in a few plain lines (first Facebook post): the storm, the towns under a signal, rain, gusts, and
    how soon to act. One fact per line, no repetition of the map or of the steps (they are on the next post)."""
    from .tc_map import _short_time
    tc = payload.get("tc") or {}
    s = payload.get("summary") or {}
    lines = []
    if tc.get("location_text"):
        wind = f", winds of {tc['max_wind_kmh']:.0f} km/h" if tc.get("max_wind_kmh") else ""
        lines.append(f"{_storm(payload)} is {tc['location_text'].split(' (')[0]}, "
                     f"{(tc.get('movement') or '').replace('Moving ', 'moving ').lower()}{wind}.")
    for n, prov, towns in _signal_rows(payload):
        lines.append(f"Wind Signal No. {n} – {prov}: {', '.join(towns)}.")
    if not _signal_rows(payload):
        lines.append("No wind signal is raised over CAR yet.")
    for prov, days in sorted((s.get("car_rainfall") or {}).items()):
        worst = max(days, key=lambda d: {"50–100 mm": 1, "100–200 mm": 2, ">200 mm": 3}.get(d[1], 0))[1]
        when = pages._list([d.lower() if d.lower().startswith("to") else d for d, _ in days])
        lines.append(f"Heavy rain in {prov} {when} ({worst}): flooding and landslides are possible.")
    if s.get("car_gusts"):
        days = pages._list([g["day"].lower() if g["day"].lower().startswith("to") else g["day"] for g in s["car_gusts"]])
        lines.append(f"Strong gusts over CAR {days}, especially in upland and exposed areas.")
    d = s.get("car_distance") or {}
    sit = s.get("situation") or {}
    act = {"imminent": "act now", "approaching": "prepare within the next 24 hours"}.get(sit.get("stage"), "get ready")
    if d.get("closest_km") is not None:
        lines.append(f"Closest to CAR on {_short_time(d.get('closest_time') or '')} (about {d['closest_km']:,} km) – "
                     f"{act}. What to do: see the next post.")
    else:
        lines.append(f"{act[0].upper() + act[1:]}. What to do: see the next post.")
    return lines


# -------------------------------------------------------- A4, one page (PDF) ---

def _a4_header(cv, payload: dict) -> float:
    """DA-RFO-CAR / AMIA letterhead with the three logos, then the green title bar; returns the y below it."""
    from .envi import config as envi_config
    W = cv.W
    x = 40
    for name, w in (("Bagong_Pilipinas_logo.png", 96), ("DA CAR LOGO no background.png", 104), ("AMIA_Logo.png", 92)):
        p = envi_config.LOGO_DIR / name
        if p.exists():
            _, _, lw, _ = cv.paste(p, x, 22, w, 96, align="left")
            x += lw + 16
    cv.d.line([((x + 2) * cv.s, 26 * cv.s), ((x + 2) * cv.s, 114 * cv.s)], fill=(160, 160, 160), width=int(2 * cv.s))
    tx, tw = x + 22, W - x - 62
    l1 = "DEPARTMENT OF AGRICULTURE"
    l2 = "Regional Field Office – Cordillera Administrative Region"
    l3 = "Adaptation and Mitigation Initiative in Agriculture (AMIA) Program"
    cv.text(tx, 24, l1, "bold", _fit(cv, l1, "bold", 30, tw, 18), GREEN_DARK)
    cv.text(tx, 62, l2, "semibold", _fit(cv, l2, "semibold", 24, tw, 16), GREEN)
    cv.text(tx, 94, l3, "bold", _fit(cv, l3, "bold", 22, tw, 14), pages.AMBER)
    y = 136
    tc = payload.get("tc") or {}
    title = "SPECIAL FARM WEATHER OUTLOOK AND ADVISORY"
    sub = f"for Cordillera Administrative Region  ·  as of {tc.get('issued_text') or payload.get('issued', '')}"
    cv.rrect(40, y, W - 80, 104, _hex("#0b6237"), r=16)
    cv.d.text((W / 2 * cv.s, (y + 14) * cv.s), title, font=pages._extrabold(cv, _fit(cv, title, "bold", 40, W - 140, 24)),
              fill=(255, 255, 255), anchor="ma")
    cv.text(W / 2, y + 66, sub, "semibold", _fit(cv, sub, "semibold", 22, W - 140, 14), (214, 240, 222), anchor="ma")
    return y + 104 + 14


def _rain_blocks(payload: dict) -> list[tuple]:
    rain = (payload.get("summary") or {}).get("car_rainfall") or {}
    if not rain:
        return []
    out: list[tuple] = [("head", "HEAVY RAINFALL (PAGASA)")]
    adv = (payload.get("tc") or {}).get("rain_advisory") or {}
    impacts = {r["class"]: r["impact"] for r in adv.get("rows", [])}
    for prov, days in sorted(rain.items()):
        by: dict[str, list[str]] = {}
        for d, c in days:
            by.setdefault(c, []).append(d)
        for c, ds in by.items():
            out.append(("swatch", _hex("#1e88e5" if c == "50–100 mm" else "#3949ab" if c == "100–200 mm" else "#6a1b9a"),
                        f"{prov}: {c}", f"{pages._list([d.lower() if d.lower().startswith('to') else d for d in ds])} – "
                                        "floods and landslides possible."))
    for w in (payload.get("tc") or {}).get("regional_warnings") or []:
        out.append(("para", f"{w['kind']} (PAGASA Northern Luzon): {w['text'][:300]}", "semibold", ORANGE))
    return out


def _rec_blocks(payload: dict, numbered_only: bool = False) -> list[tuple]:
    """The recommendations as blocks: section heads ("NOW – …:", "During the storm:") and numbered steps; the
    situation sentences above the first section are left out (the signal and rain blocks say it)."""
    out: list[tuple] = []
    started = False
    for kind, line in pages._rec_lines(payload.get("texts", {}).get("recommendations") or ""):
        if kind == "head":
            if line.rstrip().endswith(":"):
                started = True
                if not numbered_only:
                    out.append(("sub", line.rstrip(":")))
            continue
        if kind == "num":
            m = re.match(r"^(\d+)[.)]\s*(.*)$", line)
            out.append(("num", int(m.group(1)), m.group(2)) if m else ("bullet", line))
            started = True
        elif started:
            out.append(("bullet", line))
    return out


def _flow(cv, cols: list[tuple[float, float]], y: float, bottom: float, blocks: list[tuple], hi: float, lo: float,
          keep_heads: bool = True) -> float:
    """Newspaper columns: the blocks fill the first column, then the next. Largest font size (hi → lo) at which
    everything fits; a heading never ends a column. Returns the font size used."""
    def place(fs: float, draw: bool) -> bool:
        ci, yy = 0, y
        i = 0
        while i < len(blocks):
            b = blocks[i]
            h = _column(cv, 0, 0, cols[ci][1], [b], fs, draw=False)
            nxt = _column(cv, 0, 0, cols[ci][1], [blocks[i + 1]], fs, draw=False) if keep_heads and b[0] in ("head", "sub") and i + 1 < len(blocks) else 0
            if yy + h + nxt > bottom and yy > y:
                ci += 1
                yy = y
                if ci >= len(cols):
                    return False
                continue
            if draw:
                _column(cv, cols[ci][0], yy, cols[ci][1], [b], fs)
            yy += h
            i += 1
        return True

    fs = hi
    while fs > lo and not place(fs, False):
        fs -= 0.5
    if not place(fs, False):
        log.warning("A4 text does not fit at %.1f units – the end is cut", fs)
    place(fs, True)
    return fs


def _map_key(cv, payload: dict, x: float, y: float, w: float):
    """The track map's legend as one line under it (the A4 map is small: a legend inside would cover the track)."""
    from .tc_map import BUFFER_EDGE, BUFFER_FILL, TRACK
    km = (payload.get("tc") or {}).get("wind_extent_km")
    items = [("dot", "Storm centre now"), ("line", "Forecast track"), ("ring", "Outside PAR")]
    if km:
        items.append(("buffer", f"Strong winds: {km:,.0f} km of the track"))
    items.append(("dash", "PAR"))
    fs = 16
    total = sum(cv.width(t, "regular", fs) + 46 for _, t in items)
    while total > w and fs > 11:
        fs -= 0.5
        total = sum(cv.width(t, "regular", fs) + 46 for _, t in items)
    xx = x + (w - total) / 2
    cy = y + 16
    red = _hex(TRACK)
    for kind, text in items:
        if kind == "dot":
            cv.d.ellipse([(xx + 6) * cv.s, (cy - 7) * cv.s, (xx + 20) * cv.s, (cy + 7) * cv.s], fill=red, outline=(255, 255, 255))
        elif kind == "ring":
            cv.d.ellipse([(xx + 8) * cv.s, (cy - 6) * cv.s, (xx + 20) * cv.s, (cy + 6) * cv.s], fill=(255, 255, 255), outline=red,
                         width=int(2 * cv.s))
        elif kind == "line":
            cv.d.line([(xx * cv.s, cy * cv.s), ((xx + 26) * cv.s, cy * cv.s)], fill=red, width=int(3 * cv.s))
        elif kind == "buffer":
            cv.rect(xx, cy - 8, 26, 16, (255, 224, 178), outline=_hex(BUFFER_EDGE))
        elif kind == "dash":
            for k in range(3):
                cv.d.line([((xx + k * 10) * cv.s, cy * cv.s), ((xx + k * 10 + 6) * cv.s, cy * cv.s)], fill=(55, 71, 79),
                          width=int(2 * cv.s))
        cv.text(xx + 34, cy, text, "regular", fs, INK, anchor="lm")
        xx += cv.width(text, "regular", fs) + 46
    _ = BUFFER_FILL


def a4_page(payload: dict, out_dir: Path) -> dict:
    cv = _canvas(A4)
    W, H = cv.W, cv.H
    y = _a4_header(cv, payload)
    y = _storm_band(cv, payload, y, big=32)
    # maps: the track with its buffer (left), CAR by wind signal (right)
    tw = 700
    img = track_image(payload, out_dir)
    if img is not None:
        mh = (tw - 16) * Image.open(img).height / Image.open(img).width + 48
        _panel(cv, img, 40, y, tw, mh, "Track and intensity forecast (DOST-PAGASA)")
    else:
        mh, key = 470, 34
        _panel(cv, track_map(payload, out_dir, tw - 16, mh - 48 - key, "a4", legend=False), 40, y, tw, mh - key,
               "Forecast track and reach of the strong winds (DOST-PAGASA data)")
        _map_key(cv, payload, 48, y + mh - key + 2, tw - 16)
    # CAR by wind signal, with the legend of every signal class under the map
    cx, cw_ = 40 + tw + 16, W - 80 - tw - 16
    leg_fs = 17
    leg_h = 6 * leg_fs * 1.42 + 14
    _panel(cv, None, cx, y, cw_, mh, "Wind signals in CAR")
    cv.paste(_crop_transparent(car_map(payload, out_dir)), cx + 8, y + 40, cw_ - 16, mh - 52 - leg_h)
    _legend_all(cv, payload, cx + 20, y + mh - leg_h, fs=leg_fs)
    y += mh + 12
    facts = _facts(payload)
    fw = (W - 80 - 3 * 12) / 4
    for i, (t, b) in enumerate(facts):
        _fact(cv, 40 + i * (fw + 12), y, fw, 92, t, b, size=19)
    y += 92 + 16
    # text in two newspaper columns: signals, rain, outlook, then what to do (now / during / after) and crop advice
    bottom = H - 112
    # (the track narrative is on the map, the crop advice is in the steps: both stay on the Facebook posts)
    hp = (payload.get("tc") or {}).get("highest_possible")
    blocks = (_signal_blocks(payload) + ([("para", hp, "italic", MUTED)] if hp else []) + _rain_blocks(payload)
              + [("head", "WHAT FARMERS SHOULD DO")] + _rec_blocks(payload))
    gap = 28
    cw = (W - 80 - gap) / 2
    cv.rect(40 + cw + gap / 2 - 1, y, 2, bottom - y, (214, 222, 216))
    fs = _flow(cv, [(40, cw), (40 + cw + gap, cw)], y, bottom, blocks, hi=22, lo=14)
    log.info("A4 text at %.1f units", fs)
    disc = payload.get("texts", {}).get("disclaimer") or ""
    if disc:
        cv.text(40, H - 104, disc, "italic", _fit(cv, disc, "italic", 15, W - 80, 10), MUTED)
    _footer(cv, payload)
    png, jpg = _save(cv, out_dir / "tc_advisory_a4.png", out_dir / "tc_advisory_a4_preview.jpg")
    pdf = out_dir / "tc_advisory_a4.pdf"
    Image.open(png).convert("RGB").save(pdf, "PDF", resolution=A4_DPI, title=payload.get("texts", {}).get("title"),
                                        author="DA-RFO-CAR AMIA", subject=payload["period"]["label"])
    return {"layer": "a4", "label": "A4 – print (1 page)", "pdf": pdf.name, "poster": png.name, "poster_web": jpg.name,
            "alt": f"Special Farm Weather Outlook and Advisory for CAR, {payload['period']['label']}: one A4 page with "
                   "the track forecast, the CAR wind signals, the rainfall outlook and the farm advisory"}


# ------------------------------------------------------------ Facebook posts ---

def _fb_header(cv, payload: dict, kicker: str) -> float:
    """Compact letterhead for the posts: logos, DA-RFO-CAR · AMIA, the product name and the kicker."""
    from .envi import config as envi_config
    W = cv.W
    x = 40
    for name, w in (("Bagong_Pilipinas_logo.png", 70), ("DA CAR LOGO no background.png", 76), ("AMIA_Logo.png", 66)):
        p = envi_config.LOGO_DIR / name
        if p.exists():
            _, _, lw, _ = cv.paste(p, x, 22, w, 70, align="left")
            x += lw + 10
    tx, tw = x + 16, W - x - 56
    l1 = "DA-RFO Cordillera Administrative Region · AMIA Program"
    cv.text(tx, 24, l1, "semibold", _fit(cv, l1, "semibold", 20, tw, 13), GREEN)
    l2 = "SPECIAL FARM WEATHER OUTLOOK AND ADVISORY"
    cv.d.text((tx * cv.s, 52 * cv.s), l2, font=pages._extrabold(cv, _fit(cv, l2, "bold", 28, tw, 16)), fill=_hex("#0b6237"))
    cv.text(tx, 90, kicker, "semibold", _fit(cv, kicker, "semibold", 19, tw, 12), pages.AMBER)
    return 120


def _legend_all(cv, payload: dict, x: float, y: float, fs: float = 18) -> float:
    """Every wind signal class (No. 1–5 and "no wind signal"); returns the bottom."""
    for c in payload["layers"][0]["legend"]["classes"]:
        label = c["label"].replace("Wind Signal No.", "Signal No.")
        cv.rect(x, y + 3, fs * 1.4, fs * 0.95, _hex(c["color"]), outline=(90, 90, 90))
        cv.text(x + fs * 1.9, y, label, "semibold", fs, INK)
        y += fs * 1.42
    return y


def advisory_post(payload: dict, out_dir: Path) -> dict:
    """The first post: PAGASA's track image (what people see first), CAR's signals with the full legend, and the
    summary."""
    cv = _canvas(FACEBOOK)
    W, H = cv.W, cv.H
    tc = payload.get("tc") or {}
    y = _fb_header(cv, payload, f"for CAR  ·  as of {tc.get('issued_text') or payload.get('issued', '')}")
    storm = _storm(payload).upper()
    meta = f"PAGASA Bulletin #{tc.get('bulletin_no') or '?'}"
    cv.rrect(40, y, W - 80, 62, NAVY, r=14)
    cv.text(60, y + 31, storm, "bold", _fit(cv, storm, "bold", 32, W - 360, 18), PANEL_TEXT, anchor="lm")
    cv.text(W - 60, y + 31, meta, "semibold", 20, (175, 205, 240), anchor="rm")
    y += 62 + 12
    # PAGASA's track (left) | CAR's wind signals with the full legend (right)
    tw = 690
    img = track_image(payload, out_dir)
    ph = (tw - 16) * (Image.open(img).height / Image.open(img).width if img else 0.82) + 48
    if img is not None:
        _panel(cv, img, 40, y, tw, ph, "Track forecast (DOST-PAGASA)")
    else:
        _panel(cv, track_map(payload, out_dir, tw - 16, ph - 48, "facebook", units_per_inch=95), 40, y, tw, ph,
               "Track forecast (DOST-PAGASA data)")
    rx, rw = 40 + tw + 12, W - 80 - tw - 12
    cv.rrect(rx, y, rw, ph, (255, 255, 255), r=14, outline=(214, 222, 216), width=2)
    cv.text(rx + 14, y + 10, "SIGNALS IN CAR", "bold", 19, GREEN_DARK)
    leg_h = 6 * 17 * 1.42 + 8
    cv.paste(_crop_transparent(car_map(payload, out_dir)), rx + 6, y + 38, rw - 12, ph - 50 - leg_h)
    _legend_all(cv, payload, rx + 16, y + ph - leg_h, fs=17)
    y += ph + 12
    # summary
    bottom = H - 96
    cv.rrect(40, y, W - 80, bottom - y, NAVY, r=14)
    cv.text(60, y + 12, "SUMMARY", "bold", 24, (255, 214, 102))
    lines = in_short(payload)
    fs = 28

    def height(f):
        return sum(len(cv.wrap(l, "regular", f, W - 150)) * f * 1.28 + 12 for l in lines)
    while fs > 15 and height(fs) > bottom - y - 58:
        fs -= 0.5
    yy = y + 54
    for l in lines:
        r = fs * 0.18
        cv.d.ellipse([(68 - r) * cv.s, (yy + fs * 0.6 - r) * cv.s, (68 + r) * cv.s, (yy + fs * 0.6 + r) * cv.s],
                     fill=(255, 214, 102))
        for w_ in cv.wrap(l, "regular", fs, W - 150):
            cv.text(88, yy, w_, "regular", fs, PANEL_TEXT)
            yy += fs * 1.28
        yy += 12
    _footer(cv, payload)
    png, jpg = _save(cv, *pages._files(payload, out_dir, "advisory", "facebook"))
    return {"layer": "advisory", "label": "Advisory", "png": png, "jpg": jpg,
            "alt": f"Special Farm Weather Outlook and Advisory for CAR: {_storm(payload)} – PAGASA track forecast, the CAR "
                   "municipalities under wind signals, and the summary"}


def _sections(payload: dict) -> list[tuple[str, list[tuple]]]:
    """The recommendations split at their section heads: [(head, blocks)]."""
    out: list[tuple[str, list[tuple]]] = []
    for b in _rec_blocks(payload):
        if b[0] == "sub":
            out.append((b[1], []))
        elif out:
            out[-1][1].append(b)
    return out


def action_posts(payload: dict, out_dir: Path) -> list[dict]:
    """What farmers should do: the first section ("now" / "within 24 hours") on one post, the rest (during and after
    the storm) on the next – big type for phones."""
    secs = _sections(payload)
    if not secs:
        return []
    groups = [secs[:1], secs[1:]] if len(secs) > 1 else [secs]
    out = []
    for k, group in enumerate(groups, start=1):
        cv = _canvas(FACEBOOK)
        W, H = cv.W, cv.H
        y = _fb_header(cv, payload, f"What farmers should do  ·  {_storm(payload)}")
        blocks: list[tuple] = []
        for head, bl in group:
            blocks += [("head", head.upper())] + bl
        fs = _flow(cv, [(48, W - 96)], y + 10, H - 104, blocks, hi=40, lo=17)
        log.info("Facebook actions post %d at %.1f units", k, fs)
        _footer(cv, payload)
        pid = "recommendations" if k == 1 else f"recommendations_{k}"
        png, jpg = _save(cv, *pages._files(payload, out_dir, pid, "facebook"))
        out.append({"layer": pid, "label": "What to do" if k == 1 else "During and after the storm", "png": png, "jpg": jpg,
                    "alt": f"What farmers in CAR should do – {', '.join(h for h, _ in group)}"})
    return out


def _facebook_size(png: Path) -> None:
    """Facebook shows 1080 px wide (2160 px for sharp phones); a smaller file uploads faster."""
    with Image.open(png) as im:
        im = im.convert("RGB").resize(FACEBOOK_PX, Image.LANCZOS)
    im.save(png, optimize=True)


def export(payload: dict, out_dir: Path, progress) -> list[dict]:
    """The one-page A4 (PDF + PNG), then the Facebook posts: the advisory (track first), then what to do."""
    progress("pages", "running", "Making the A4 page (PDF)")
    out = [a4_page(payload, out_dir)]
    progress("pages", "running", "Making the Facebook posts")
    for p in [advisory_post(payload, out_dir), *action_posts(payload, out_dir)]:
        _facebook_size(p["png"])
        out.append({"layer": p["layer"], "label": p["label"], "alt": p["alt"], "social": p["png"].name,
                    "social_web": p["jpg"].name})
    return out


__all__ = ["export", "a4_page", "advisory_post", "action_posts", "in_short", "FACEBOOK", "A4"]
