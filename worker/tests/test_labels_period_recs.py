import itertools

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

from agriclimate.envi import config, index, io_loader, mapping, recommendations  # noqa: E402
from agriclimate.envi.labels import place_labels  # noqa: E402


# the reference results were computed with equal weights
EQUAL = {**config.DEFAULT_SETTINGS, "weights": {"hazard": 1 / 3, "damage": 1 / 3, "crops": 1 / 3}}


@pytest.fixture(scope="module")
def computed():
    gaz = io_loader.load_gazetteer()
    res = io_loader.load_all({k: (p, p.name) for k, p in config.DEFAULT_FILES.items()}, gaz)
    df, meta = index.compute_envi(res, gaz, EQUAL)
    return df, meta, res


def test_labels_never_overlap_and_all_names_present(computed):
    df, meta, _ = computed
    areas, prov = mapping.join_results(df, meta["level"])
    fig = plt.figure(figsize=(7.4, 11.1), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    report = mapping._draw_map(ax, areas, prov)
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    boxes = [(t.get_text(), t.get_window_extent(r)) for t in ax.texts]
    names = {t for t, _ in boxes}
    assert set(areas.MunName2) <= names and set(prov.Pro_Name) <= names
    assert report["missing"] == []
    overlaps = [(a, b) for (a, ba), (b, bb) in itertools.combinations(boxes, 2)
                if ba.x0 < bb.x1 - 1 and bb.x0 < ba.x1 - 1 and ba.y0 < bb.y1 - 1 and bb.y0 < ba.y1 - 1]
    plt.close(fig)
    assert overlaps == []


def test_period_labels():
    lab = config.period_labels({"reporting_month": "2027-01", "period_start": "2027-02", "period_end": "2027-07",
                                "crops_as_of": "2027-01-15"})
    assert lab["period"] == "February 2027 – July 2027"
    assert lab["issued"] == "January 2027"
    assert lab["crops_as_of"] == "January 15, 2027"
    assert lab["subtitle"] == "Outlook: February 2027 – July 2027 (as of January 2027)"


def test_period_flows_into_map_and_presentation(computed):
    from agriclimate.envi import presentation
    gaz = io_loader.load_gazetteer()
    _, _, res = computed
    s = {**config.DEFAULT_SETTINGS, "reporting_month": "2027-01", "period_start": "2027-02", "period_end": "2027-07"}
    _, meta = index.compute_envi(res, gaz, s)
    assert mapping.texts(meta)["period"] == "Outlook: February 2027 – July 2027"
    c = presentation._content(meta)
    assert "February 2027 – July 2027" in c["footnote"] and "Issued: January 2027" in c["footnote"]
    assert "2019, 2024, 2026" in c["sources"]


def test_recommendations_draft(computed):
    df, meta, res = computed
    txt = recommendations.generate(df, meta, res, EQUAL)
    assert "Abra, Apayao, Ifugao, Kalinga and Mountain Province: dry spell from November 2026, " \
           "drought from January 2027 (3 months)." in txt
    assert "Benguet: dry spell from December 2026, drought from February 2027 (2 months)." in txt
    assert "Tabuk City (Very High" in txt
    assert "44,772 ha" in txt
    assert txt.count("\n") > 8


def test_presentation_with_recommendations(computed, tmp_path):
    from PIL import Image

    from agriclimate.envi import presentation
    df, meta, res = computed
    txt = recommendations.generate(df, meta, res, EQUAL)
    map_png = tmp_path / "map.png"
    Image.new("RGBA", (600, 1000), (0, 120, 0, 255)).save(map_png)
    out = presentation.build_all(meta, map_png, tmp_path, txt)
    assert Image.open(out["slide"]).size == (1920, 1080)
    assert Image.open(out["poster"]).size == (2480, 3508)
