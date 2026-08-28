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
    build_role_flip_leads_from_video,
    extract_attributed_quotes,
    extract_quotes_from_speaker_text,
    fetch_article_markdown,
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

    @property
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


def test_build_role_flip_leads_skips_tier5_source_without_scraping(conn, monkeypatch):
    """Fáze 6e: bulvár/nespolehlivé zdroje se zahodí dřív, než se vůbec stáhnou."""
    import media_role_flip as mrf
    scrape_calls = []
    monkeypatch.setattr(mrf, "search_related_articles",
                        lambda query, api_key=None, limit=5: [{"url": "https://blesk.cz/clanek", "title": "t", "popis": ""}])

    def _spy_fetch(url, api_key=None):
        scrape_calls.append(url)
        return {"markdown": "Novák: citace", "medium": "blesk.cz", "datumClanku": "2025-11-10"}

    monkeypatch.setattr(mrf, "fetch_article_markdown", _spy_fetch)
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert leads == []
    assert scrape_calls == []


def test_build_role_flip_leads_skips_tier4_source_without_scraping(conn, monkeypatch):
    """Fáze 6e: názorové/sekundární zdroje (stupeň 4) se blokují stejně jako stupeň 5."""
    import media_role_flip as mrf
    scrape_calls = []
    monkeypatch.setattr(mrf, "search_related_articles",
                        lambda query, api_key=None, limit=5: [{"url": "https://echo24.cz/clanek", "title": "t", "popis": ""}])

    def _spy_fetch(url, api_key=None):
        scrape_calls.append(url)
        return {"markdown": "Novák: citace", "medium": "echo24.cz", "datumClanku": "2025-11-10"}

    monkeypatch.setattr(mrf, "fetch_article_markdown", _spy_fetch)
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert leads == []
    assert scrape_calls == []


def test_build_role_flip_leads_skips_listing_page_without_scraping(conn, monkeypatch):
    """Fáze 6f: téma/tag/přehledová stránka se přeskočí dřív, než se vůbec stáhne."""
    import media_role_flip as mrf
    scrape_calls = []
    monkeypatch.setattr(
        mrf, "search_related_articles",
        lambda query, api_key=None, limit=5: [
            {"url": "https://ct24.ceskatelevize.cz/tema/jan-novak-1", "title": "t", "popis": ""}
        ],
    )

    def _spy_fetch(url, api_key=None):
        scrape_calls.append(url)
        return {"markdown": "Novák: citace", "medium": "ct24.ceskatelevize.cz", "datumClanku": "2025-11-10"}

    monkeypatch.setattr(mrf, "fetch_article_markdown", _spy_fetch)
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert leads == []
    assert scrape_calls == []


def test_build_role_flip_leads_proceeds_for_allowed_source(conn, monkeypatch):
    """Fáze 6e: neznámá/tier 1-3 doména (výchozí `_patch_common` URL) prochází beze změny chování."""
    import media_role_flip as mrf
    _patch_common(monkeypatch, mrf, quotes=[{"citace": "citace"}],
                  tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads(["Jan Novák"], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "fake-key", "test-model")
    assert len(leads) == 1


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


# --------------------------------------------- extrakce citací z videa -----

def _speaker_segments():
    return [
        {"speaker": "SPEAKER_00", "text": "Úvodní věta.", "start": 0.0, "duration": 2.0},
        {"speaker": "SPEAKER_00", "text": "Tohle nikdy nepodpoříme.", "start": 5.0, "duration": 3.0},
    ]


def test_extract_quotes_from_speaker_text_keeps_valid_quote_with_timestamp():
    backend = _FakeBackend(json.dumps([{"citace": "Tohle nikdy nepodpoříme."}]))
    out = extract_quotes_from_speaker_text(backend, _speaker_segments(), "Jan Novák", "test-model")
    assert out == [{"citace": "Tohle nikdy nepodpoříme.", "timestampSeconds": 5.0}]


def test_extract_quotes_from_speaker_text_drops_unverifiable_substring():
    backend = _FakeBackend(json.dumps([{"citace": "Tohle nikdo neřekl."}]))
    out = extract_quotes_from_speaker_text(backend, _speaker_segments(), "Jan Novák", "test-model")
    assert out == []


def test_extract_quotes_from_speaker_text_drops_over_length_limit():
    dlouha = "A" * (MAX_QUOTE_CHARS + 1)
    segments = [{"speaker": "SPEAKER_00", "text": dlouha, "start": 0.0, "duration": 10.0}]
    backend = _FakeBackend(json.dumps([{"citace": dlouha}]))
    out = extract_quotes_from_speaker_text(backend, segments, "Jan Novák", "test-model")
    assert out == []


def test_extract_quotes_from_speaker_text_handles_unparsable_response():
    backend = _FakeBackend("not json")
    out = extract_quotes_from_speaker_text(backend, _speaker_segments(), "Jan Novák", "test-model")
    assert out == []


# --------------------------------------- orchestrace video (Fáze 6c) -------

def _seed_video_cache(conn, video_url, medium="YouTube · Kanál X", datum_videa="2025-11-10", segments=None):
    conn.execute(
        "INSERT OR REPLACE INTO video_transcript_cache (video_url, medium, datum_videa, segments_json, produced_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (video_url, medium, datum_videa, json.dumps(segments if segments is not None else _speaker_segments()), now_iso()),
    )
    conn.commit()


def _seed_video_speaker(conn, video_url, speaker_label="SPEAKER_00", id_osoba="1"):
    conn.execute(
        "INSERT OR REPLACE INTO video_speakers (video_url, speaker_label, id_osoba, sample_text, total_seconds, "
        " tagged_at, produced_at) VALUES (?, ?, ?, 'ukázka', 5.0, ?, ?)",
        (video_url, speaker_label, id_osoba, now_iso(), now_iso()),
    )
    conn.commit()


def _patch_video_common(monkeypatch, mrf, *, quotes, tisk_candidate, klub_pomer=None):
    monkeypatch.setattr(mrf, "extract_quotes_from_speaker_text", lambda *a, **k: quotes)
    monkeypatch.setattr(mrf, "find_tisk_candidate", lambda *a, **k: tisk_candidate)
    monkeypatch.setattr(mrf, "latest_final_vote", lambda *a, **k: {
        "idHlasovani": "h1", "url": "https://example/hlas", "cisloHlasovani": 1, "schuze": 1,
        "vysledekSlovy": "schválen", "prijat": True, "historieUrl": "https://example/historie",
    })
    monkeypatch.setattr(mrf, "resolve_vote", lambda *a, **k: {"hlas": "PRO", "omluven": False, "klub": "ANO2011"})
    monkeypatch.setattr(mrf, "classify_stance", lambda *a, **k: {"postoj": "PROTI", "oduvodneni": "d"})
    monkeypatch.setattr(mrf, "klub_tally_for_ballot", lambda *a, **k: klub_pomer)
    monkeypatch.setattr(mrf, "challenge_pairing", lambda *a, **k: {"parovaniPlati": True, "vyklad": "sedí"})
    monkeypatch.setattr(mrf, "challenge_mismatch", lambda *a, **k: {"rozporMizi": False, "vyklad": "obstálo"})


def test_build_role_flip_leads_from_video_creates_lead_on_real_role_change(conn, monkeypatch):
    import media_role_flip as mrf
    video_url = "https://youtube.com/watch?v=abc"
    _seed_video_cache(conn, video_url)
    _seed_video_speaker(conn, video_url)
    _patch_video_common(monkeypatch, mrf, quotes=[{"citace": "citace", "timestampSeconds": 5.0}],
                        tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads_from_video(
        [video_url], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "test-model",
    )
    assert len(leads) == 1
    assert leads[0]["receno"]["zdroj"]["timestampSeconds"] == 5.0
    assert leads[0]["receno"]["rolePriCitatu"] == "OPPOSITION_DEPUTY"
    assert leads[0]["hlasovani"]["rolePriHlasovani"] == "COALITION_DEPUTY"


def test_build_role_flip_leads_from_video_skips_untagged_speaker(conn, monkeypatch):
    import media_role_flip as mrf
    video_url = "https://youtube.com/watch?v=abc"
    _seed_video_cache(conn, video_url)
    # žádný _seed_video_speaker -> žádný mluvčí s id_osoba
    _patch_video_common(monkeypatch, mrf, quotes=[{"citace": "citace", "timestampSeconds": 5.0}],
                        tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads_from_video(
        [video_url], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "test-model",
    )
    assert leads == []


def test_build_role_flip_leads_from_video_skips_video_without_date(conn, monkeypatch):
    import media_role_flip as mrf
    video_url = "https://youtube.com/watch?v=abc"
    _seed_video_cache(conn, video_url, datum_videa=None)
    _seed_video_speaker(conn, video_url)
    _patch_video_common(monkeypatch, mrf, quotes=[{"citace": "citace", "timestampSeconds": 5.0}],
                        tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads_from_video(
        [video_url], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "test-model",
    )
    assert leads == []


def test_build_role_flip_leads_from_video_skips_before_term_start(conn, monkeypatch):
    import media_role_flip as mrf
    video_url = "https://youtube.com/watch?v=abc"
    _seed_video_cache(conn, video_url, datum_videa="2023-01-01")
    _seed_video_speaker(conn, video_url)
    _patch_video_common(monkeypatch, mrf, quotes=[{"citace": "citace", "timestampSeconds": 5.0}],
                        tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads_from_video(
        [video_url], conn, registry, tisky_registry, object(), _FakeBackend("{}"), "test-model",
    )
    assert leads == []


def test_build_role_flip_leads_from_video_skips_unprocessed_video(conn, monkeypatch):
    import media_role_flip as mrf
    _patch_video_common(monkeypatch, mrf, quotes=[{"citace": "citace", "timestampSeconds": 5.0}],
                        tisk_candidate={"cislo": "1", "zduvodneni": "sedí"})
    registry, tisky_registry = _base_setup(conn)

    leads = build_role_flip_leads_from_video(
        ["https://youtube.com/watch?v=nezpracovane"], conn, registry, tisky_registry,
        object(), _FakeBackend("{}"), "test-model",
    )
    assert leads == []


# ---------------------------------------------- záložní datum z <time> ----

def test_parse_date_from_html_reads_first_time_datetime():
    import media_role_flip as mrf
    html = '<time datetime="2025-08-22 10:05:18">22.&nbsp;8.&nbsp;2025</time>'
    assert mrf._parse_date_from_html(html) == "2025-08-22"


def test_parse_date_from_html_ignores_later_time_tags():
    import media_role_flip as mrf
    html = (
        '<div>obsah</div>'
        '<time datetime="2025-08-22 10:05:18">první</time>'
        '<div>mohlo by vás zajímat</div>'
        '<time datetime="2026-08-28 11:15:00">druhé, nesouvisející</time>'
    )
    assert mrf._parse_date_from_html(html) == "2025-08-22"


def test_parse_date_from_html_no_time_tag_returns_none():
    import media_role_flip as mrf
    assert mrf._parse_date_from_html("<div>žádné datum tady</div>") is None


def test_parse_date_from_html_rejects_future_date():
    import media_role_flip as mrf
    html = '<time datetime="2099-01-01 00:00:00">v budoucnosti</time>'
    assert mrf._parse_date_from_html(html) is None


def test_parse_date_from_html_empty_string_returns_none():
    import media_role_flip as mrf
    assert mrf._parse_date_from_html("") is None


# ------------------------------ záložní datum přes htmldate (2. stupeň) ----

def test_parse_date_with_htmldate_returns_none_when_library_missing(monkeypatch):
    import sys
    import media_role_flip as mrf
    monkeypatch.setitem(sys.modules, "htmldate", None)
    assert mrf._parse_date_with_htmldate("<div>cokoliv</div>") is None


def test_parse_date_with_htmldate_uses_conservative_mode(monkeypatch):
    import sys
    import types
    import media_role_flip as mrf

    calls = []

    def _fake_find_date(html, extensive_search=True, outputformat="%Y-%m-%d"):
        calls.append({"extensive_search": extensive_search, "outputformat": outputformat})
        return "2026-03-05"

    fake_module = types.ModuleType("htmldate")
    fake_module.find_date = _fake_find_date
    monkeypatch.setitem(sys.modules, "htmldate", fake_module)

    assert mrf._parse_date_with_htmldate("<html>...</html>") == "2026-03-05"
    # nejdůležitější tvrzení testu: nikdy se nezapne fallback na volný text
    assert calls == [{"extensive_search": False, "outputformat": "%Y-%m-%d"}]


def test_parse_date_with_htmldate_returns_none_when_find_date_returns_none(monkeypatch):
    import sys
    import types
    import media_role_flip as mrf

    fake_module = types.ModuleType("htmldate")
    fake_module.find_date = lambda html, extensive_search=True, outputformat="%Y-%m-%d": None
    monkeypatch.setitem(sys.modules, "htmldate", fake_module)

    assert mrf._parse_date_with_htmldate("<div>bez data</div>") is None


def test_parse_date_with_htmldate_rejects_future_date(monkeypatch):
    import sys
    import types
    import media_role_flip as mrf

    fake_module = types.ModuleType("htmldate")
    fake_module.find_date = lambda html, extensive_search=True, outputformat="%Y-%m-%d": "2099-01-01"
    monkeypatch.setitem(sys.modules, "htmldate", fake_module)

    assert mrf._parse_date_with_htmldate("<html>...</html>") is None


def test_parse_date_from_html_falls_back_to_htmldate_when_no_time_tag(monkeypatch):
    import sys
    import types
    import media_role_flip as mrf

    fake_module = types.ModuleType("htmldate")
    fake_module.find_date = lambda html, extensive_search=True, outputformat="%Y-%m-%d": "2026-03-05"
    monkeypatch.setitem(sys.modules, "htmldate", fake_module)

    assert mrf._parse_date_from_html("<html><body>žádný time tag tady</body></html>") == "2026-03-05"


def test_parse_date_from_html_time_tag_wins_without_calling_htmldate(monkeypatch):
    import sys
    import types
    import media_role_flip as mrf

    calls = []
    fake_module = types.ModuleType("htmldate")
    fake_module.find_date = lambda *a, **kw: calls.append(1) or "2020-01-01"
    monkeypatch.setitem(sys.modules, "htmldate", fake_module)

    html = '<time datetime="2025-08-22 10:05:18">22. 8. 2025</time>'
    assert mrf._parse_date_from_html(html) == "2025-08-22"
    assert calls == []  # levnější/přesnější <time> zdroj se najde první, htmldate se vůbec nevolá


# --------------------------- diagnostický důvod chybějícího data (Fáze 6f) --

def test_no_date_reason_meta_prazdna_time_tag_chybi():
    import media_role_flip as mrf
    assert mrf._no_date_reason({}, "<div>bez data</div>") == \
        "meta:prazdna,time-tag:chybi,htmldate:bez-vysledku"


def test_no_date_reason_meta_nevalidni_when_key_present():
    import media_role_flip as mrf
    reason = mrf._no_date_reason({"publishedTime": "neplatny-format"}, "<div></div>")
    assert reason.startswith("meta:nevalidni,")


def test_no_date_reason_time_tag_nevalidni_when_future_date():
    import media_role_flip as mrf
    html = '<time datetime="2099-01-01 00:00:00">v budoucnosti</time>'
    reason = mrf._no_date_reason({}, html)
    assert "time-tag:nevalidni" in reason


# -------------------------- filtr téma/tag/přehled stránek (Fáze 6f) -------

def test_looks_like_listing_page_tema_path():
    import media_role_flip as mrf
    assert mrf._looks_like_listing_page("https://ct24.ceskatelevize.cz/tema/eva-decroix-2391") is True


def test_looks_like_listing_page_stitky_path():
    import media_role_flip as mrf
    assert mrf._looks_like_listing_page("https://video.aktualne.cz/stitky/ivan-bartos/") is True


def test_looks_like_listing_page_bare_aktualne_index():
    import media_role_flip as mrf
    assert mrf._looks_like_listing_page("https://www.evadecroix.cz/aktualne/") is True


def test_looks_like_listing_page_youtube_and_facebook_hosts():
    import media_role_flip as mrf
    assert mrf._looks_like_listing_page("https://www.youtube.com/watch?v=abc123") is True
    assert mrf._looks_like_listing_page("https://www.facebook.com/SeznamZpravy/videos/xyz") is True


def test_looks_like_listing_page_false_for_confirmed_real_article_shapes():
    """
    Živě potvrzeno dávkovou diagnózou (8 poslanců, 2026-08-28) jako skutečné
    datované články, ne přehledy — přesně ten typ URL, kvůli kterému filtr
    záměrně NEPOUŽÍVÁ obecné pravidlo typu "jeden segment cesty".
    """
    import media_role_flip as mrf
    assert mrf._looks_like_listing_page("https://archiv.hn.cz/c1-67763020-slug") is False
    assert mrf._looks_like_listing_page("https://cnn.iprima.cz/nejaky-slug-513835") is False
    assert mrf._looks_like_listing_page("https://msp.gov.cz/en/web/msp/-/eva-decroix-transparentnost") is False
    assert mrf._looks_like_listing_page("https://www.ods.cz/clanek/28333-eva-decroix-udalosti") is False
    assert mrf._looks_like_listing_page("https://www.respekt.cz/rozhovor/eva-decroix-podceneni") is False


def test_looks_like_listing_page_false_for_unrelated_domain():
    import media_role_flip as mrf
    assert mrf._looks_like_listing_page("https://example.cz/clanek") is False


class _FakeHttpResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_article_markdown_falls_back_to_html_time_when_metadata_has_no_date(monkeypatch):
    import media_role_flip as mrf
    monkeypatch.setattr(mrf, "_scrape_cache_get", lambda key: None)
    monkeypatch.setattr(mrf, "_scrape_cache_set", lambda key, value: None)

    def _fake_urlopen(req, timeout=20):
        return _FakeHttpResponse({
            "data": {
                "markdown": "Novák: citace",
                "metadata": {},  # bez publishedTime/datePublished, jako u reálných českých webů
                "html": '<time datetime="2025-08-22 10:05:18">22. 8. 2025</time>',
            }
        })

    monkeypatch.setattr(mrf.urllib.request, "urlopen", _fake_urlopen)

    result = mrf.fetch_article_markdown("https://example.cz/clanek", api_key="fake-key")
    assert result["datumClanku"] == "2025-08-22"


def test_fetch_article_markdown_prefers_metadata_date_over_html_fallback(monkeypatch):
    import media_role_flip as mrf
    monkeypatch.setattr(mrf, "_scrape_cache_get", lambda key: None)
    monkeypatch.setattr(mrf, "_scrape_cache_set", lambda key, value: None)

    def _fake_urlopen(req, timeout=20):
        return _FakeHttpResponse({
            "data": {
                "markdown": "Novák: citace",
                "metadata": {"publishedTime": "2025-11-10T00:00:00Z"},
                "html": '<time datetime="2020-01-01 00:00:00">jiné, nepoužije se</time>',
            }
        })

    monkeypatch.setattr(mrf.urllib.request, "urlopen", _fake_urlopen)

    result = mrf.fetch_article_markdown("https://example.cz/clanek", api_key="fake-key")
    assert result["datumClanku"] == "2025-11-10"


def test_fetch_article_markdown_none_when_neither_source_has_date(monkeypatch):
    import media_role_flip as mrf
    monkeypatch.setattr(mrf, "_scrape_cache_get", lambda key: None)
    monkeypatch.setattr(mrf, "_scrape_cache_set", lambda key, value: None)

    def _fake_urlopen(req, timeout=20):
        return _FakeHttpResponse({
            "data": {"markdown": "Novák: citace", "metadata": {}, "html": "<div>bez data</div>"}
        })

    monkeypatch.setattr(mrf.urllib.request, "urlopen", _fake_urlopen)

    result = mrf.fetch_article_markdown("https://example.cz/clanek", api_key="fake-key")
    assert result["datumClanku"] is None
    assert result["datumDuvodChybi"] == "meta:prazdna,time-tag:chybi,htmldate:bez-vysledku"


def test_fetch_article_markdown_no_reason_key_when_date_found(monkeypatch):
    import media_role_flip as mrf
    monkeypatch.setattr(mrf, "_scrape_cache_get", lambda key: None)
    monkeypatch.setattr(mrf, "_scrape_cache_set", lambda key, value: None)

    def _fake_urlopen(req, timeout=20):
        return _FakeHttpResponse({
            "data": {
                "markdown": "Novák: citace",
                "metadata": {"publishedTime": "2025-11-10T00:00:00Z"},
                "html": "<div>irelevantní</div>",
            }
        })

    monkeypatch.setattr(mrf.urllib.request, "urlopen", _fake_urlopen)

    result = mrf.fetch_article_markdown("https://example.cz/clanek", api_key="fake-key")
    assert result["datumClanku"] == "2025-11-10"
    assert "datumDuvodChybi" not in result
