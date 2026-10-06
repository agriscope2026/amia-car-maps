"""PAGASA DroughtCaster fetcher – behind an interface, with retries, logging and a "last fetched" record.

The official machine-readable access method for DroughtCaster has NOT been confirmed (see
docs/ARCHITECTURE.md §12). Until it is, the only built-in fetcher downloads a table in the manual
template format (``ID, PROVINCE, <months>`` with PAGASA categories) from a URL the admin configures
(``DROUGHTCASTER_URL``) – e.g. a file DA-RFO-CAR receives from PAGASA under its terms of use. Add a new
``Fetcher`` subclass when PAGASA confirms an API/GeoJSON/raster endpoint. The manual upload always works.

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


def get_fetcher() -> Fetcher:
    return TemplateUrlFetcher()


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
