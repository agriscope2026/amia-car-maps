"""Continuous 10-day rainfall feed (Cordillera weather API) → 10-day rainfall product draft.

Source: ``RAINFALL_FEED_URL`` (default https://cordillera-weather.onrender.com/api/cordillera/full/), which
returns ``metadata`` (issuance_date, start_date, end_date as M/D/YYYY) and ``data`` rows
``{date, province, municity, rainfall_total (mm), …}`` – one row per municipality per day.

Only the rainfall is used: daily ``rainfall_total`` values become DAY_1 … DAY_n columns in the standard
10-day template, so the feed goes through exactly the same validation and name matching as a manual
upload. The result is a draft; an admin still reviews and publishes it.
Run on a schedule:  python -m agriclimate.rainfall_feed
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import reference
from .exports import now_manila
from .products import rainfall_dekad

log = logging.getLogger("agriclimate.rainfall_feed")
DEFAULT_URL = "https://cordillera-weather.onrender.com/api/cordillera/full/"
STATE_FILE = Path(os.environ.get("OUTPUT_DIR", Path(__file__).resolve().parents[1] / "outputs")) / \
    "rainfall_feed_state.json"


def _date(s: str):
    return datetime.strptime(s.strip(), "%m/%d/%Y").date()


def fetch_json(url: str | None = None, retries: int = 3, backoff: float = 3.0, timeout: float = 90.0) -> dict:
    """GET the feed with retries (the host may cold-start, hence the long timeout)."""
    import httpx
    url = url or os.environ.get("RAINFALL_FEED_URL") or DEFAULT_URL
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "DA-RFO-CAR AgriClimate Portal", "Accept": "application/json"})
            r.raise_for_status()
            data = r.json()
            log.info("fetched %s: %d rows on attempt %d", url, len(data.get("data", [])), attempt)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("feed attempt %d/%d failed: %s", attempt, retries, e)
            if attempt < retries:
                time.sleep(backoff ** attempt)
    raise RuntimeError(f"Rainfall feed failed after {retries} attempts: {last}")


def to_template(feed: dict) -> tuple[bytes, dict]:
    """Feed JSON → (10-day template XLSX bytes, settings with the dekad dates and issue date)."""
    meta = feed.get("metadata") or {}
    rows = feed.get("data") or []
    if not rows:
        raise ValueError("The feed returned no data rows.")
    df = pd.DataFrame(rows)
    missing = {"date", "province", "municity", "rainfall_total"} - set(df.columns)
    if missing:
        raise ValueError(f"The feed is missing fields: {sorted(missing)}")
    df["day"] = df["date"].map(_date)
    start = _date(meta["start_date"]) if meta.get("start_date") else df.day.min()
    end = _date(meta["end_date"]) if meta.get("end_date") else df.day.max()
    issued = _date(meta["issuance_date"]) if meta.get("issuance_date") else start
    days = pd.date_range(start, end, freq="D").date
    wide = df.pivot_table(index=["province", "municity"], columns="day", values="rainfall_total", aggfunc="first")
    wide = wide.reindex(columns=days)
    out = pd.DataFrame({"PROVINCE": [p for p, _ in wide.index], "MUNICIPALITY": [m for _, m in wide.index]})
    for i, d in enumerate(days, 1):
        out[f"DAY_{i}"] = wide[d].to_numpy()
    gz = reference.gazetteer_table()
    psgc = dict(zip(gz.label.str.upper(), gz.psgc))
    out.insert(0, "PSGC", out.MUNICIPALITY.str.upper().map(psgc))
    buf = io.BytesIO()
    out.to_excel(buf, index=False)
    settings = {"period_start": start.isoformat(), "period_end": end.isoformat(), "issue_date": issued.isoformat(),
                "fetched_from": os.environ.get("RAINFALL_FEED_URL") or DEFAULT_URL, "fetched_at": now_manila(),
                "feed_request_no": meta.get("request_no")}
    return buf.getvalue(), settings


def build_from_feed(feed: dict, settings: dict | None = None) -> dict:
    data, s = to_template(feed)
    s = {**s, **{k: v for k, v in (settings or {}).items() if v not in (None, "")}}
    s.setdefault("data_credit", "Cordillera weather API")
    s.setdefault("source", "10-day forecast via Cordillera weather API "
                           f"({s['fetched_from']}); processed by DA-RFO-CAR AMIA")
    payload = rainfall_dekad.build(data, "rainfall_feed.xlsx", s)
    payload.setdefault("method", {})["fetched_from"] = s["fetched_from"]
    if payload.get("ok"):
        payload["method"]["fetched_at"] = s["fetched_at"]
    payload["feed_settings"] = s
    return payload


def run_once(settings: dict | None = None) -> dict:
    try:
        feed = fetch_json()
        payload = build_from_feed(feed, settings)
    except Exception as e:  # noqa: BLE001
        st = record({"last_attempt": now_manila(), "last_error": str(e)})
        return {"ok": False, "error": str(e), "state": st}
    st = record({"last_attempt": now_manila(), "last_fetched": now_manila(), "last_error": None,
                 "period": payload.get("period"), "issued": payload.get("issued")})
    return {"ok": payload["ok"], "payload": payload, "state": st}


def record(state: dict) -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    new = {**last_state(), **state}
    STATE_FILE.write_text(json.dumps(new, indent=1, default=str), encoding="utf-8")
    return new


def last_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    res = run_once()
    p = res.get("payload") or {}
    print(json.dumps({"ok": res["ok"], "error": res.get("error"), "period": p.get("period"),
                      "errors": (p.get("report") or {}).get("errors"),
                      "warnings": (p.get("report") or {}).get("warnings")}, indent=1, default=str))
    sys.exit(0 if res["ok"] else 1)
