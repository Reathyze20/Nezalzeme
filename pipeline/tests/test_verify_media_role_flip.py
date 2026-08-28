"""
Testy důkazní brány Fáze 6b (`export_web.verify_media_role_flip`).

Dvojí podmínka na export: `schvaleno` (ruční, `promote_media_lead.py`) A
`overeno` (strojové, přepočtené znovu při každém exportu, stejný vzorec jako
`verify_slovo_cin`). Chybí-li jedna z nich, položka se nevyexportuje.
"""

import pytest

from db import open_engine_db
from export_web import load_media_role_flip, verify_media_role_flip
from media_role_flip import approve_lead, build_record, store_record


class _FakeRegistry:
    def __init__(self, mapping):
        self._mapping = mapping

    def deputy_id(self, id_osoba):
        return self._mapping.get(str(id_osoba))


@pytest.fixture
def engine_db():
    return open_engine_db(":memory:")


def _seed_hlasovani(conn, id_hlasovani="h1", kod="A", is_zmatecne=0):
    conn.execute(
        "INSERT OR REPLACE INTO hlasovani (id_hlasovani, id_organ, schuze, cislo, bod, datum, cas,"
        " pro, proti, zdrzel, nehlasoval, prihlaseno, kvorum, vysledek, nazev, is_zmatecne, url)"
        " VALUES (?, '174', 1, 1, 1, '10.12.2025', '10:00', 1, 1, 0, 0, 2, 1, 'A', 'test', ?, 'u')",
        (id_hlasovani, is_zmatecne),
    )
    conn.execute(
        "INSERT OR REPLACE INTO hlas_poslance (id_hlasovani, id_poslanec, kod) VALUES (?, '2103', ?)",
        (id_hlasovani, kod),
    )
    conn.commit()


class _FakeTiskInfo:
    cislo = "1"
    cely_nazev = "Test tisk"
    url = "https://example/tisk"


def _record(record_id="mrf-1", id_osoba="6992", hlas="PRO", postoj="PRO", id_hlasovani="h1"):
    return build_record(
        id_osoba, "Jan Novák", "citace",
        {"url": "https://example/clanek", "medium": "example.cz", "datumClanku": "2025-11-10"},
        "OPPOSITION_DEPUTY", _FakeTiskInfo(),
        {"idHlasovani": id_hlasovani, "url": "u", "cisloHlasovani": 1, "schuze": 1,
         "vysledekSlovy": "schválen", "prijat": True, "historieUrl": "u"},
        {"postoj": postoj, "oduvodneni": "d"},
        {"hlas": hlas, "omluven": False, "klub": "ANO2011"},
        "COALITION_DEPUTY", None,
    ) | {"id": record_id}


def _store(conn, **kwargs):
    record = _record(**kwargs)
    store_record(conn, record, "m", parovani_plati=True, rozpor_mizi=False)
    return record


def test_gate_rejects_unapproved_lead_even_if_data_matches(engine_db):
    _seed_hlasovani(engine_db, kod="A")
    _store(engine_db, hlas="PRO")
    out = verify_media_role_flip(engine_db, _FakeRegistry({"6992": "2103"}))
    assert out["ok"] == 0
    assert "nebylo schváleno" in out["zamitnuto"][0]
    assert load_media_role_flip(engine_db) == []


def test_gate_accepts_approved_lead_matching_open_data(engine_db):
    _seed_hlasovani(engine_db, kod="A")
    record = _store(engine_db, hlas="PRO")
    approve_lead(engine_db, record["id"])
    out = verify_media_role_flip(engine_db, _FakeRegistry({"6992": "2103"}))
    assert out["ok"] == 1 and out["zamitnuto"] == []
    exported = load_media_role_flip(engine_db)
    assert len(exported) == 1
    assert exported[0]["id"] == record["id"]
    assert "schvalenoAt" in exported[0]


def test_gate_rejects_approved_lead_when_vote_contradicts_open_data(engine_db):
    _seed_hlasovani(engine_db, kod="B")  # otevřená data: PROTI
    record = _store(engine_db, hlas="PRO")  # uloženo: PRO
    approve_lead(engine_db, record["id"])
    out = verify_media_role_flip(engine_db, _FakeRegistry({"6992": "2103"}))
    assert out["ok"] == 0
    assert "hlas nesouhlasí" in out["zamitnuto"][0]
    assert load_media_role_flip(engine_db) == []


def test_gate_rejects_approved_lead_on_annulled_vote(engine_db):
    _seed_hlasovani(engine_db, kod="A", is_zmatecne=1)
    record = _store(engine_db, hlas="PRO")
    approve_lead(engine_db, record["id"])
    out = verify_media_role_flip(engine_db, _FakeRegistry({"6992": "2103"}))
    assert out["ok"] == 0
    assert "zmatečné" in out["zamitnuto"][0]


def test_gate_rejects_approved_lead_without_mandate(engine_db):
    _seed_hlasovani(engine_db, kod="A")
    record = _store(engine_db, hlas="PRO")
    approve_lead(engine_db, record["id"])
    out = verify_media_role_flip(engine_db, _FakeRegistry({}))
    assert out["ok"] == 0
    assert "mandát" in out["zamitnuto"][0]
