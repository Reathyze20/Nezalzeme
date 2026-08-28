"""
Testy Fáze 6 (novinářský nástroj) — pásmo NLI 0,50-0,80, obohacení,
a strukturální pojistka že výstup nikdy nejde do `src/data/psp/`.

Bez sítě: Hlídač státu i Firecrawl se testují přes injektované dvojníky /
chybějící klíč, nikdy přes skutečné HTTP volání.
"""

import json

import pytest

from db import open_engine_db, store_candidate_pair, store_claims, store_nli_result
from journalist_tool import (
    NLI_BAND_MAX,
    NLI_BAND_MIN,
    attach_articles,
    attach_macro_context,
    build_internal_overview,
    build_lead_record,
    candidate_leads,
    enrich_with_hlidac,
    export_internal,
    search_related_articles,
)


def _claim(claim_id, message_id, subject="vláda", predicate="podpoří", obj="zákon",
           time_frame="2026", category="STANCE_COMMITMENT", raw_span="podpoříme zákon"):
    return {
        "claimId": claim_id,
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "timeFrame": time_frame,
        "claimCategory": category,
        "rawSpan": raw_span,
        "sourceCharStart": 0,
        "sourceCharEnd": len(raw_span),
    }


def _seed_pair(conn, pair_id, contradiction, similarity=0.7,
               claim_a=None, claim_b=None, message_id_a="m-a", message_id_b="m-b"):
    claim_a = claim_a or _claim(pair_id + "-a", message_id_a)
    claim_b = claim_b or _claim(pair_id + "-b", message_id_b, raw_span="starší tvrzení")
    store_claims(conn, message_id_a, "1001", [claim_a], "test-model")
    store_claims(conn, message_id_b, "1001", [claim_b], "test-model")
    store_candidate_pair(conn, pair_id, claim_a["claimId"], claim_b["claimId"], similarity)
    store_nli_result(conn, pair_id, {"CONTRADICTION": contradiction}, "CONTRADICTION")
    return claim_a, claim_b


def _msg(message_id, speaker="Jan Novák", date="2026-03-01", id_osoba="1001", steno="https://example/steno"):
    return {
        "messageId": message_id,
        "speaker": speaker,
        "party": "TEST",
        "date": date,
        "cleanText": "x" * 300,
        "source": {"idOsoba": id_osoba, "stenoUrl": steno, "isChair": False},
    }


@pytest.fixture
def conn():
    return open_engine_db(":memory:")


# --------------------------------------------------------------- pásmo -----

def test_candidate_leads_includes_band_midpoint(conn):
    _seed_pair(conn, "p1", contradiction=0.65)
    leads = candidate_leads(conn)
    assert [l["pairId"] for l in leads] == ["p1"]


def test_candidate_leads_excludes_below_band(conn):
    _seed_pair(conn, "p-low", contradiction=NLI_BAND_MIN - 0.01)
    assert candidate_leads(conn) == []


def test_candidate_leads_excludes_at_or_above_tribunal_threshold(conn):
    """>= 0,80 patří tribunálu (run_pipeline.phase_tribunal) — sem nesmí."""
    _seed_pair(conn, "p-high", contradiction=NLI_BAND_MAX)
    assert candidate_leads(conn) == []


def test_candidate_leads_excludes_procedural_claims(conn):
    claim_a = _claim("pp-a", "m-a", category="PROCEDURAL", raw_span="zahajuji hlasování")
    _seed_pair(conn, "pp", contradiction=0.6, claim_a=claim_a)
    assert candidate_leads(conn) == []


def test_candidate_leads_excludes_same_message_pair(conn):
    claim_a = _claim("sm-a", "m-same")
    claim_b = _claim("sm-b", "m-same", raw_span="jiné tvrzení stejného projevu")
    _seed_pair(conn, "sm", contradiction=0.6, claim_a=claim_a, claim_b=claim_b,
               message_id_a="m-same", message_id_b="m-same")
    assert candidate_leads(conn) == []


def test_candidate_leads_excludes_below_similarity_threshold(conn):
    _seed_pair(conn, "p-sim", contradiction=0.6, similarity=0.1)
    assert candidate_leads(conn) == []


# ------------------------------------------------------------ sestavení ----

def test_build_lead_record_returns_none_without_source_message(conn):
    _seed_pair(conn, "p1", contradiction=0.65)
    lead = candidate_leads(conn)[0]
    assert build_lead_record(lead, {}) is None


def test_build_lead_record_shapes_both_sides(conn):
    _seed_pair(conn, "p1", contradiction=0.65, message_id_a="m-a", message_id_b="m-b")
    lead = candidate_leads(conn)[0]
    msg_map = {"m-a": _msg("m-a"), "m-b": _msg("m-b", speaker="Jan Novák", date="2025-01-01")}
    record = build_lead_record(lead, msg_map)
    assert record["vyrokA"]["speaker"] == "Jan Novák"
    assert record["vyrokA"]["stenoUrl"] == "https://example/steno"
    assert record["vyrokB"]["date"] == "2025-01-01"
    assert record["contradiction"] == pytest.approx(0.65)
    assert record["hlidacStatu"] is None
    assert record["clanky"] == []


# ------------------------------------------------------------ obohacení ----

class _FakeEnrichment:
    def __init__(self, url, roles=None, entities=None):
        self.profile_url = url
        self.historical_roles = roles or []
        self.corporate_entities = entities or []


class _FakeHlidacClient:
    def __init__(self, result):
        self.result = result
        self.api_token = "fake-token"
        self.calls = []

    def enrich_speaker(self, name, psp_id=None):
        self.calls.append((name, psp_id))
        return self.result


def test_enrich_with_hlidac_attaches_profile_when_found(conn):
    _seed_pair(conn, "p1", contradiction=0.65)
    lead = candidate_leads(conn)[0]
    msg_map = {"m-a": _msg("m-a"), "m-b": _msg("m-b")}
    record = build_lead_record(lead, msg_map)

    client = _FakeHlidacClient(_FakeEnrichment("https://hlidacstatu.cz/osoba/1", entities=["Firma s.r.o."]))
    enrich_with_hlidac([record], client)

    assert record["vyrokA"]["hlidacProfil"]["url"] == "https://hlidacstatu.cz/osoba/1"
    assert record["vyrokA"]["hlidacProfil"]["firemniVazby"] == ["Firma s.r.o."]
    # Stejná osoba na obou stranách -> cachováno, ne dvakrát dotázáno.
    assert len(client.calls) == 1


def test_enrich_with_hlidac_leaves_none_without_client(conn):
    _seed_pair(conn, "p1", contradiction=0.65)
    lead = candidate_leads(conn)[0]
    msg_map = {"m-a": _msg("m-a"), "m-b": _msg("m-b")}
    record = build_lead_record(lead, msg_map)

    enrich_with_hlidac([record], None)
    assert "hlidacProfil" not in record["vyrokA"]


def test_attach_macro_context_skips_when_no_data_sources(conn, monkeypatch):
    _seed_pair(conn, "p1", contradiction=0.65)
    lead = candidate_leads(conn)[0]
    msg_map = {"m-a": _msg("m-a", date="2026-03-15"), "m-b": _msg("m-b")}
    record = build_lead_record(lead, msg_map)

    import journalist_tool
    monkeypatch.setattr(journalist_tool, "get_macro_context", lambda month: {"data_sources": []})
    attach_macro_context([record])
    assert record["makrokontext"] is None


def test_attach_macro_context_attaches_when_available(conn, monkeypatch):
    _seed_pair(conn, "p1", contradiction=0.65)
    lead = candidate_leads(conn)[0]
    msg_map = {"m-a": _msg("m-a", date="2026-03-15"), "m-b": _msg("m-b")}
    record = build_lead_record(lead, msg_map)

    import journalist_tool
    macro = {"data_sources": ["csu_cpi"], "narrative": "inflace 3 %", "month": "2026-03"}
    monkeypatch.setattr(journalist_tool, "get_macro_context", lambda month: macro)
    attach_macro_context([record])
    assert record["makrokontext"]["narrative"] == "inflace 3 %"


def test_search_related_articles_returns_empty_without_key(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    assert search_related_articles("cokoliv", api_key=None) == []


def test_attach_articles_noop_without_key(conn, monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    _seed_pair(conn, "p1", contradiction=0.65)
    lead = candidate_leads(conn)[0]
    msg_map = {"m-a": _msg("m-a"), "m-b": _msg("m-b")}
    record = build_lead_record(lead, msg_map)
    attach_articles([record], api_key=None)
    assert record["clanky"] == []


# ------------------------------------------------------------- export ------

def test_build_internal_overview_reports_disabled_integrations_without_keys(conn, monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("HLIDAC_STATU_TOKEN", raising=False)
    _seed_pair(conn, "p1", contradiction=0.65)
    pairs = [({"debateId": "d1"}, _msg("m-a")), ({"debateId": "d2"}, _msg("m-b"))]

    overview = build_internal_overview(conn, pairs)
    assert overview["leadCount"] == 1
    assert overview["hlidacStatuZapnuto"] is False
    assert overview["firecrawlZapnuto"] is False
    assert overview["nliBand"] == [NLI_BAND_MIN, NLI_BAND_MAX]
    assert "verdicts" not in json.dumps(overview)  # sanity: nikdy nemísit se strojovým verdiktem


def test_export_internal_refuses_public_dataset_path():
    import os
    import journalist_tool

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(journalist_tool.__file__)))
    forbidden = os.path.join(repo_root, "src", "data", "psp", "dataset.json")
    with pytest.raises(ValueError):
        export_internal({"leads": []}, forbidden)


def test_export_internal_writes_json(tmp_path):
    out = tmp_path / "interni_prehled.json"
    path = export_internal({"leadCount": 0, "leads": []}, str(out))
    assert json.loads(open(path, encoding="utf-8").read())["leadCount"] == 0
