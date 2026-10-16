import json
import time

import pytest
from fastapi.testclient import TestClient

from agriclimate import api
from agriclimate.envi import config

SAMPLE = config.ROOT / "data" / "sample"          # synthetic rainfall/irrigation demo files


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "WORKER_TOKEN", "t0ken")
    monkeypatch.setattr(api, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(api, "JOBS_DIR", tmp_path / "jobs")
    return TestClient(api.app, headers={"Authorization": "Bearer t0ken"})


def test_auth_required(client):
    r = TestClient(api.app).get("/reference/gazetteer")
    assert r.status_code == 401
    assert client.get("/reference/gazetteer").json()["municipalities"][0]["psgc"]


def test_template_download(client):
    r = client.get("/templates/rainfall_seasonal?period_start=2026-10&period_end=2027-03")
    assert r.status_code == 200 and "rainfall_seasonal_template.xlsx" in r.headers["content-disposition"]


def test_preview_drafts_recommendations(client):
    f = SAMPLE / "DEMO_rainfall_10day_2026-10-01.xlsx"
    settings = {"period_start": "2026-10-01", "period_end": "2026-10-10", "issue_date": "2026-09-30",
                "texts": {"title": "Custom title"}}
    r = client.post("/preview/rainfall_dekad", data={"settings": json.dumps(settings)},
                    files={"file": (f.name, f.read_bytes())})
    p = r.json()
    assert p["ok"] and p["texts"]["title"] == "Custom title"
    assert p["texts"]["recommendations"].startswith("Agricultural advisory")


def test_preview_envi_needs_three_files(client):
    p = client.post("/preview/envi", data={"settings": "{}"}).json()
    assert not p["ok"] and set(p["report"]) == {"drought", "damage", "crops"}


def test_preview_envi_with_hvc_and_livestock(client):
    from test_exposure import ROWS, da_form, summary_csv
    files = {k: (p.name, p.read_bytes()) for k, p in config.DEFAULT_FILES.items()}
    files["hvc"] = ("summary.csv", summary_csv(ROWS))
    files["livestock"] = ("livestock.xlsx", da_form())
    s = {"issue_date": "2026-10-01", "period_start": "2026-10", "period_end": "2027-03", "crops_as_of": "2026-09-30",
         "livestock_as_of": "2026-06-30", "livestock_share": 0.25}
    p = client.post("/preview/envi", data={"settings": json.dumps(s)}, files=files).json()
    assert p["ok"] and set(p["report"]) == {"drought", "damage", "crops", "hvc", "livestock"}
    assert p["exposure"]["hvc"] and p["exposure"]["livestock"] and p["method"]["crops_label"] == config.EXPOSURE_LABEL
    atok = p["layers"][0]["values"]["BENGUET|ATOK"]
    assert atok["crop_hvc"] == 12.0 and atok["livestock_raw"] > 0 and "livestock_norm" in atok


def test_drought_export_job_end_to_end(client):
    f = config.DEFAULT_FILES["drought"]
    s = {"issue_date": "2026-09-15", "period_start": "2026-10"}
    r = client.post("/jobs/drought", data={"settings": json.dumps(s)}, files={"file": (f.name, f.read_bytes())})
    job_id = r.json()["id"]
    for _ in range(900):
        j = client.get(f"/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert j["status"] == "done", j.get("error")
    layers = [x["layer"] for x in j["manifest"]["maps"]]                    # title page, 6 months, summary + recs pages
    assert layers[0] == "cover" and len([l for l in layers if l.startswith("m_")]) == 6 and j["manifest"]["labels_ok"]
    assert "summary" in layers and layers[-1].startswith("recommendations")
    z = client.get(f"/jobs/{job_id}/files/{j['manifest']['files']['zip']}")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    assert client.get(f"/jobs/{job_id}/files/../../etc/passwd").status_code == 404


def test_droughtcaster_unreachable(client, monkeypatch):
    """PAGASA DroughtCaster is the default source; when it cannot be reached the admin gets a clear error."""
    from agriclimate import droughtcaster

    def down(self, client_, name):
        raise RuntimeError(f"DroughtCaster: {name} could not be fetched (timeout)")

    monkeypatch.delenv("DROUGHTCASTER_URL", raising=False)
    monkeypatch.setattr(droughtcaster.PagasaDroughtCasterFetcher, "_province", down)
    monkeypatch.setattr(droughtcaster, "STATE_FILE", config.ROOT / "outputs" / "test_droughtcaster_state.json")
    r = client.post("/droughtcaster/fetch", json={}).json()
    assert r["ok"] is False and r["configured"] is True and "could not be fetched" in r["error"]
    t = client.post("/droughtcaster/table")
    assert t.status_code == 502 and "DroughtCaster" in t.json()["detail"]


def test_rainfall_feed_draft_and_export_from_payload(client, monkeypatch):
    from agriclimate import rainfall_feed
    feed = json.loads((config.ROOT / "tests" / "fixtures" / "rainfall_feed_2026-10-05.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(rainfall_feed, "fetch_json", lambda *a, **k: feed)
    monkeypatch.setattr(rainfall_feed, "STATE_FILE", config.ROOT / "outputs" / "test_feed_state.json")
    r = client.post("/feeds/rainfall_dekad/fetch", json={}).json()
    p = r["payload"]
    assert r["ok"] and p["period"]["start"] == "2026-10-05" and p["period"]["end"] == "2026-10-14"
    assert p["issued"] == "2026-10-05" and p["report"]["n_matched"] == 77 and not p["report"]["missing_areas"]
    assert p["texts"]["recommendations"].startswith("Agricultural advisory")
    # Bangued = sum of its 10 daily values
    bangued = sum(d["rainfall_total"] for d in feed["data"] if d["municity"] == "Bangued")
    assert p["layers"][0]["values"]["ABRA|BANGUED"]["total"] == round(bangued, 2)   # kept per area, no total map
    assert len(p["layers"]) == 10 and p["layers"][0]["label"] == "October 5"
    first_day = next(d["rainfall_total"] for d in feed["data"] if d["municity"] == "Bangued" and d["date"] == "10/5/2026")
    assert p["layers"][0]["values"]["ABRA|BANGUED"]["value"] == round(first_day, 2)
    s = {"texts": {"title": "Edited title"}}
    j = client.post("/jobs/rainfall_dekad", data={"settings": json.dumps(s), "payload": json.dumps(p)}).json()
    for _ in range(900):
        st = client.get(f"/jobs/{j['id']}?include_payload=true").json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert st["status"] == "done", st.get("error")
    assert st["payload"]["texts"]["title"] == "Edited title" and st["manifest"]["labels_ok"]


def test_rainfall_feed_rejects_empty(monkeypatch):
    from agriclimate import rainfall_feed
    with pytest.raises(ValueError):
        rainfall_feed.to_template({"metadata": {}, "data": []})
