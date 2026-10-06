"""PAGASA seasonal rainfall forecast → seasonal rainfall product (CAR only).

PAGASA publishes the monthly/seasonal rainfall outlook on
https://www.pagasa.dost.gov.ph/climate/climate-prediction/seasonal-forecast as **images** only:
  * "FORECAST RAINFALL in mm (October 2026 - March 2027) as of September 2026" – MIN / MAX / MEAN per province
    and month (CAR is the first block: Abra, Benguet, Ifugao, Kalinga, Apayao, Mountain Province);
  * "FORECAST RAINFALL in % Normal (…)" – one value per province and month.

This module finds those table images on the page, reads the CAR rows with OCR (RapidOCR / ONNX), checks them
(6 provinces × every month, MIN ≤ MEAN ≤ MAX) and turns them into the seasonal-rainfall template: every
municipality gets its province's monthly MEAN (mm); % of normal gives the normal and the season % of normal.

The forecast is provincial. Values read by OCR must be checked against PAGASA's image before publishing –
the result is always a draft, and the report carries the extracted table and the image link for that check.
"""
from __future__ import annotations

import io
import logging
import os
import re
import time
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import reference
from .envi.config import MONTHS
from .envi.io_loader import PROVINCE_DISPLAY, clean_name
from .exports import now_manila

log = logging.getLogger("agriclimate.pagasa_seasonal")
PAGE_URL = os.environ.get("PAGASA_SEASONAL_URL",
                          "https://www.pagasa.dost.gov.ph/climate/climate-prediction/seasonal-forecast")
UA = {"User-Agent": "DA-RFO-CAR AgriClimate Portal (seasonal outlook for CAR; contact DA-RFO-CAR AMIA)"}
CAR = ["ABRA", "APAYAO", "BENGUET", "IFUGAO", "KALINGA", "MOUNTAIN PROVINCE"]
MON3 = {m[:3].upper(): i + 1 for i, m in enumerate(MONTHS)}
STATE_FILE = Path(os.environ.get("OUTPUT_DIR", Path(__file__).resolve().parents[1] / "outputs")) / \
    "pagasa_seasonal_state.json"


# ---------------------------------------------------------------- fetching ---

def _get(url: str, retries: int = 3, timeout: float = 60.0) -> bytes:
    import httpx
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("GET %s failed (%d/%d): %s", url, attempt, retries, e)
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Could not download {url}: {last}")


def candidate_images(html: str) -> list[str]:
    """Image URLs that may hold the forecast tables (rainfall section of the page)."""
    urls = re.findall(r"""(?:src|value)=['"](https?://[^'"]+?\.(?:jpe?g|png))['"]""", html, flags=re.I)
    seen, out = set(), []
    for u in urls:
        if "/climate/" in u and "/rainfall/" in u and u not in seen:
            seen.add(u)
            out.append(u)
    # the tables are not named after a month (the monthly map images are, e.g. "october-2026_…")
    month_named = re.compile(r"/(" + "|".join(m.lower() for m in MONTHS) + r")[-_]?\d{4}", re.I)
    return [u for u in out if not month_named.search(u)] + [u for u in out if month_named.search(u)]


# --------------------------------------------------------------------- OCR ---

@lru_cache(maxsize=1)
def _engine():
    from rapidocr import RapidOCR
    return RapidOCR()


def ocr(image: bytes | Path) -> list[dict]:
    """[{text, x0, y0, x1, y1, cx, cy, score}] for every text box."""
    from PIL import Image
    im = Image.open(io.BytesIO(image) if isinstance(image, (bytes, bytearray)) else image).convert("RGB")
    res = _engine()(np.asarray(im))
    out = []
    if res is None or res.txts is None:
        return out
    for box, txt, sc in zip(res.boxes, res.txts, res.scores):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append({"text": str(txt).strip(), "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
                    "cx": (min(xs) + max(xs)) / 2, "cy": (min(ys) + max(ys)) / 2, "score": float(sc)})
    return out


def _rows(tokens: list[dict], tol: float = 6.0) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for t in sorted(tokens, key=lambda t: t["cy"]):
        if rows and abs(rows[-1][0]["cy"] - t["cy"]) <= tol:
            rows[-1].append(t)
        else:
            rows.append([t])
    return [sorted(r, key=lambda t: t["cx"]) for r in rows]


_NUM = re.compile(r"^-?\d{1,4}(?:[.,]\d{1,2})?$")


def _num(s: str) -> float | None:
    s = s.replace(",", ".").replace(" ", "")
    return float(s) if _NUM.match(s) else None


def _title(tokens: list[dict]) -> str:
    top = [t for t in tokens if t["cy"] < 120]
    return " ".join(t["text"] for t in sorted(top, key=lambda t: (round(t["cy"] / 10), t["cx"])))


def parse_title(text: str) -> dict:
    """'FORECAST RAINFALL in mm (October 2026 - March 2027) as of September 2026' → kind, months, as_of."""
    t = re.sub(r"\s+", " ", text)
    kind = "pct" if re.search(r"%\s*normal", t, re.I) else "mm" if re.search(r"rainfall\s+in\s+mm", t, re.I) else None
    m = re.search(r"\(\s*([A-Za-z]+)\s+(\d{4})\s*[-–]\s*([A-Za-z]+)\s+(\d{4})\s*\)", t)
    a = re.search(r"as\s+of\s+([A-Za-z]+)\s+(\d{4})", t, re.I)
    out = {"kind": kind}
    if m:
        out["start"] = f"{int(m.group(2)):04d}-{MON3[m.group(1)[:3].upper()]:02d}"
        out["end"] = f"{int(m.group(4)):04d}-{MON3[m.group(3)[:3].upper()]:02d}"
    if a and a.group(1)[:3].upper() in MON3:
        out["as_of"] = f"{int(a.group(2)):04d}-{MON3[a.group(1)[:3].upper()]:02d}"
    return out


def _months_between(start: str, end: str) -> list[str]:
    return pd.period_range(start, end, freq="M").strftime("%Y-%m").tolist()


def parse_table(tokens: list[dict], kind: str, months: list[str]) -> dict:
    """CAR rows of a table → {province: {month: {min, max, mean} | {value}}} plus low-confidence cells.

    The table structure is fixed – per month MIN, MAX, MEAN (mm table) or one value (% normal table) – so the
    column positions are taken from complete data rows instead of the header words (OCR may merge
    "MAX MEAN" into one box). Each number is then assigned to the nearest column.
    """
    rows = _rows(tokens)
    fields = ["min", "max", "mean"] if kind == "mm" else ["value"]
    n_cols = len(fields) * len(months)
    # the % normal table has three panes side by side: keep the first (CAR is there)
    prov_hdr = sorted(t["cx"] for r in rows for t in r if t["text"].upper() == "PROVINCE")
    pane_end = prov_hdr[1] - 10 if len(prov_hdr) > 1 else None

    def in_pane(t):
        return pane_end is None or t["cx"] < pane_end

    car_rows = {}
    for r in rows:
        label = clean_name(" ".join(t["text"] for t in r if in_pane(t) and _num(t["text"]) is None))
        prov = next((p for p in CAR if label == p or label.startswith(p + " ") or label == p), None)
        if prov and prov not in car_rows:
            car_rows[prov] = [t for t in r if in_pane(t) and _num(t["text"]) is not None]
    complete = [sorted(r, key=lambda t: t["cx"]) for r in car_rows.values() if len(r) == n_cols]
    if not complete:
        raise ValueError(f"No complete CAR row ({n_cols} numbers) was read from the table image.")
    centers = [float(np.median([r[i]["cx"] for r in complete])) for i in range(n_cols)]
    width = float(np.median(np.diff(centers))) if n_cols > 1 else 60.0

    found, low = {}, []
    for prov, cells_t in car_rows.items():
        cells: dict = {}
        for t in cells_t:
            j = int(np.argmin([abs(t["cx"] - c) for c in centers]))
            if abs(t["cx"] - centers[j]) > width * 0.6:
                continue
            month, field = months[j // len(fields)], fields[j % len(fields)]
            cells.setdefault(month, {})[field] = _num(t["text"])
            if t["score"] < 0.9:
                low.append(f"{PROVINCE_DISPLAY[prov]} {month} {field}: '{t['text']}' ({t['score']:.2f})")
        found[prov] = cells
    return {"values": found, "low_confidence": low}


# ---------------------------------------------------------------- product ---

def read_pagasa(html: str | None = None, fetch=_get) -> dict:
    """Download and read the PAGASA tables. Returns {mm, pct, months, start, as_of, issued, images, report}."""
    html = html if html is not None else fetch(PAGE_URL).decode("utf-8", errors="replace")
    report = {"errors": [], "warnings": [], "source_page": PAGE_URL}
    tables = {}
    for url in candidate_images(html)[:8]:
        try:
            img = fetch(url)
        except Exception as e:  # noqa: BLE001
            report["warnings"].append(f"Could not download {url}: {e}")
            continue
        toks = ocr(img)
        meta = parse_title(_title(toks))
        if meta.get("kind") and meta["kind"] not in tables and "start" in meta:
            tables[meta["kind"]] = {"url": url, "tokens": toks, **meta}
        if "mm" in tables and "pct" in tables:
            break
    if "mm" not in tables:
        report["errors"].append("PAGASA's “Forecast rainfall in mm” table was not found on the seasonal forecast page "
                                "(the page layout may have changed). Upload the seasonal template instead.")
        return {"report": report}
    mm = tables["mm"]
    months = _months_between(mm["start"], mm["end"])
    parsed = parse_table(mm["tokens"], "mm", months)
    out = {"months": months, "start": mm["start"], "as_of": mm.get("as_of"), "images": {"mm": mm["url"]},
           "mm": parsed["values"], "report": report}
    report["warnings"] += [f"Low OCR confidence – check: {x}" for x in parsed["low_confidence"]]
    if "pct" in tables and tables["pct"].get("start") == mm["start"]:
        p = parse_table(tables["pct"]["tokens"], "pct", months)
        out["pct"] = p["values"]
        out["images"]["pct"] = tables["pct"]["url"]
        report["warnings"] += [f"Low OCR confidence – check: {x}" for x in p["low_confidence"]]
    elif "pct" in tables:
        report["warnings"].append("The % of normal table covers other months; it was not used.")
    # checks: every CAR province and month, MIN <= MEAN <= MAX
    for prov in CAR:
        row = out["mm"].get(prov)
        if not row:
            report["errors"].append(f"{PROVINCE_DISPLAY[prov]} was not found in PAGASA's table.")
            continue
        for m in months:
            c = row.get(m, {})
            if "mean" not in c:
                report["errors"].append(f"{PROVINCE_DISPLAY[prov]}, {m}: the MEAN value could not be read.")
            elif "min" in c and "max" in c and not (c["min"] - 0.05 <= c["mean"] <= c["max"] + 0.05):
                report["warnings"].append(f"{PROVINCE_DISPLAY[prov]}, {m}: MEAN {c['mean']} is outside "
                                          f"MIN {c['min']} – MAX {c['max']}; check the image.")
    return out


def to_template(data: dict) -> tuple[bytes, dict]:
    """PAGASA provincial values → seasonal template (one row per municipality) + settings."""
    months = data["months"]
    gz = reference.gazetteer_table()
    rows = []
    for _, g in gz.iterrows():
        prov = g.province
        mm = data["mm"].get(prov, {})
        r = {"PSGC": g.psgc, "PROVINCE": g.province_label, "MUNICIPALITY": g.label}
        normal_total, ok_normal = 0.0, "pct" in data
        for m in months:
            mean = mm.get(m, {}).get("mean")
            r[pd.Period(m, "M").strftime("%b_%Y").upper()] = mean
            pct = (data.get("pct") or {}).get(prov, {}).get(m, {}).get("value")
            if ok_normal and mean is not None and pct:
                normal_total += mean / (pct / 100.0)
            else:
                ok_normal = False
        if ok_normal and normal_total > 0:
            r["NORMAL_MM"] = round(normal_total, 1)
        rows.append(r)
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    as_of = data.get("as_of")
    issued = f"{as_of}-01" if as_of else date.today().isoformat()
    settings = {
        "period_start": data["start"], "issue_date": issued, "data_credit": "DOST-PAGASA",
        "source": "DOST-PAGASA seasonal rainfall forecast (provincial mean, mm), read from "
                  f"{PAGE_URL}; provincial values applied to all municipalities; processed by DA-RFO-CAR AMIA",
        "fetched_from": PAGE_URL, "fetched_at": now_manila(),
    }
    return buf.getvalue(), settings


def extracted_table(data: dict) -> list[dict]:
    """Rows for the admin's check: province × month (min / mean / max, % normal)."""
    out = []
    for prov in CAR:
        for m in data.get("months", []):
            c = data.get("mm", {}).get(prov, {}).get(m, {})
            out.append({"province": PROVINCE_DISPLAY[prov], "month": m, "min": c.get("min"), "mean": c.get("mean"),
                        "max": c.get("max"),
                        "pct_normal": (data.get("pct") or {}).get(prov, {}).get(m, {}).get("value")})
    return out


def build_from_pagasa(settings: dict | None = None, html: str | None = None, fetch=_get) -> dict:
    """Fetch + read + build the seasonal payload (a draft for the admin to check)."""
    from .products import rainfall_seasonal
    data = read_pagasa(html, fetch)
    rep = data["report"]
    if rep["errors"]:
        return {"type": "rainfall_seasonal", "ok": False, "report": rep, "pagasa": {"images": data.get("images")}}
    xlsx, s = to_template(data)
    s = {**s, **{k: v for k, v in (settings or {}).items() if v not in (None, "")}}
    payload = rainfall_seasonal.build(xlsx, "pagasa_seasonal.xlsx", s)
    payload["report"]["warnings"] = rep["warnings"] + [
        "Values were read automatically from PAGASA's table image. Compare them with the image (links below) "
        "before publishing.",
        "PAGASA's forecast is provincial: every municipality shows its province's value."] + \
        payload["report"].get("warnings", [])
    payload["pagasa"] = {"images": data["images"], "table": extracted_table(data), "as_of": data.get("as_of"),
                         "page": PAGE_URL}
    if payload.get("ok"):
        payload.setdefault("method", {})["source"] = "PAGASA seasonal forecast tables (OCR), provincial"
        payload["feed_settings"] = s
    return payload


def run_once(settings: dict | None = None) -> dict:
    import json
    try:
        p = build_from_pagasa(settings)
    except Exception as e:  # noqa: BLE001
        log.exception("PAGASA seasonal fetch failed")
        return {"ok": False, "error": str(e)}
    state = {"last_attempt": now_manila(), "period": p.get("period"), "issued": p.get("issued"),
             "ok": p.get("ok")}
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, default=str), encoding="utf-8")
    except OSError:
        pass
    return {"ok": bool(p.get("ok")), "payload": p, "state": state,
            "error": None if p.get("ok") else "; ".join(p.get("report", {}).get("errors", []))}


if __name__ == "__main__":
    import json
    import sys
    logging.basicConfig(level=logging.INFO)
    r = run_once()
    p = r.get("payload") or {}
    print(json.dumps({"ok": r["ok"], "error": r.get("error"), "period": p.get("period"),
                      "table": (p.get("pagasa") or {}).get("table", [])[:6]}, indent=1, default=str))
    sys.exit(0 if r["ok"] else 1)

_ = datetime
