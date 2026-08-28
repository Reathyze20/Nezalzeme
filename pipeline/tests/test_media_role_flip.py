"""
Testy Fáze 6b (rolový obrat v médiích) — extrakce citací, pojistky proti
term-boundary a proti "žádná skutečná změna strany", a že se schválení
nesmí ztratit / obejít.

Bez sítě: Firecrawl, backend a hlasování jsou dvojníci nebo fixtures
v `open_engine_db(":memory:")`.
"""

import json

import pytest

from db import now_iso, open_engine_db
from media_role_flip import (
    MAX_QUOTE_CHARS,
    NAME_PROXIMITY_WINDOW,
    TERM_START_DATE,
    approve_lead,
    build_record,
    build_role_flip_leads,
    extract_attributed_quotes,
    load_leads,
    resolve_id_osoba,
    store_record,
)


class _FakeBackend:
    def __init__(self, responses):
        # responses: list consumed in call order, or a single value reused
        self._responses = responses if isinstance(responses, list) else None
        self._single = responses if not isinstance(responses, list) else None
        self.calls = []

    def call(self, role, prompt, payload, model, ck=None):
        self.calls.append({"role": role, "payload": payload})
        if self._responses is not None:
            return self._responses.pop(0)
        return self._single


class _FakePerson:
    def __init__(self, jmeno, prijmeni):
        self.jmeno = jmeno
        self.prijmeni = prijmeni

    def full_name(self):
        return f"{self.jmeno} {self.prijmeni}"


class _FakeRegistry:
    def __init__(self, people, role_fn):
        self.people = people
        self.term_organ_id = "174"
        self._role_fn = role_fn

    def political_role_at(self, id_osoba, when):
        return {"role": self._role_fn(id_osoba, when)}

    def deputy_id(self, id_osoba):
        return "posl-" + id_osoba


class _FakeTiskInfo:
    def __init__(self, cislo, cely_nazev, url="https://example/tisk"):
        self.cislo = cislo
        self.cely_nazev = cely_nazev
        self.url = url


class _FakeTiskyRegistry:
    def __init__(self, tisky):
        self._tisky = {t.cislo: t for t in tisky}

    def all_for_organ(self, organ):
        return list(self._tisky.values())

    def get_tisk(self, cislo, organ="174"):
        return self._tisky.get(cislo)


@pytest.fixture
def conn():
    return open_engine_db(":memory:")


def _seed_hlasovani(conn, id_hlasovani="h1", datum="10.11.2025"):
    conn.execute(
        "INSERT OR REPLACE INTO hlasovani "
        "(id_hlasovani, id_organ, schuze, cislo, bod, datum, cas, pro, proti, zdrzel, "
        " nehlasoval, prihlaseno, kvorum, vysledek, nazev, is_zmatecne, url) "
        "VALUES (?, '174', 1, 1, 1, ?, '10:00:00', 90, 80, 0, 0, 170, 86, 'schválen', 'test', 0, 'https://example/hlas')",
        (id_hlasovani, datum),
    )
    conn.commit()


def _seed_hlas_poslance(conn, id_hlasovani, id_poslanec, kod):
    conn.execute(
        "INSERT OR REPLACE INTO hlas_poslance (id_hlasovani, id_poslanec, kod) VALUES (?, ?, ?)",
        (id_hlasovani, id_poslanec, kod),
    )
    conn.commit()


# --------------------------------------------------------------- jméno -----

def test_resolve_id_osoba_matches_full_name_case_insensitive():
    registry = _FakeRegistry({"1": _FakePerson("Jan", "Novák")}, lambda *_: "OPPOSITION_DEPUTY")
    assert resolve_id_osoba(registry, "jan novák") == "1"


def test_resolve_id_osoba_none_without_match():
    registry = _FakeRegistry({"1": _FakePerson("Jan", "Novák")}, lambda *_: "OPPOSITION_DEPUTY")
    assert resolve_id_osoba(registry, "Petr Svoboda") is None


# ------------------------------------------------------ extrakce citací ----

def test_extract_attributed_quotes_keeps_valid_quote():
    markdown = 'Novinář se zeptal. Novák řekl: "Tohle nikdy nepodpoříme." Konec článku.'
    backend = _FakeBackend(json.dumps([{"citace": "Tohle nikdy nepodpoříme."}]))
    out = extract_attributed_quotes(backend, markdown, "Jan Novák", "Novák", "test-model")
    assert out == [{"citace": "Tohle nikdy nepodpoříme."}]


def test_extract_attributed_quotes_drops_unverifiable_substring():
    markdown = 'Novák řekl něco úplně jiného v článku.'
    backend = _FakeBackend(json.dumps([{"citace": "Tohle nikdy nepodpoříme."}]))
    out = extract_attributed_quotes(backend, markdown, "Jan Novák", "Novák", "test-model")
    assert out == []


def test_extract_attributed_quotes_drops_quote_without_name_nearby():
    # citace existuje v textu, ale jméno "Novák" je příliš daleko
    filler = "x" * (NAME_PROXIMITY_WINDOW + 50)
    markdown = 'Novák byl na tiskovce. ' + filler + ' "Tohle nikdy nepodpoříme," řekl někdo.'
    backend = _FakeBackend(json.dumps([{"citace": "Tohle nikdy nepodpoříme,"}]))
    out = extract_attributed_quotes(backend, markdown, "Jan Novák", "Novák", "test-model")
    assert out == []


def test_extract_attributed_quotes_drops_over_length_limit():
    dlouha_citace = "A" * (MAX_QUOTE_CHARS + 1)
    markdown = f'Novák řekl: "{dlouha_citace}"'
    backend = _FakeBackend(json.dumps([{"citace": dlouha_citace}]))
    out = extract_attributed_quotes(backend, markdown, "Jan Novák", "Novák", "test-model")
    assert out == []


def test_extract_attributed_quotes_handles_unparsable_response():
    backend = _FakeBackend("not json")
    out = extract_attributed_quotes(backend, "cokoliv Novák", "Jan Novák", "Novák", "test-model")
    assert out == []


# --------------------------------------------------------- perzistence ----

def _minimal_record(record_id="mrf-1", hlas="PRO", postoj="PRO", shoda="SHODA"):
    return {
        "id": record_id,
        "idOsoba": "1",
        "politik": "Jan Novák",
        "receno": {
            "citace": "citace",
            "rolePriCitatu": "OPPOSITION_DEPUTY",
            "zdroj": {"url": "https://example/clanek", "medium": "example.cz", "datumClanku": "2025-11-10"},
        },
        "postoj": postoj,
        "postojOduvodneni": "duvod",
        "tisk": {"cislo": "1", "nazev": "Test tisk", "url": "https://example/tisk"},
        "hlasovani": {
            "idHlasovani": "h1", "url": "https://example/hlas", "cislo": 1, "schuze": 1,
            "vysledekSlovy": "schválen", "prijat": True, "historieUrl": "https://example/historie",
            "hlas": hlas, "omluven": False, "klub": "ANO2011", "klubPomer": None,
            "rolePriHlasovani": "COALITION_DEPUTY",
        },
        "shoda": shoda,
    }


def test_new_lead_is_not_approved_by_default(conn):
    record = _minimal_record()
    store_record(conn, record, "test-model", parovani_plati=True, rozpor_mizi=False)
    leads = load_leads(conn)
    assert len(leads) == 1
    assert leads[0]["schvaleno"] is False
    assert leads[0]["schvalenoAt"] is None


def test_store_record_preserves_prior_approval_on_rerun(conn):
    record = _minimal_record()
    store_record(conn, record, "test-model", parovani_plati=True, rozpor_mizi=False)
    assert approve_lead(conn, record["id"]) is True

    # Znovu uložený stejný lead (např. další běh pipeline) nesmí zrušit schválení.
    store_record(conn, record, "test-model", parovani_plati=True, rozpor_mizi=False)
    leads = load_leads(conn)
    assert leads[0]["schvaleno"] is True
    assert leads[0]["schvalenoAt"] is not None


def test_approve_lead_only_affects_given_id(conn):
    a = _minimal_record("mrf-a")
    b = _minimal_record("mrf-b")
    store_record(conn, a, "test-model", parovani_plati=True, rozpor_mizi=False)
    store_record(conn, b, "test-model", parovani_plati=True, rozpor_mizi=False)

    assert approve_lead(conn, "mrf-a") is True
    leads = {lead["id"]: lead for lead in load_leads(conn)}
    assert leads["mrf-a"]["schvaleno"] is True
    assert leads["mrf-b"]["schvaleno"] is False


def test_approve_lead_returns_false_for_unknown_id(conn):
    assert approve_lead(conn, "nonexistent") is False


def test_build_record_neshoda_when_stance_and_vote_disagree():
    record = build_record(
        "1", "Jan Novák", "citace",
        {"url": "u", "medium": "m", "datumClanku": "2025-11-10"},
        "OPPOSITION_DEPUTY",
        _FakeTiskInfo("1", "Test tisk"),
        {"idHlasovani": "h1", "url": "u", "cisloHlasovani": 1, "schuze": 1,
         "vysledekSlovy": "schválen", "prijat": True, "historieUrl": "u"},
        {"postoj": "PROTI", "oduvodneni": "d"},
        {"hlas": "PRO", "omluven": False, "klub": "ANO2011"},
        "COALITION_DEPUTY", None,
    )
    assert record["shoda"] == "NESHODA"


def test_build_record_shoda_when_stance_and_vote_agree():
    record = build_record(
        "1", "Jan Novák", "citace",
        {"url": "u", "medium": "m", "datumClanku": "2025-11-10"},
        "OPPOSITION_DEPUTY",
        _FakeTiskInfo("1", "Test tisk"),
        {"idHlasovani": "h1", "url": "u", "cisloHlasovani": 1, "schuze": 1,
         "vysledekSlovy": "schválen", "prijat": True, "historieUrl": "u"},
        {"postoj": "PRO", "oduvodneni": "d"},
        {"hlas": "PRO", "omluven": False, "klub": "ANO2011"},
        "COALITION_DEPUTY", None,
    )
    assert record["shoda"] == "SHODA"


# ------------------------------------------------------- orchestrace -------

def _patch_common(monkeypatch, mrf, *, quotes, tisk_candidate, klub_pomer=None):
    monkeypatch.setattr(mrf, "search_related_articles",
                        lambda query, api_key=None, limit=5: [{"url": "https://example/clanek", "title": "t", "popis": ""}])
    monkeypatch.setattr(mrf, "fetch_article_markdown",
                        lambda url, api_key=None: {"markdown": "Novák: citace", "medium": "example.cz",
                                                     "datumClanku": "2025-11-10"})
    monkeypatch.setattr(mrf, "extract_attributed_quotes", lambda *a, **k: quotes)
    monkeypatch.setattr(mrf, "find_tisk_candidate", lambda *a, **k: tisk_candidate)
    monkeypatch.setattr(mrf, "latest_final_vote", lambda *a, **k: {
        "idHlasovani": "h1", "url": "https://example/hlas", "cisloHlasovani": 1, "schuze": 1,
        "vysledekSlovy": "schválen", "prijat": True, "historieUrl": "https://example/historie",
    })
    monkeypatch.setattr(mrf, "resolve_vote", lambda *a, **k: {
        "hlas": "PRO", "omluven": False, "klub": "ANO2011",
    })
    monkeypatch.setattr(mrf, "classify_stance", lambda *a, **k: {"postoj": "PROTI", "oduvodneni": "d"})
    monkeypatch.setattr(mrf, "klub_tally_for_ballot", lambda *a, **k: klub_pomer)
    monkeypatch.setattr(mrf, "challenge_pairing", lambda *a, **k: {"parovaniPlati": True, "vyklad": "sedí"})
    monkeypatch.setattr(mrf, "challenge_mismatch", lambda *a, **k: {"rozporMizi": False, "vyklad": "obstálo"})


def _base_setup(conn):
    # Hlasování je datováno POZDĚJI než citát z článku (2025-11-10) — nutné,
    # aby role_při_hlasování mohla vyjít jinak než role_při_citátu.
    _seed_hlasovani(conn, "h1", "10.12.2025")
    switch = TERM_START_DATE.replace(month=12, day=1)
    registry = _FakeRegistry(
        {"1": _FakePerson("Jan", "Novák")},
        lambda id_osoba, when: "OPPOSITION_DEPUTY" if when < switch else "COALITION_DEPUTY",
    )
    tisky_registry = _FakeTiskyRegistry([_FakeTiskInfo("1", "Test tisk")])
    return registry, tisky_registry


def test_build_role_flip_leads_creates_lead_on_real_role_change(conn, monkeypatch):
    import media_role_flip as mrf
    _patch_common(monkeypatch, mrf, quotes=[{"citace": "citace"}],
                  tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert len(leads) == 1
    assert leads[0]["receno"]["rolePriCitatu"] == "OPPOSITION_DEPUTY"
    assert leads[0]["hlasovani"]["rolePriHlasovani"] == "COALITION_DEPUTY"


def test_build_role_flip_leads_skips_when_role_unchanged(conn, monkeypatch):
    import media_role_flip as mrf
    _patch_common(monkeypatch, mrf, quotes=[{"citace": "citace"}],
                  tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    _seed_hlasovani(conn, "h1", "10.11.2025")
    # Role je stejná při citátu i při hlasování -> žádná skutečná změna strany.
    registry = _FakeRegistry({"1": _FakePerson("Jan", "Novák")}, lambda *_: "OPPOSITION_DEPUTY")
    tisky_registry = _FakeTiskyRegistry([_FakeTiskInfo("1", "Test tisk")])

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert leads == []


def test_build_role_flip_leads_skips_article_before_term_start(conn, monkeypatch):
    import media_role_flip as mrf
    monkeypatch.setattr(mrf, "search_related_articles",
                        lambda query, api_key=None, limit=5: [{"url": "https://example/clanek", "title": "t", "popis": ""}])
    monkeypatch.setattr(mrf, "fetch_article_markdown",
                        lambda url, api_key=None: {"markdown": "Novák: citace", "medium": "example.cz",
                                                     "datumClanku": "2023-01-01"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert leads == []


def test_build_role_flip_leads_skips_article_without_date(conn, monkeypatch):
    import media_role_flip as mrf
    monkeypatch.setattr(mrf, "search_related_articles",
                        lambda query, api_key=None, limit=5: [{"url": "https://example/clanek", "title": "t", "popis": ""}])
    monkeypatch.setattr(mrf, "fetch_article_markdown",
                        lambda url, api_key=None: {"markdown": "Novák: citace", "medium": "example.cz",
                                                     "datumClanku": None})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert leads == []


def test_build_role_flip_leads_skips_hallucinated_tisk(conn, monkeypatch):
    import media_role_flip as mrf
    _patch_common(monkeypatch, mrf, quotes=[{"citace": "citace"}], tisk_candidate=None)
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert leads == []


def test_build_role_flip_leads_skips_non_publishable_stance(conn, monkeypatch):
    import media_role_flip as mrf
    _patch_common(monkeypatch, mrf, quotes=[{"citace": "citace"}],
                  tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    monkeypatch.setattr(mrf, "classify_stance", lambda *a, **k: {"postoj": "NEURCITELNE", "oduvodneni": "d"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert leads == []


def test_build_role_flip_leads_attaches_gate_verdicts_even_when_rejected(conn, monkeypatch):
    """Zamítnuté brány se PŘIPOJÍ k leadu, ne tiše zahodí — interní nástroj je pro člověka."""
    import media_role_flip as mrf
    _patch_common(monkeypatch, mrf, quotes=[{"citace": "citace"}],
                  tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    monkeypatch.setattr(mrf, "challenge_pairing", lambda *a, **k: {"parovaniPlati": False, "vyklad": "nesedí"})
    monkeypatch.setattr(mrf, "challenge_mismatch", lambda *a, **k: {"rozporMizi": True, "vyklad": "obhájeno"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert len(leads) == 1
    assert leads[0]["parovani"] == "nesedí"
    assert leads[0]["obhajoba"] == "obhájeno"

    stored = load_leads(conn)
    assert len(stored) == 1
    assert stored[0]["parovaniPlati"] is False
    assert stored[0]["rozporMizi"] is True
