"""
Testy Fáze 4 (Programová věrnost) — parsing prohlášení, atomizace závazků,
spárování s tiskem a jeho nezávislý přezkum.

Bez sítě a bez modelu: backend i HTTP klient jsou dvojníci.
"""

import json

import pytest

from programova_vernost import (
    KAPITOLY_ID,
    challenge_pairing,
    extract_zavazky,
    find_tisk_candidate,
    kluby_tally_for_ballot,
    latest_final_vote,
    parse_kapitoly,
)


class _FakeBackend:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call(self, role, system_prompt, user_payload, model, ck=None):
        self.calls.append({"role": role, "ck": ck, "payload": user_payload})
        return self.response


def _synthetic_prohlaseni_html():
    """18 kapitol se skutečnými `id` kotvami z `KAPITOLY_ID`, minimálním obsahem."""
    chapters = "".join(
        '<h2><a id="{i}" name="{i}"></a>{n}. Kapitola {i}</h2>'
        '<h4>Podnadpis {i}</h4>'
        '<p>Obecná proklamace v kapitole {i}. '
        'Slíbíme konkrétní opatření {i} do konce roku.</p>'.format(i=kid, n=index + 1)
        for index, kid in enumerate(KAPITOLY_ID)
    )
    return "<html><body><article class=\"article\">{}</article></body></html>".format(chapters)


# ------------------------------------------------------------- parsování ----

def test_parse_kapitoly_finds_all_eighteen_in_order():
    kapitoly = parse_kapitoly(_synthetic_prohlaseni_html())
    assert [k["id"] for k in kapitoly] == KAPITOLY_ID
    assert [k["poradi"] for k in kapitoly] == list(range(1, 19))


def test_parse_kapitoly_text_contains_promise_sentence():
    kapitoly = parse_kapitoly(_synthetic_prohlaseni_html())
    prvni = kapitoly[0]
    assert "Slíbíme konkrétní opatření {} do konce roku.".format(KAPITOLY_ID[0]) in prvni["text"]
    assert prvni["nazev"] == "Kapitola {}".format(KAPITOLY_ID[0])


def test_parse_kapitoly_raises_when_structure_changed():
    # Chybí poslední kapitola -> nesmí potichu vrátit jen 17, musí selhat nahlas.
    html = _synthetic_prohlaseni_html().replace(
        '<h2><a id="{i}" name="{i}"></a>18. Kapitola {i}</h2>'.format(i=KAPITOLY_ID[-1]), ""
    )
    with pytest.raises(ValueError):
        parse_kapitoly(html)


def test_parse_kapitoly_raises_without_article_wrapper():
    with pytest.raises(ValueError):
        parse_kapitoly("<html><body>žádný article tag</body></html>")


# --------------------------------------------------------------- závazky ----

def _kapitola():
    return {"id": KAPITOLY_ID[0], "poradi": 1, "nazev": "Finance",
            "text": "Obecná věta. Snížíme daň z příjmu fyzických osob o dva procentní body."}


def test_extract_zavazky_keeps_verbatim_quote():
    backend = _FakeBackend(json.dumps(
        [{"citace": "Snížíme daň z příjmu fyzických osob o dva procentní body."}]
    ))
    out = extract_zavazky(backend, _kapitola(), "m")
    assert len(out) == 1
    assert out[0]["charStart"] == _kapitola()["text"].index(out[0]["citace"])
    assert out[0]["kapitolaId"] == KAPITOLY_ID[0]


def test_extract_zavazky_drops_non_verbatim_quote():
    # Model si citaci mírně přeformuloval -> není podřetězec -> zahodit.
    backend = _FakeBackend(json.dumps([{"citace": "Snížíme daně o dva procentní body."}]))
    out = extract_zavazky(backend, _kapitola(), "m")
    assert out == []


def test_extract_zavazky_id_is_deterministic_and_scoped_to_chapter():
    citace = "Snížíme daň z příjmu fyzických osob o dva procentní body."
    backend = _FakeBackend(json.dumps([{"citace": citace}]))
    first = extract_zavazky(backend, _kapitola(), "m")[0]
    second = extract_zavazky(backend, _kapitola(), "m")[0]
    assert first["id"] == second["id"]

    jina_kapitola = dict(_kapitola(), id=KAPITOLY_ID[1])
    treti = extract_zavazky(backend, jina_kapitola, "m")[0]
    assert treti["id"] != first["id"]


def test_extract_zavazky_ignores_malformed_response():
    backend = _FakeBackend("tohle není JSON pole")
    assert extract_zavazky(backend, _kapitola(), "m") == []


# ------------------------------------------------------------- spárování ----

_TISKY = [
    {"cislo": "82", "nazev": "Novela zákona o podpoře bydlení"},
    {"cislo": "4", "nazev": "Novela zákona o daních z příjmů"},
]


def test_find_tisk_candidate_returns_valid_match():
    backend = _FakeBackend(json.dumps({"cisloTisku": "4", "zduvodneni": "shoda: daň z příjmu"}))
    out = find_tisk_candidate(backend, "Snížíme daň z příjmu.", _TISKY, "m")
    assert out == {"cislo": "4", "zduvodneni": "shoda: daň z příjmu"}


def test_find_tisk_candidate_returns_none_when_model_says_no_match():
    backend = _FakeBackend(json.dumps({"cisloTisku": None, "zduvodneni": ""}))
    assert find_tisk_candidate(backend, "Posílíme obranyschopnost státu.", _TISKY, "m") is None


def test_find_tisk_candidate_rejects_hallucinated_number():
    # Model vrátí číslo, které jsme mu vůbec nenabídli -> nedůvěryhodné.
    backend = _FakeBackend(json.dumps({"cisloTisku": "999", "zduvodneni": "x"}))
    assert find_tisk_candidate(backend, "cokoliv", _TISKY, "m") is None


def test_find_tisk_candidate_ignores_malformed_response():
    backend = _FakeBackend("rozbitá odpověď")
    assert find_tisk_candidate(backend, "cokoliv", _TISKY, "m") is None


# --------------------------------------------------- nezávislý přezkum ----

def test_challenge_pairing_passes_through_valid_answer():
    backend = _FakeBackend(json.dumps({"parovaniPlati": True, "vyklad": "sedí věcně"}))
    out = challenge_pairing(backend, "závazek", "název tisku", "zdůvodnění", "m")
    assert out == {"parovaniPlati": True, "vyklad": "sedí věcně"}


def test_challenge_pairing_unreadable_answer_defaults_to_invalid():
    # Bezpečný směr je tu OPAČNÝ než u slovo_cin.challenge_mismatch: tvrdit
    # spojení, které neexistuje, je riziko, ne tvrdit rozpor, který neexistuje.
    backend = _FakeBackend("rozbitá odpověď")
    out = challenge_pairing(backend, "závazek", "název tisku", "zdůvodnění", "m")
    assert out["parovaniPlati"] is False


def test_challenge_pairing_missing_field_defaults_to_invalid():
    backend = _FakeBackend(json.dumps({"vyklad": "chybí pole parovaniPlati"}))
    out = challenge_pairing(backend, "závazek", "název tisku", "zdůvodnění", "m")
    assert out["parovaniPlati"] is False


# ------------------------------------------------------- poslední hlasování ----

_HISTORIE_DVE_HLASOVANI = """
<p>3. čtení proběhlo na 10. schůzi. Návrh zákona schválen
(<a href="/sqw/hlasy.sqw?G=50001">hlasování č. 50</a>).</p>
<p>Vráceno Senátem s pozměňovacími návrhy, na 14. schůzi Sněmovna setrvala
na původním návrhu. Návrh zákona schválen
(<a href="/sqw/hlasy.sqw?G=71001">hlasování č. 71</a>).</p>
"""


class _FakeClient:
    def __init__(self, html):
        self._html = html

    def get_text(self, url):
        return self._html


def _seed_hlasovani(conn, id_hlasovani, schuze, cislo):
    conn.execute(
        "INSERT OR REPLACE INTO hlasovani (id_hlasovani, id_organ, schuze, cislo, bod, datum, cas,"
        " pro, proti, zdrzel, nehlasoval, prihlaseno, kvorum, vysledek, nazev, is_zmatecne, url)"
        " VALUES (?, '174', ?, ?, 1, '29.05.2026', '10:00', 100, 50, 0, 0, 150, 76, 'A', 'Novela**', 0, ?)",
        (id_hlasovani, schuze, cislo, "https://www.psp.cz/sqw/hlasy.sqw?G={}".format(id_hlasovani)),
    )
    conn.commit()


def test_latest_final_vote_picks_second_vote_not_first(engine_db):
    _seed_hlasovani(engine_db, "50001", 10, 50)
    _seed_hlasovani(engine_db, "71001", 14, 71)
    out = latest_final_vote(_FakeClient(_HISTORIE_DVE_HLASOVANI), "78", engine_db)
    assert out is not None
    assert out["idHlasovani"] == "71001"
    assert out["schuze"] == 14


def test_latest_final_vote_none_when_bill_not_yet_decided(engine_db):
    html = "<p>1. čtení proběhlo na 5. schůzi. Návrh zákona přikázán výborům.</p>"
    assert latest_final_vote(_FakeClient(html), "999", engine_db) is None


# ------------------------------------------------------- poměr v klubech ----

class _FakeRegistry:
    def __init__(self, klub_by_osoba, mapping):
        self._klub = klub_by_osoba
        self._mapping = mapping

    def deputy_ids(self):
        return self._mapping.items()

    def club_at(self, id_osoba, when):
        return self._klub.get(str(id_osoba))


def test_kluby_tally_for_ballot_covers_all_three_coalition_clubs(engine_db):
    engine_db.execute(
        "INSERT OR REPLACE INTO hlasovani (id_hlasovani, id_organ, schuze, cislo, bod, datum, cas,"
        " pro, proti, zdrzel, nehlasoval, prihlaseno, kvorum, vysledek, nazev, is_zmatecne, url)"
        " VALUES ('1', '174', 5, 1, 1, '15.01.2026', '10:00', 2, 0, 0, 0, 2, 1, 'A', 'x', 0, 'u')"
    )
    engine_db.execute("INSERT INTO hlas_poslance (id_hlasovani, id_poslanec, kod) VALUES ('1','p1','A')")
    engine_db.execute("INSERT INTO hlas_poslance (id_hlasovani, id_poslanec, kod) VALUES ('1','p2','A')")
    engine_db.commit()

    registry = _FakeRegistry(
        klub_by_osoba={"o1": "ANO2011", "o2": "MS"},
        mapping={"o1": "p1", "o2": "p2"},
    )
    out = kluby_tally_for_ballot(engine_db, registry, "1", __import__("datetime").date(2026, 1, 15))
    assert set(out.keys()) == {"ANO2011", "MS", "SPD"}
    assert out["ANO2011"]["pro"] == 1
    assert out["MS"]["pro"] == 1
    assert out["SPD"] is None
