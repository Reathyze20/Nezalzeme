"""
Testy `psp/opendata_hlasovani.py` — spoj projev -> bod pořadu -> hlasování.

Fixtury jsou malé syntetické ZIP archivy ve stejném formátu jako skutečné
dumpy PSP ČR (windows-1250, `|`-oddělené UNL), ne stažená data — testy běží
bez sítě. Sloupcové indexy zrcadlí ověření nad reálným korpusem (schůze 5,
bod 51 = žádost o vyslovení důvěry vládě, 28. 8. 2026).
"""

import io
import os
import zipfile

import pytest

from psp.opendata_hlasovani import (
    VOTE_CODE_MAP,
    bod_info,
    find_id_bod,
    hlas_poslance_kod,
    is_omluven,
    parse_bod_schuze,
    parse_hlas_poslance,
    parse_hlasovani,
    parse_omluvy,
    parse_rec,
    parse_schuze,
    parse_steno_turns,
    parse_zmatecne,
    populate_voting_tables,
)


def _make_unl_zip(path: str, members: dict) -> None:
    """`members`: `{jméno_souboru: [řádky_jako_seznamy_sloupců]}`."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, rows in members.items():
            body = "\n".join("|".join(cols) for cols in rows)
            zf.writestr(name, body.encode("windows-1250"))


@pytest.fixture
def hl_zip(tmp_path):
    path = str(tmp_path / "hl-2025ps.zip")
    _make_unl_zip(path, {
        "hl2025s.unl": [
            # id_hlasovani|organ|schuze|cislo|bod|datum|cas|pro|proti|zdrzel|nehlasoval|prihl|kvorum|druh|vysledek|nazev|nazev_kratky
            ["86479", "174", "5", "39", "51", "15.01.2026", "18:13", "122", "2", "51", "14", "194", "98", "N", "A", "Vysloveni duvery vlade", ""],
            ["86480", "174", "5", "40", "51", "15.01.2026", "20:57", "108", "91", "0", "1", "194", "98", "N", "A", "Vysloveni duvery vlade", ""],
            # jiné volební období — musí se odfiltrovat
            ["99999", "170", "1", "1", "1", "01.01.2020", "10:00", "1", "1", "1", "1", "10", "5", "N", "A", "Jiné období", ""],
        ],
        "hl2025h1.unl": [
            ["2103", "86479", "A"],
            ["2103", "86480", "B"],
            ["1964", "86479", "K"],
            ["1964", "86480", "@"],
        ],
        "zmatecne.unl": [["86480"]],
        "omluvy.unl": [
            ["174", "2103", "15.01.2026", "09:00", "23:59"],
            ["173", "9999", "15.01.2026", "09:00", "23:59"],  # jiné období
        ],
    })
    return path


@pytest.fixture
def schuze_zip(tmp_path):
    path = str(tmp_path / "schuze.zip")
    _make_unl_zip(path, {
        "schuze.unl": [
            ["843", "174", "5", "2026-01-15 09", "", "2026-01-15 09", "1"],
            ["999", "170", "1", "2020-01-01 09", "", "2020-01-01 09", "1"],  # jiné období
        ],
        "bod_schuze.unl": [
            # id_bod|id_schuze|id_tisk|id_typ|bod|nazev|tisk_ref|...(9 dalších sloupců)
            ["58108", "843", "", "1", "51", "Žádost vlády o vyslovení důvěry", "", "", "0", "", "", "", "", "", ""],
        ],
    })
    return path


@pytest.fixture
def steno_zip(tmp_path):
    path = str(tmp_path / "steno.zip")
    _make_unl_zip(path, {
        "steno.unl": [
            # id_steno|organ|schuze|turn|datum|jednaci_den|od_min|do_min
            ["25000", "174", "5", "141", "2026-01-15", "3", "600", "610"],
            ["25001", "170", "1", "1", "2020-01-01", "1", "0", "10"],  # jiné období
        ],
        "rec.unl": [
            # id_steno|id_osoba|anchor_n|id_bod|druh
            ["25000", "6987", "6", "58108", "5"],
            ["25000", "6473", "1", "0", "4"],  # bod=0 -> bez konkrétního bodu, musí se vynechat
        ],
    })
    return path


def test_parse_schuze_filters_by_organ(schuze_zip):
    out = parse_schuze(schuze_zip, "174")
    assert out == {"843": ("174", 5)}


def test_parse_bod_schuze_maps_tisk_and_bod_number(schuze_zip):
    schuze = parse_schuze(schuze_zip, "174")
    rows = parse_bod_schuze(schuze_zip, set(schuze.keys()))
    assert len(rows) == 1
    assert rows[0]["id_bod"] == "58108"
    assert rows[0]["id_tisk"] is None  # prázdný řetězec -> None
    assert rows[0]["bod"] == 51


def test_parse_steno_turns_filters_by_organ(steno_zip):
    out = parse_steno_turns(steno_zip, "174")
    assert out == {"25000": ("174", 5, 141)}
    assert "25001" not in out  # jiné volební období


def test_parse_rec_skips_zero_bod_and_joins_steno(steno_zip):
    steno_index = parse_steno_turns(steno_zip, "174")
    rows = parse_rec(steno_zip, steno_index)
    # jen jeden řádek zbyde — druhý má id_bod="0" (string "0" je v Pythonu
    # truthy, filtr proto musí porovnávat na "0" explicitně, ne jen `not id_bod`)
    assert len(rows) == 1
    assert rows[0]["id_osoba"] == "6987"
    assert rows[0]["id_bod"] == "58108"
    assert rows[0]["anchor_n"] == 6
    assert rows[0]["turn"] == 141


def test_parse_hlasovani_filters_by_organ_and_maps_columns(hl_zip):
    rows = parse_hlasovani(hl_zip, "hl2025s.unl", "174")
    assert len(rows) == 2
    r = rows[0]
    assert r["id_hlasovani"] == "86479"
    assert r["bod"] == 51
    assert r["pro"] == 122 and r["proti"] == 2 and r["zdrzel"] == 51 and r["nehlasoval"] == 14
    assert r["vysledek"] == "A"
    assert r["url"] == "https://www.psp.cz/sqw/hlasy.sqw?G=86479"


def test_parse_hlas_poslance_filters_by_hlasovani_id(hl_zip):
    rows = parse_hlas_poslance(hl_zip, "hl2025h1.unl", {"86479"})
    assert len(rows) == 2
    assert ("86479", "2103", "A") in rows
    assert ("86479", "1964", "K") in rows


def test_vote_code_map_matches_html_flags_semantics():
    # Křížově ověřeno proti HTML `hlasy.sqw?G=` na 200 hlasech, 0 neshod
    # (viz plán Fáze 1) — kód "K" je záměrně nejednoznačný.
    assert VOTE_CODE_MAP["A"] == "PRO"
    assert VOTE_CODE_MAP["B"] == "PROTI"
    assert VOTE_CODE_MAP["K"] == "ZDRZEL_SE"
    assert VOTE_CODE_MAP["@"] == "NEPRIHLASEN"


def test_parse_zmatecne_filters_by_known_ids(hl_zip):
    out = parse_zmatecne(hl_zip, "zmatecne.unl", {"86479", "86480"})
    assert out == {"86480"}


def test_parse_omluvy_filters_by_organ(hl_zip):
    rows = parse_omluvy(hl_zip, "omluvy.unl", "174")
    assert rows == [("174", "2103", "15.01.2026", "09:00", "23:59")]


class _FakeClient:
    """Nahrazuje `PspClient.opendata_archive` fixturami bez sítě."""

    def __init__(self, paths: dict):
        self._paths = paths

    def opendata_archive(self, name: str) -> str:
        return self._paths[name]


def test_populate_voting_tables_end_to_end(engine_db, hl_zip, schuze_zip, steno_zip):
    client = _FakeClient({
        "hl-2025ps.zip": hl_zip,
        "schuze.zip": schuze_zip,
        "steno.zip": steno_zip,
    })
    stats = populate_voting_tables(engine_db, client, term_organ_id=174)
    assert stats["schuze"] == 1
    assert stats["bod_schuze"] == 1
    assert stats["rec_bod"] == 1
    assert stats["hlasovani"] == 2
    assert stats["hlas_poslance"] == 4
    assert stats["zmatecne"] == 1
    assert stats["omluva"] == 1

    # Projev (turn=141, kotva #r6, id_osoba=6987) -> id_bod -> bod 51
    id_bod = find_id_bod(engine_db, "174", 5, 141, 6, "6987")
    assert id_bod == "58108"
    info = bod_info(engine_db, id_bod)
    assert info["bod"] == 51
    assert info["id_tisk"] is None

    # Zmatečné hlasování (86480) se z výchozího výběru vynechá
    from psp.opendata_hlasovani import votes_for_bod
    votes = votes_for_bod(engine_db, "174", 5, 51)
    assert [v["id_hlasovani"] for v in votes] == ["86479"]
    votes_all = votes_for_bod(engine_db, "174", 5, 51, include_zmatecne=True)
    assert len(votes_all) == 2

    assert hlas_poslance_kod(engine_db, "86479", "2103") == "A"
    assert hlas_poslance_kod(engine_db, "86479", "0000") is None

    # Omluva 15.1.2026 9:00-23:59 pokrývá hlasování v 18:13 (86479)
    assert is_omluven(engine_db, "174", "2103", "15.01.2026", "18:13") is True
    assert is_omluven(engine_db, "174", "9999", "15.01.2026", "18:13") is False


def test_populate_voting_tables_is_idempotent(engine_db, hl_zip, schuze_zip, steno_zip):
    """Opakované volání pro stejné `id_organ` nesmí duplikovat řádky."""
    client = _FakeClient({
        "hl-2025ps.zip": hl_zip,
        "schuze.zip": schuze_zip,
        "steno.zip": steno_zip,
    })
    populate_voting_tables(engine_db, client, term_organ_id=174)
    stats2 = populate_voting_tables(engine_db, client, term_organ_id=174)
    assert stats2["hlasovani"] == 2
    n = engine_db.execute("SELECT COUNT(*) AS n FROM hlasovani").fetchone()["n"]
    assert n == 2
