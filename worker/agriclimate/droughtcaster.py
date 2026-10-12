"""PAGASA DroughtCaster fetcher – behind an interface, with retries, logging and a "last fetched" record.

Default source: the PAGASA DroughtCaster site (https://droughtcaster.pagasa.dost.gov.ph/). Its page loads each
province's assessment and outlook as JSON from ``proxy.php?endpoint=drought&location=<province>``; the six CAR
provinces are read from there and written as the manual drought template (``ID, PROVINCE, <months>`` with PAGASA
categories). This is the site's own data endpoint, not a documented public API, so it may change without notice:
the manual upload always works. ``DROUGHTCASTER_URL`` switches to a template file at a URL instead (e.g. a file
DA-RFO-CAR receives from PAGASA).

Run on a schedule (cron / Cloud Scheduler):  python -m agriclimate.droughtcaster
Fetched data is never published automatically – it becomes a draft that an admin must approve.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .exports import now_manila

log = logging.getLogger("agriclimate.droughtcaster")
STATE_FILE = Path(os.environ.get("OUTPUT_DIR", Path(__file__).resolve().parents[1] / "outputs")) / \
    "droughtcaster_state.json"


class NotConfigured(RuntimeError):
    pass


@dataclass
class FetchResult:
    content: bytes
    filename: str
    source_url: str
    fetched_at: str


class Fetcher:
    name = "base"

    def fetch(self) -> FetchResult:  # pragma: no cover - interface
        raise NotImplementedError


class TemplateUrlFetcher(Fetcher):
    """Downloads a CSV/XLSX in the manual drought template format from ``DROUGHTCASTER_URL``."""
    name = "template-url"

    def __init__(self, url: str | None = None, retries: int = 3, backoff: float = 2.0, timeout: float = 30.0):
        self.url = url or os.environ.get("DROUGHTCASTER_URL")
        self.retries, self.backoff, self.timeout = retries, backoff, timeout

    def fetch(self) -> FetchResult:
        if not self.url:
            raise NotConfigured("No DroughtCaster source is configured (DROUGHTCASTER_URL). Upload the drought "
                                "template manually instead.")
        import httpx
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                r = httpx.get(self.url, timeout=self.timeout, follow_redirects=True,
                              headers={"User-Agent": "DA-RFO-CAR AgriClimate Portal"})
                r.raise_for_status()
                name = self.url.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or "droughtcaster.csv"
                if not name.lower().endswith((".csv", ".xlsx")):
                    name += ".csv"
                log.info("fetched %s (%d bytes) on attempt %d", self.url, len(r.content), attempt)
                return FetchResult(r.content, name, self.url, now_manila())
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("fetch attempt %d/%d failed: %s", attempt, self.retries, e)
                if attempt < self.retries:
                    time.sleep(self.backoff ** attempt)
        raise RuntimeError(f"DroughtCaster fetch failed after {self.retries} attempts: {last}")


PAGASA_BASE = "https://droughtcaster.pagasa.dost.gov.ph/proxy.php"
CAR_PROVINCES = ["Abra", "Apayao", "Benguet", "Ifugao", "Kalinga", "Mountain Province"]


class PagasaDroughtCasterFetcher(Fetcher):
    """PAGASA DroughtCaster (https://droughtcaster.pagasa.dost.gov.ph/): the outlook of each CAR province from the
    site's JSON endpoint (``proxy.php?endpoint=drought&location=<province>``), written as the manual drought
    template (``ID, PROVINCE, <month names>``) so it goes through the same validation as an upload.

    Each province returns ``[{name, issuedAt, data: [{date: 'YYYY-MM', type: 'assessment'|'outlook', status}]}]``;
    only the ``outlook`` months are used (the assessment month is the observed situation)."""
    name = "pagasa-droughtcaster"

    def __init__(self, base: str | None = None, retries: int = 3, backoff: float = 2.0, timeout: float = 60.0):
        self.base = base or os.environ.get("DROUGHTCASTER_API", PAGASA_BASE)
        self.retries, self.backoff, self.timeout = retries, backoff, timeout
        self.meta: dict = {}

    def _province(self, client, name: str) -> dict:
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                r = client.get(self.base, params={"endpoint": "drought", "location": name})
                r.raise_for_status()
                rows = r.json()
                row = next((x for x in rows if str(x.get("name", "")).lower() == name.lower()), rows[0] if rows else None)
                if not row or not row.get("data"):
                    raise ValueError(f"no data for {name}")
                return row
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("DroughtCaster %s attempt %d/%d failed: %s", name, attempt, self.retries, e)
                if attempt < self.retries:
                    time.sleep(self.backoff ** attempt)
        raise RuntimeError(f"DroughtCaster: {name} could not be fetched ({last})")

    def fetch(self) -> FetchResult:
        import csv
        import io

        import httpx
        with httpx.Client(timeout=self.timeout, follow_redirects=True,
                          headers={"User-Agent": "DA-RFO-CAR AgriClimate Portal",
                                   "Referer": "https://droughtcaster.pagasa.dost.gov.ph/"}) as client:
            rows = {p: self._province(client, p) for p in CAR_PROVINCES}
        months = sorted({d["date"] for r in rows.values() for d in r["data"] if d.get("type") == "outlook"})
        if not months:
            raise RuntimeError("DroughtCaster returned no outlook months for CAR.")
        names = [pd_month_name(m) for m in months]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ID", "PROVINCE", *names])
        for i, (p, r) in enumerate(rows.items(), start=1):
            by = {d["date"]: d.get("status", "") for d in r["data"] if d.get("type") == "outlook"}
            w.writerow([i, p, *[by.get(m, "") for m in months]])
        issued = max((str(r.get("issuedAt", ""))[:10] for r in rows.values()), default="")
        assessment = {p: next((d["status"] for d in r["data"] if d.get("type") == "assessment"), None)
                      for p, r in rows.items()}
        self.meta = {"issued": issued, "period_start": months[0], "period_end": months[-1], "months": months,
                     "assessment": assessment}
        return FetchResult(buf.getvalue().encode("utf-8"), f"droughtcaster_CAR_{issued or months[0]}.csv",
                           "https://droughtcaster.pagasa.dost.gov.ph/", now_manila())


def pd_month_name(ym: str) -> str:
    """'2026-10' → 'October' (the drought template's month columns)."""
    import calendar
    return calendar.month_name[int(ym[5:7])]


def get_fetcher() -> Fetcher:
    """PAGASA DroughtCaster by default; ``DROUGHTCASTER_URL`` switches to a template file at that URL."""
    return TemplateUrlFetcher() if os.environ.get("DROUGHTCASTER_URL") else PagasaDroughtCasterFetcher()


def fetch_table() -> dict:
    """The CAR outlook as a drought-template CSV plus its dates, for the upload forms (ENVI and drought)."""
    f = get_fetcher()
    res = f.fetch()
    meta = getattr(f, "meta", {})
    record({"last_attempt": res.fetched_at, "last_fetched": res.fetched_at, "last_error": None,
            "source": res.source_url, "fetcher": f.name})
    return {"filename": res.filename, "csv": res.content.decode("utf-8"), "source": res.source_url,
            "fetched_at": res.fetched_at, **meta}


def record(state: dict) -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    prev = last_state()
    new = {**prev, **state}
    STATE_FILE.write_text(json.dumps(new, indent=1), encoding="utf-8")
    return new


def last_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run_once(settings: dict) -> dict:
    """Fetch and build a draft payload (CAR only). Returns {ok, payload|error, state}."""
    from .products import drought
    fetcher = get_fetcher()
    try:
        res = fetcher.fetch()
        meta = getattr(fetcher, "meta", {})
        # dates from DroughtCaster unless given: issued date and the first outlook month
        settings = {"issue_date": meta.get("issued"), "period_start": meta.get("period_start"),
                    **{k: v for k, v in settings.items() if v}}
    except NotConfigured as e:
        return {"ok": False, "error": str(e), "configured": False, "state": last_state()}
    except Exception as e:  # noqa: BLE001
        st = record({"last_attempt": now_manila(), "last_error": str(e)})
        return {"ok": False, "error": str(e), "configured": True, "state": st}
    payload = drought.build(res.content, res.filename, {**settings, "fetched_from": res.source_url,
                                                        "fetched_at": res.fetched_at})
    st = record({"last_attempt": res.fetched_at, "last_fetched": res.fetched_at, "last_error": None,
                 "source": res.source_url, "fetcher": fetcher.name})
    return {"ok": payload["ok"], "payload": payload, "state": st, "raw_filename": res.filename}


if __name__ == "__main__":
    import sys
    from datetime import date
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    today = date.today()
    out = run_once({"issue_date": today.isoformat(), "period_start": f"{today:%Y-%m}"})
    print(json.dumps({k: v for k, v in out.items() if k != "payload"}, indent=1))
    sys.exit(0 if out["ok"] else 1)
