"""
Testy Fáze 5 (Index věcnosti) — žádný model, žádná síť: jen počitatelné
veličiny z (mockovaných) otevřených dat a ze stažených stenozáznamů.
"""

import pytest

from index_vecnosti import (
    MIN_SUBSTANTIVE_CHARS,
    MIN_VYSTOUPENI_PRO_VECNOST,
    build_index,
    speech_metrics_by_person,
    submitted_bills_by_person,
)


class _FakeClient:
    def opendata_archive(self, name):
        return name


#: `tisky.unl` sloupce: 0 id_tisk,1 id_druh,2 id_stav,3 ct,4 cislo_za,
#: 5 id_navrh,6 id_org,7 id_org_obd,8 id_osoba (ověřeno proti psp.cz).
_TISKY_ROWS = [
    # Vládní návrh (id_druh=1) — nesmí se počítat, i když má id_osoba (ministr).
    ["1", "1", "1", "10", "0", "", "174", "174", "9999"],
    # Poslanecký návrh, jediný předkladatel (id_navrh=2), přímo v tisky.id_osoba.
    ["2", "2", "1", "11", "0", "2", "174", "174", "1001"],
    # Poslanecký návrh skupiny (id_navrh=3) — id_osoba v tisky.unl chybí,
    # skuteční předkladatelé jsou v predkladatel.unl.
    ["3", "2", "1", "12", "0", "3", "174", "174", ""],
    # Senátní návrh (id_navrh=4) — nepočítá se, i přes id_druh=2.
    ["4", "2", "1", "13", "0", "4", "174", "174", "1002"],
    # Poslanecký návrh z jiného volebního období — nepočítá se.
    ["5", "2", "1", "14", "0", "2", "170", "170", "1001"],
]

_PREDKLADATEL_ROWS = [
    ["3", "2001", "1", "0"],
    ["3", "2002", "2", "0"],
]


def _fake_read_unl(archive_path, member):
    if member == "tisky.unl":
        return _TISKY_ROWS
    if member == "predkladatel.unl":
        return _PREDKLADATEL_ROWS
    raise AssertionError("neočekávaný člen archivu: {}".format(member))


def test_submitted_bills_excludes_government_and_senate_bills(monkeypatch):
    monkeypatch.setattr("index_vecnosti.read_unl", _fake_read_unl)
    counts = submitted_bills_by_person(_FakeClient(), id_organ="174")
    # tisk 1 (vládní) a tisk 4 (senátní) se nesmí objevit vůbec.
    assert "9999" not in counts
    assert "1002" not in counts


def test_submitted_bills_counts_single_submitter_from_tisky_unl(monkeypatch):
    monkeypatch.setattr("index_vecnosti.read_unl", _fake_read_unl)
    counts = submitted_bills_by_person(_FakeClient(), id_organ="174")
    assert counts["1001"] == 1   # jen tisk 2 — tisk 5 patří jinému období


def test_submitted_bills_counts_group_submitters_from_predkladatel_unl(monkeypatch):
    monkeypatch.setattr("index_vecnosti.read_unl", _fake_read_unl)
    counts = submitted_bills_by_person(_FakeClient(), id_organ="174")
    assert counts["2001"] == 1   # jen v predkladatel.unl, ne v tisky.id_osoba
    assert counts["2002"] == 1


def test_submitted_bills_scoped_to_requested_organ(monkeypatch):
    monkeypatch.setattr("index_vecnosti.read_unl", _fake_read_unl)
    counts = submitted_bills_by_person(_FakeClient(), id_organ="170")
    assert counts == {"1001": 1}   # jen tisk 5, z období 170


# --------------------------------------------------------- vzorek vystoupení --

def _debate(messages):
    return {"messages": messages}


def _msg(id_osoba, delka, is_chair=False):
    return {"cleanText": "x" * delka, "source": {"idOsoba": id_osoba, "isChair": is_chair}}


def test_speech_metrics_excludes_chair_messages():
    debates = [_debate([_msg("1", 300, is_chair=True)] + [_msg("1", 300)] * MIN_VYSTOUPENI_PRO_VECNOST)]
    out = speech_metrics_by_person(debates)
    assert out["1"]["vystoupeniVeVzorku"] == MIN_VYSTOUPENI_PRO_VECNOST


def test_speech_metrics_below_minimum_sample_not_published():
    debates = [_debate([_msg("1", 300)] * (MIN_VYSTOUPENI_PRO_VECNOST - 1))]
    out = speech_metrics_by_person(debates)
    assert "1" not in out


def test_speech_metrics_computes_median_and_short_share():
    delky = [50, 100, 300, 500, 900]   # 2 pod MIN_SUBSTANTIVE_CHARS (200)
    assert len(delky) >= MIN_VYSTOUPENI_PRO_VECNOST
    debates = [_debate([_msg("1", d) for d in delky])]
    out = speech_metrics_by_person(debates)
    assert out["1"]["medianDelkyZnaku"] == 300.0
    assert out["1"]["podilKratkychVystoupeni"] == pytest.approx(2 / 5)
    assert all(d < MIN_SUBSTANTIVE_CHARS for d in (50, 100))


def test_speech_metrics_median_of_even_sample_averages_middle_two():
    delky = [100, 200, 300, 400, 500, 600]
    debates = [_debate([_msg("1", d) for d in delky])]
    out = speech_metrics_by_person(debates)
    assert out["1"]["medianDelkyZnaku"] == 350.0


# ------------------------------------------------------------------ build_index --

def test_build_index_omits_person_with_nothing_to_report(monkeypatch):
    monkeypatch.setattr("index_vecnosti.read_unl", _fake_read_unl)
    out = build_index(_FakeClient(), debates=[], politician_ids=["7777"], id_organ="174")
    assert "7777" not in out


def test_build_index_combines_both_components(monkeypatch):
    monkeypatch.setattr("index_vecnosti.read_unl", _fake_read_unl)
    debates = [_debate([_msg("1001", 300)] * MIN_VYSTOUPENI_PRO_VECNOST)]
    out = build_index(_FakeClient(), debates=debates, politician_ids=["1001"], id_organ="174")
    assert out["1001"]["poslaneckeNavrhyZakonu"] == 1
    assert out["1001"]["vzorekVystoupeni"]["vystoupeniVeVzorku"] == MIN_VYSTOUPENI_PRO_VECNOST


def test_build_index_keeps_person_with_only_bills_and_no_speech_sample(monkeypatch):
    monkeypatch.setattr("index_vecnosti.read_unl", _fake_read_unl)
    out = build_index(_FakeClient(), debates=[], politician_ids=["1001"], id_organ="174")
    assert out["1001"]["poslaneckeNavrhyZakonu"] == 1
    assert out["1001"]["vzorekVystoupeni"] is None
