"""
Novinářský nástroj (Fáze 6) — INTERNÍ, nikdy ne veřejná značka.

Pásmo NLI 0,50 až `run_pipeline.NLI_CONTRADICTION_THRESHOLD` (0,80) tribunál
nikdy nevidí — `phase_tribunal()` bere jen páry se skóre >= 0,80. Tenhle
modul je jediné legitimní místo, kde se tohle pásmo vůbec čte: jde o slabší
signál, plný falešných shod (viz `za-v-erej-ek-jsme-do-li-transient-hinton.md`,
oddíl "Kritické zhodnocení návrhu", bod 1), takže nikdy nesmí obejít
tribunál a skončit v `verdicts`/`dataset.json` jako hotové obvinění —
přesně vzorec incidentu z 28. 8. 2026 popsaného v CLAUDE.md. Tenhle modul
do `verdicts` nezapisuje nic a `store_verdict()`/`db.py` vůbec nevolá.

Výstup je samostatný soubor `pipeline/data/interni_prehled.json`, mimo
`src/data/psp/` — `export_web.py` ho nikdy nenačte, protože ho nikdy
neimportuje ani neprochází ten adresář. Web ho čte jen přes interní route
`/interni/prehled`, zamčenou middlewarem (HTTP Basic Auth), nikde
neodkazovanou z veřejné navigace.

Ke každému kandidátovi modul přidává (vše volitelné, bez sítě/klíče prostě
chybí, pipeline nespadne):
  - Hlídač státu (`psp/hlidac_client.py`) — historické funkce a firemní vazby
    mluvčího, pro křížovou kontrolu kontextu.
  - Firecrawl (`search_related_articles`) — dosavadní mediální pokrytí tématu.
  - makrokontext (`macro_context.py`) — ekonomický rámec měsíce druhého výroku.

Nic z tohoto se nezobrazuje jako důkaz rozporu — je to podklad k prošetření
pro člověka, ne strojový verdikt.
"""

import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import dotenv
    _root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _env_file = os.path.join(_root_dir, ".env")
    if os.path.exists(_env_file):
        dotenv.load_dotenv(_env_file)
    else:
        dotenv.load_dotenv()
except Exception:
    pass

from psp.facts import ENGINE_SQLITE_PATH  # noqa: E402
from psp.hlidac_client import HlidacClient  # noqa: E402

try:
    from macro_context import get_macro_context
    _MACRO_AVAILABLE = True
except ImportError:
    _MACRO_AVAILABLE = False
    def get_macro_context(month, **kw):  # type: ignore
        return {}

# Musí zůstat pod run_pipeline.NLI_CONTRADICTION_THRESHOLD (0,80) — to je
# spodní hrana tribunálu. Nejde importovat přímo (run_pipeline.py při
# importu strhne torch/transformers přes claims.py/nli.py), takže se
# hodnota drží ručně v souladu; při změně prahu v run_pipeline.py uprav i tuhle.
NLI_BAND_MIN = 0.50
NLI_BAND_MAX = 0.80
MIN_SIMILARITY_THRESHOLD = 0.60

# Stejné procedurální fráze jako `run_pipeline.phase_tribunal` — kandidát
# postavený na pozdravu nebo hlasovacím protokolu není leadem k prošetření.
_PROCEDURAL_PHRASES = (
    "hlasování číslo", "hlasování č.", "návrh byl přijat", "návrh nebyl přijat",
    "návrh usnesení byl", "zahajuji hlasování", "končím hlasování",
    "stiskněte tlačítko", "předávám slovo", "omlouvám se za",
    "vejdu se do dvou minut", "děkuji za slovo", "přeji hezké",
)

DEFAULT_OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "interni_prehled.json"
)


# --------------------------------------------------------------------------- #
# Kandidátní leady z pásma 0,50–0,80
# --------------------------------------------------------------------------- #

def _is_procedural(claim: Dict[str, Any]) -> bool:
    raw = (claim.get("rawSpan") or "").lower() + " " + (claim.get("subject") or "").lower()
    return (claim.get("claimCategory") or claim.get("claim_category") or "") == "PROCEDURAL" or any(
        p in raw for p in _PROCEDURAL_PHRASES
    )


def candidate_leads(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Vrátí syrové řádky z `nli_results`/`candidate_pairs`/`claims` v pásmu
    NLI_BAND_MIN <= contradiction < NLI_BAND_MAX, se stejnými filtry jako
    tribunál (procedurální tvrzení, souhlas se svým vlastním výrokem).
    Nedotýká se `verdicts`.
    """
    rows = conn.execute(
        "SELECT n.pair_id, n.contradiction, n.nli_relation, "
        "       p.claim_id_a, p.claim_id_b, p.similarity_score "
        "FROM nli_results n JOIN candidate_pairs p ON n.pair_id = p.pair_id "
        "WHERE n.contradiction >= ? AND n.contradiction < ? "
        "  AND p.similarity_score >= ? AND n.nli_relation = 'CONTRADICTION' "
        "ORDER BY n.contradiction DESC",
        (NLI_BAND_MIN, NLI_BAND_MAX, MIN_SIMILARITY_THRESHOLD),
    ).fetchall()

    leads = []
    for row in rows:
        row_a = conn.execute(
            "SELECT claim_json, message_id FROM claims WHERE claim_id = ?",
            (row["claim_id_a"],),
        ).fetchone()
        row_b = conn.execute(
            "SELECT claim_json, message_id FROM claims WHERE claim_id = ?",
            (row["claim_id_b"],),
        ).fetchone()
        if not row_a or not row_b:
            continue
        if row_a["message_id"] == row_b["message_id"]:
            continue

        claim_a = json.loads(row_a["claim_json"])
        claim_b = json.loads(row_b["claim_json"])
        if _is_procedural(claim_a) or _is_procedural(claim_b):
            continue

        leads.append({
            "pairId": row["pair_id"],
            "contradiction": float(row["contradiction"]),
            "similarity": float(row["similarity_score"]),
            "claimA": claim_a,
            "claimB": claim_b,
            "messageIdA": row_a["message_id"],
            "messageIdB": row_b["message_id"],
        })
    return leads


def _message_view(msg: Dict[str, Any]) -> Dict[str, Any]:
    src = msg.get("source") or {}
    return {
        "messageId": msg.get("messageId"),
        "speaker": msg.get("speaker"),
        "idOsoba": src.get("idOsoba"),
        "party": msg.get("party"),
        "date": msg.get("date"),
        "stenoUrl": src.get("stenoUrl") or "",
    }


def build_lead_record(lead: Dict[str, Any], msg_map: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Sestaví jeden zobrazitelný lead. `None`, pokud chybí zdrojové vystoupení."""
    msg_a = msg_map.get(lead["messageIdA"])
    msg_b = msg_map.get(lead["messageIdB"])
    if not msg_a or not msg_b:
        return None

    claim_a, claim_b = lead["claimA"], lead["claimB"]
    return {
        "leadId": lead["pairId"],
        "contradiction": round(lead["contradiction"], 4),
        "similarity": round(lead["similarity"], 4),
        "vyrokA": {
            "citace": claim_a.get("rawSpan", ""),
            "tvrzeni": "{subject} {predicate} {object}".format(
                subject=claim_a.get("subject", ""),
                predicate=claim_a.get("predicate", ""),
                object=claim_a.get("object", ""),
            ).strip(),
            "casovyRamec": claim_a.get("timeFrame", ""),
            **_message_view(msg_a),
        },
        "vyrokB": {
            "citace": claim_b.get("rawSpan", ""),
            "tvrzeni": "{subject} {predicate} {object}".format(
                subject=claim_b.get("subject", ""),
                predicate=claim_b.get("predicate", ""),
                object=claim_b.get("object", ""),
            ).strip(),
            "casovyRamec": claim_b.get("timeFrame", ""),
            **_message_view(msg_b),
        },
        "hlidacStatu": None,
        "makrokontext": None,
        "clanky": [],
    }


# --------------------------------------------------------------------------- #
# Obohacení: Hlídač státu
# --------------------------------------------------------------------------- #

def enrich_with_hlidac(leads: List[Dict[str, Any]], client: Optional[HlidacClient]) -> None:
    """Doplní `hlidacStatu` u obou stran leadu. Bez klíče/shody necháno `None`."""
    if client is None:
        return
    cache: Dict[str, Any] = {}
    for lead in leads:
        for side in ("vyrokA", "vyrokB"):
            osoba = lead[side]
            key = osoba.get("idOsoba") or osoba.get("speaker")
            if not key:
                continue
            if key not in cache:
                try:
                    enrichment = client.enrich_speaker(osoba.get("speaker", ""), psp_id=osoba.get("idOsoba"))
                except Exception:
                    enrichment = None
                cache[key] = enrichment
            enrichment = cache[key]
            if enrichment:
                osoba["hlidacProfil"] = {
                    "url": enrichment.profile_url,
                    "funkce": [
                        {"role": r.role, "organizace": r.organization, "od": r.since, "do": r.until}
                        for r in enrichment.historical_roles
                    ],
                    "firemniVazby": enrichment.corporate_entities,
                }


# --------------------------------------------------------------------------- #
# Obohacení: makrokontext
# --------------------------------------------------------------------------- #

def attach_macro_context(leads: List[Dict[str, Any]]) -> None:
    """Doplní `makrokontext` z měsíce novějšího výroku (claimA je vždy ten aktuální)."""
    if not _MACRO_AVAILABLE:
        return
    cache: Dict[str, Any] = {}
    for lead in leads:
        date = lead["vyrokA"].get("date") or ""
        month = date[:7]
        if not month:
            continue
        if month not in cache:
            try:
                cache[month] = get_macro_context(month)
            except Exception:
                cache[month] = {}
        macro = cache[month]
        if macro.get("data_sources"):
            lead["makrokontext"] = macro


# --------------------------------------------------------------------------- #
# Obohacení: Firecrawl — dosavadní mediální pokrytí
# --------------------------------------------------------------------------- #

def _firecrawl_cache_path() -> str:
    return os.path.join(os.path.dirname(ENGINE_SQLITE_PATH), "firecrawl_cache.sqlite")


def _firecrawl_cache_get(key: str, ttl_seconds: int = 7 * 86400) -> Optional[List[Dict[str, Any]]]:
    conn = None
    try:
        conn = sqlite3.connect(_firecrawl_cache_path())
        conn.execute(
            "CREATE TABLE IF NOT EXISTS firecrawl_search (cache_key TEXT PRIMARY KEY, "
            "results_json TEXT NOT NULL, cached_at_ts REAL NOT NULL)"
        )
        row = conn.execute(
            "SELECT results_json, cached_at_ts FROM firecrawl_search WHERE cache_key = ?", (key,)
        ).fetchone()
        if row and time.time() - row[1] <= ttl_seconds:
            return json.loads(row[0])
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
    return None


def _firecrawl_cache_set(key: str, results: List[Dict[str, Any]]) -> None:
    conn = None
    try:
        conn = sqlite3.connect(_firecrawl_cache_path())
        conn.execute(
            "CREATE TABLE IF NOT EXISTS firecrawl_search (cache_key TEXT PRIMARY KEY, "
            "results_json TEXT NOT NULL, cached_at_ts REAL NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO firecrawl_search VALUES (?, ?, ?)",
            (key, json.dumps(results, ensure_ascii=False), time.time()),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        if conn:
            conn.close()


def search_related_articles(
    query: str, api_key: Optional[str] = None, limit: int = 5, timeout: int = 15
) -> List[Dict[str, Any]]:
    """
    Firecrawl `/v1/search` — dosavadní mediální pokrytí tématu, pro kontext
    novináři, ne jako důkaz. Bez klíče vrátí `[]` (pipeline nespadne).
    """
    api_key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key or not query.strip():
        return []

    cache_key = "search:" + hashlib.sha256((query + f"::{limit}").encode("utf-8")).hexdigest()
    cached = _firecrawl_cache_get(cache_key)
    if cached is not None:
        return cached

    body = json.dumps({"query": query, "limit": limit}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/search",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, Exception):
        return []

    raw_results = payload.get("data", []) if isinstance(payload, dict) else []
    results = [
        {
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "popis": item.get("description", ""),
        }
        for item in raw_results
        if item.get("url")
    ]
    _firecrawl_cache_set(cache_key, results)
    return results


def attach_articles(leads: List[Dict[str, Any]], api_key: Optional[str] = None) -> None:
    if not (api_key or os.environ.get("FIRECRAWL_API_KEY", "")):
        return
    for lead in leads:
        subject = lead["vyrokA"].get("speaker", "")
        topic = lead["vyrokA"].get("tvrzeni", "")[:80]
        if not subject or not topic:
            continue
        lead["clanky"] = search_related_articles(f"{subject} {topic}", api_key=api_key)


# --------------------------------------------------------------------------- #
# Sestavení a export
# --------------------------------------------------------------------------- #

def build_internal_overview(
    conn: sqlite3.Connection,
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    hlidac_client: Optional[HlidacClient] = None,
    firecrawl_key: Optional[str] = None,
    rolovy_obrat: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Sestaví interní přehled leadů z pásma NLI 0,50–0,80.

    `pairs` je `run_pipeline.load_corpus()` výstup — (debate, message)
    dvojice ze staženého vzorku. Nic tady se nezapisuje do `verdicts` ani
    `src/data/psp/`.

    `rolovy_obrat` (nepovinné) je výstup `media_role_flip.load_leads()` —
    VŠECHNY uložené leady, schválené i ne (fronta k rozhodnutí operátora,
    `id`/`schvaleno` u každého). Publikaci na veřejný web dělá výhradně
    `promote_media_lead.py` + `export_web.py`, tady se jen zobrazuje stav.
    """
    msg_map = {msg["messageId"]: msg for _, msg in pairs}

    raw_leads = candidate_leads(conn)
    records = [r for r in (build_lead_record(lead, msg_map) for lead in raw_leads) if r]

    enrich_with_hlidac(records, hlidac_client)
    attach_macro_context(records)
    attach_articles(records, api_key=firecrawl_key)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "nliBand": [NLI_BAND_MIN, NLI_BAND_MAX],
        "poznamka": (
            "INTERNÍ PODKLAD K PROŠETŘENÍ. Pásmo NLI 0,50–0,80 tribunál "
            "nikdy nezpracovává — nejde o ověřený rozpor, ale o slabší "
            "signál pro novináře. Nepublikovat bez vlastního ověření zdroje."
        ),
        "leadCount": len(records),
        "hlidacStatuZapnuto": hlidac_client is not None and bool(hlidac_client.api_token),
        "firecrawlZapnuto": bool(firecrawl_key or os.environ.get("FIRECRAWL_API_KEY", "")),
        "leads": records,
        "rolovyObrat": rolovy_obrat or [],
    }


def export_internal(overview: Dict[str, Any], path: str = DEFAULT_OUTPUT_PATH) -> str:
    """Zapíše přehled na `path`. Odmítne zapsat cokoliv pod `src/data/psp/`."""
    normalized = os.path.normpath(os.path.abspath(path))
    forbidden = os.path.normpath(os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "data", "psp")
    ))
    if normalized.startswith(forbidden):
        raise ValueError(
            "interní přehled se nesmí zapisovat do src/data/psp/ — "
            "jediný legitimní zápis tam je export_web.py"
        )
    os.makedirs(os.path.dirname(normalized), exist_ok=True)
    with open(normalized, "w", encoding="utf-8") as handle:
        json.dump(overview, handle, ensure_ascii=False, indent=2)
    return normalized


def main() -> None:
    import argparse
    from db import open_engine_db
    from run_pipeline import load_corpus  # heavy import (torch přes claims.py/nli.py) — jen tady, ne na modulové úrovni

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schuze", type=int, default=None)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--poslanec", action="append", default=[], dest="poslanci",
                        help="Rolový obrat v médiích (Fáze 6b) pro tohle jméno (opakovatelné).")
    parser.add_argument("--video", action="append", default=[], dest="videa",
                        help="Rolový obrat z videa (Fáze 6c), URL už zpracovaného přes "
                             "prepare_video_speakers.py + tag_video_speaker.py (opakovatelné).")
    args = parser.parse_args()

    conn = open_engine_db()
    pairs = load_corpus(schuze=args.schuze)

    hlidac_client = HlidacClient() if os.environ.get("HLIDAC_STATU_TOKEN") else None
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "")

    from media_role_flip import load_leads

    if args.poslanci and not firecrawl_key:
        print("  (FIRECRAWL_API_KEY chybí — --poslanec se přeskakuje)")
        args.poslanci = []

    if args.poslanci or args.videa:
        from media_role_flip import build_role_flip_leads, build_role_flip_leads_from_video
        from psp.client import PspClient
        from psp.opendata import Registry
        from psp.tisky import TiskyRegistry
        from claims import CLAIM_EXTRACTION_MODEL
        from model_backend import ApiBackend, GeminiBackend

        client = PspClient()
        registry = Registry.load(client)
        tisky_registry = TiskyRegistry.load(client)
        mrf_backend = (
            GeminiBackend(conn)
            if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            else ApiBackend(conn)
        )
        mrf_model = getattr(mrf_backend, "default_model", CLAIM_EXTRACTION_MODEL)
        if args.poslanci:
            build_role_flip_leads(
                args.poslanci, conn, registry, tisky_registry, client, mrf_backend,
                firecrawl_key, mrf_model,
            )
        if args.videa:
            build_role_flip_leads_from_video(
                args.videa, conn, registry, tisky_registry, client, mrf_backend, mrf_model,
            )

    rolovy_obrat = load_leads(conn)

    overview = build_internal_overview(
        conn, pairs, hlidac_client=hlidac_client, rolovy_obrat=rolovy_obrat,
    )
    out_path = export_internal(overview, args.output)

    print(f"novinářský nástroj: {overview['leadCount']} leadů v pásmu "
          f"{NLI_BAND_MIN}–{NLI_BAND_MAX} -> {out_path}")
    if not overview["hlidacStatuZapnuto"]:
        print("  (HLIDAC_STATU_TOKEN chybí — bez obohacení Hlídačem státu)")
    if not overview["firecrawlZapnuto"]:
        print("  (FIRECRAWL_API_KEY chybí — bez vyhledání souvisejících článků)")
    if overview["rolovyObrat"]:
        neschvaleno = sum(1 for lead in overview["rolovyObrat"] if not lead["schvaleno"])
        print(f"  Rolový obrat: {len(overview['rolovyObrat'])} leadů, {neschvaleno} čeká na schválení "
              f"(python pipeline/promote_media_lead.py --lead-id <id>)")


if __name__ == "__main__":
    main()
