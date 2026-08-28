"""
Testy Fáze 3 (Slovo vs. Čin) — logika shody, obhájce a důkazní brána.

Bez sítě a bez modelu: backend i klient jsou dvojníci. Jde o to, co se stane
s daty, ne o to, jak dobře model čte češtinu.
"""

import json

import pytest

from export_web import load_slovo_cin, verify_slovo_cin
from slovo_cin import build_record, challenge_mismatch, classify_stance, store_record


class _FakeBackend:
    """Vrátí předem danou odpověď; zaznamená, s jakým cache klíčem se volalo."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def call(self, role, system_prompt, user_payload, model, ck=None):
        self.calls.append({"role": role, "ck": ck, "payload": user_payload})
        return self.response


class _FakeRegistry:
    def __init__(self, mapping):
        self._mapping = mapping

    def deputy_id(self, id_osoba):
        return self._mapping.get(str(id_osoba))


def _candidate(citace="Tuto novelu podporujeme.", id_osoba="6992"):
    return {
        "claimId": "c1",
        "messageId": "m1",
        "idOsoba": id_osoba,
        "claim": {
            "rawSpan": citace,
            "sourceCharStart": 0,
            "sourceCharEnd": len(citace),
            "subject": "klub",
            "predicate": "podporuje",
            "object": "novelu",
        },
        "message": {"date": "2026-06-30", "source": {"stenoUrl": "https://www.psp.cz/x#r4"}},
        "debate": {"debateId": "psp-24-5-1", "title": "Novela", "sessionNumber": 24},
        "bod": {"nazev": "Vládní návrh zákona o něčem"},
        "tisk": "198",
        "finalVote": {
            "idHlasovani": "88130", "url": "https://www.psp.cz/sqw/hlasy.sqw?G=88130",
            "cisloHlasovani": 285, "schuze": 24, "vysledekSlovy": "schválen",
            "prijat": True, "historieUrl": "https://www.psp.cz/sqw/historie.sqw?o=10&T=198",
        },
    }


def _vote(hlas="PRO", omluven=False):
    return {"hlas": hlas, "pritomen": hlas != "NEPRIHLASEN", "klub": "ANO2011",
            "omluven": omluven, "vysledek": "NÁVRH BYL PŘIJAT", "url": "u"}


# ---------------------------------------------------------------- shoda ----

@pytest.mark.parametrize("postoj,hlas,ocekavano", [
    ("PRO", "PRO", "SHODA"),
    ("PROTI", "PROTI", "SHODA"),
    ("PRO", "PROTI", "NESHODA"),
    ("PROTI", "PRO", "NESHODA"),
    # Zdržení ani neúčast není rozpor — poslanec nic nehlasoval.
    ("PRO", "ZDRZEL_SE", "NEHLASOVAL"),
    ("PROTI", "NEPRIHLASEN", "NEHLASOVAL"),
])
def test_build_record_shoda(postoj, hlas, ocekavano):
    record = build_record(
        _candidate(), {"postoj": postoj, "oduvodneni": "x"}, _vote(hlas), None
    )
    assert record["shoda"] == ocekavano


def test_build_record_keeps_evidence_links():
    record = build_record(_candidate(), {"postoj": "PRO", "oduvodneni": "x"}, _vote(), None)
    # Bez těchhle tří odkazů je položka netvrditelná: co bylo řečeno,
    # jak se hlasovalo, a čím je doloženo, že šlo o finální hlasování.
    assert record["receno"]["stenoUrl"]
    assert record["hlasovani"]["url"]
    assert record["hlasovani"]["historieUrl"]


# ------------------------------------------------------------- postoje ----

def test_classify_stance_defaults_to_neurcitelne_on_bad_json():
    backend = _FakeBackend("tohle není JSON")
    out = classify_stance(backend, _candidate()["claim"], "Novela", "m")
    assert out["postoj"] == "NEURCITELNE"


def test_classify_stance_rejects_unknown_value():
    backend = _FakeBackend(json.dumps({"postoj": "URCITE_PRO", "oduvodneni": ""}))
    out = classify_stance(backend, _candidate()["claim"], "Novela", "m")
    assert out["postoj"] == "NEURCITELNE"


def test_classify_stance_cache_key_carries_prompt_version():
    # Bez verze v klíči by se po zpřísnění promptu vracely staré odpovědi:
    # `model_backend` počítá klíč jen z payloadu.
    backend = _FakeBackend(json.dumps({"postoj": "PRO", "oduvodneni": ""}))
    classify_stance(backend, _candidate()["claim"], "Novela", "m")
    assert backend.calls[0]["ck"]
    assert backend.calls[0]["role"] == "SLOVO_CIN_POSTOJ"


def test_classify_stance_prompt_does_not_leak_the_vote():
    """Model nesmí vědět, jak se hlasovalo — jinak si postoj domyslí zpětně."""
    backend = _FakeBackend(json.dumps({"postoj": "PRO", "oduvodneni": ""}))
    classify_stance(backend, _candidate()["claim"], "Novela", "m")
    payload = backend.calls[0]["payload"]
    for zakazane in ("hlas", "PROTI", "88130", "schválen"):
        assert zakazane not in payload


# ------------------------------------------------------------- obhájce ----

def test_challenge_mismatch_treats_unreadable_answer_as_defended():
    record = build_record(_candidate(), {"postoj": "PRO", "oduvodneni": ""}, _vote("PROTI"), None)
    out = challenge_mismatch(_FakeBackend("rozbitá odpověď"), record, "m")
    # Nepřečtená odpověď nesmí projít jako "obžaloba obstála".
    assert out["rozporMizi"] is True


def test_challenge_mismatch_passes_club_ratio_to_model():
    klub = {"pro": 0, "proti": 13, "zdrzelNeboNehlasoval": 1, "neprihlasen": 2}
    record = build_record(_candidate(), {"postoj": "PRO", "oduvodneni": ""}, _vote("PROTI"), klub)
    backend = _FakeBackend(json.dumps({"rozporMizi": False, "vyklad": ""}))
    challenge_mismatch(backend, record, "m")
    payload = json.loads(backend.calls[0]["payload"])
    assert payload["KLUB_POMER"] == klub


# --------------------------------------------------------- důkazní brána ----

def _seed(conn, id_hlasovani="88130", kod="A", is_zmatecne=0):
    conn.execute(
        "INSERT OR REPLACE INTO hlasovani (id_hlasovani, id_organ, schuze, cislo, bod, datum, cas,"
        " pro, proti, zdrzel, nehlasoval, prihlaseno, kvorum, vysledek, nazev, is_zmatecne, url)"
        " VALUES (?, '174', 24, 285, 1, '30.06.2026', '10:00', 1, 1, 0, 0, 2, 1, 'A', 'N', ?, 'u')",
        (id_hlasovani, is_zmatecne),
    )
    conn.execute(
        "INSERT OR REPLACE INTO hlas_poslance (id_hlasovani, id_poslanec, kod) VALUES (?, '2103', ?)",
        (id_hlasovani, kod),
    )
    conn.commit()


def _store(conn, hlas="PRO", postoj="PRO"):
    record = build_record(_candidate(), {"postoj": postoj, "oduvodneni": ""}, _vote(hlas), None)
    store_record(conn, record, "m")
    conn.commit()
    return record


def test_gate_accepts_record_matching_open_data(engine_db):
    _seed(engine_db, kod="A")
    _store(engine_db, hlas="PRO")
    out = verify_slovo_cin(engine_db, _FakeRegistry({"6992": "2103"}))
    assert out["ok"] == 1 and out["zamitnuto"] == []
    assert len(load_slovo_cin(engine_db)) == 1


def test_gate_rejects_when_vote_contradicts_open_data(engine_db):
    # Uloženo PRO, otevřená data říkají B (proti) -> nesmí projít.
    _seed(engine_db, kod="B")
    _store(engine_db, hlas="PRO")
    out = verify_slovo_cin(engine_db, _FakeRegistry({"6992": "2103"}))
    assert out["ok"] == 0
    assert "hlas nesouhlasí" in out["zamitnuto"][0]
    assert load_slovo_cin(engine_db) == []


def test_gate_rejects_annulled_vote(engine_db):
    _seed(engine_db, kod="A", is_zmatecne=1)
    _store(engine_db, hlas="PRO")
    out = verify_slovo_cin(engine_db, _FakeRegistry({"6992": "2103"}))
    assert out["ok"] == 0
    assert "zmatečné" in out["zamitnuto"][0]


def test_gate_rejects_unknown_ballot(engine_db):
    _store(engine_db, hlas="PRO")  # žádné hlasování nezaseto
    out = verify_slovo_cin(engine_db, _FakeRegistry({"6992": "2103"}))
    assert out["ok"] == 0
    assert "není v otevřených datech" in out["zamitnuto"][0]


def test_gate_rejects_deputy_without_mandate(engine_db):
    _seed(engine_db, kod="A")
    _store(engine_db, hlas="PRO")
    out = verify_slovo_cin(engine_db, _FakeRegistry({}))
    assert out["ok"] == 0
    assert "mandát" in out["zamitnuto"][0]


def test_gate_recomputes_shoda_and_rejects_tampering(engine_db):
    """Uložená `shoda` se nebere na slovo — přepočítá se z hlasu a postoje."""
    _seed(engine_db, kod="A")
    _store(engine_db, hlas="PRO", postoj="PRO")
    engine_db.execute("UPDATE slovo_cin SET shoda = 'NESHODA'")
    engine_db.commit()
    out = verify_slovo_cin(engine_db, _FakeRegistry({"6992": "2103"}))
    assert out["ok"] == 0
    assert "shoda nesedí" in out["zamitnuto"][0]
