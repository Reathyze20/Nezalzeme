"""
Rolový obrat v médiích (Fáze 6b) — citace z doby, kdy byl politik v opozici,
vedle jeho hlasování z doby, kdy je (nebo byl) ve vládní straně.

**Proč tahle fáze nese jiné riziko než Slovo vs. Čin / Programová věrnost.**
Stenozáznam a hlasování jsou oficiální, trvalé záznamy Sněmovny — dvojitá
strojová brána (párování + přezkum rozporu) nad nimi stačí bez člověka.
Novinový článek je něčí ZPRÁVA o tom, co bylo řečeno, ne oficiální záznam:
`markdown.find(citace)` dokáže ověřit, že se řetězec v článku fyzicky
nachází, ne že novinář citoval přesně a v kontextu. Riskantní tvrzení tu
není citace samotná — je to enginem sestavená juxtapozice „řekl v opozici /
hlasoval ve vládě" pod skutečným jménem.

Proto: **žádný záznam odsud nejde do `dataset.json` bez `schvaleno = 1`**,
a `schvaleno` nastavuje výhradně `promote_media_lead.py`, jeden lead po
druhém, poté co si operátor přečetl `zdroj_url` sám. `/interni/prehled`
(`journalist_tool.py`) ukazuje VŠECHNY leady, schválené i ne — je to fronta
k rozhodnutí, ne hotový výstup.

Řetěz, na kterém to stojí — každý článek znovupoužitý, ne nově vymyšlený:

    Firecrawl /v1/search -> kandidátní články     [journalist_tool.search_related_articles]
    Firecrawl /v1/scrape -> markdown článku        [fetch_article_markdown, nová cache]
    LLM (přísný prompt) -> přímé citace politika   [extract_attributed_quotes, nové]
      -> ověření: řetězec v markdownu + jméno poblíž + délkový limit
    Registry.political_role_at(id_osoba, datum)    [psp/opendata.py, beze změny]
      -> lead vzniká JEN při skutečné změně strany (opozice <-> vláda)
    find_tisk_candidate -> challenge_pairing       [programova_vernost.py, beze změny]
    latest_final_vote -> resolve_vote              [programova_vernost.py / slovo_cin.py]
    classify_stance -> challenge_mismatch          [slovo_cin.py, beze změny]

**Hranice, kterou tahle fáze nepřekračuje:** `Registry` zná klubové a vládní
příslušnosti jen pro současné volební období (`id_organ=174`, od 3. 11. 2025).
Citát z minulého období (vláda M. Fialy, 2021–2025) by šlo k roli přiřadit
jen ručně vloženým tvrzením typu „ANO bylo do 2025 v opozici" — přesně ten
vzorec, který způsobil incident z 28. 8. 2026 (`INVESTIGATIVE_CASES`, viz
CLAUDE.md). Citáty datované před 3. 11. 2025 se proto vždy zahazují.
"""

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, List, Optional

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

from db import cache_key, now_iso  # noqa: E402
from journalist_tool import search_related_articles  # noqa: E402
from psp.facts import ENGINE_SQLITE_PATH  # noqa: E402
from programova_vernost import (  # noqa: E402
    challenge_pairing,
    find_tisk_candidate,
    latest_final_vote,
)
from slovo_cin import (  # noqa: E402
    PUBLIKOVATELNE_POSTOJE,
    challenge_mismatch,
    classify_stance,
    klub_tally_for_ballot,
    resolve_vote,
)

ENGINE_VERSION = "media-role-flip-v1"
PROMPT_VERSION = "v1"

#: Nejstarší datum, pro které `Registry` zná roli (začátek 10. volebního
#: období). Citáty starší se zahazují — viz docstring modulu.
TERM_START_DATE = date(2025, 11, 3)

#: „Kratší přesná citace je lepší" — stejná disciplína jako
#: `programova_vernost.ZAVAZEK_PROMPT`, tady navíc kvůli fair-use citaci.
MAX_QUOTE_CHARS = 400

#: Jméno politika se musí vyskytovat blízko citace v markdownu — strukturální
#: kontrola navíc k LLM, ne jen důvěra v model.
NAME_PROXIMITY_WINDOW = 300

DEFAULT_LIMIT_CLANKY = 5

_GOVERNMENT_SIDE = {"MINISTER", "COALITION_DEPUTY"}
_OPPOSITION_SIDE = {"OPPOSITION_DEPUTY"}


def _is_government_side(role: str) -> bool:
    return role in _GOVERNMENT_SIDE


def _is_opposition_side(role: str) -> bool:
    return role in _OPPOSITION_SIDE


# --------------------------------------------------------------------------- #
# Rozpoznání osoby
# --------------------------------------------------------------------------- #

def resolve_id_osoba(registry, jmeno: str) -> Optional[str]:
    """Jméno -> `id_osoba` přes `Person.full_name()`. Bez shody `None`, žádné hádání."""
    jmeno_norm = jmeno.strip().casefold()
    for id_osoba, person in registry.people.items():
        if person.full_name().strip().casefold() == jmeno_norm:
            return id_osoba
    return None


# --------------------------------------------------------------------------- #
# Firecrawl /v1/scrape — markdown článku
# --------------------------------------------------------------------------- #

def _scrape_cache_path() -> str:
    return os.path.join(os.path.dirname(ENGINE_SQLITE_PATH), "firecrawl_cache.sqlite")


def _scrape_cache_get(key: str, ttl_seconds: int = 7 * 86400) -> Optional[Dict[str, Any]]:
    conn = None
    try:
        conn = sqlite3.connect(_scrape_cache_path())
        conn.execute(
            "CREATE TABLE IF NOT EXISTS firecrawl_scrape (cache_key TEXT PRIMARY KEY, "
            "payload_json TEXT NOT NULL, cached_at_ts REAL NOT NULL)"
        )
        row = conn.execute(
            "SELECT payload_json, cached_at_ts FROM firecrawl_scrape WHERE cache_key = ?", (key,)
        ).fetchone()
        if row and time.time() - row[1] <= ttl_seconds:
            return json.loads(row[0])
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
    return None


def _scrape_cache_set(key: str, payload: Dict[str, Any]) -> None:
    conn = None
    try:
        conn = sqlite3.connect(_scrape_cache_path())
        conn.execute(
            "CREATE TABLE IF NOT EXISTS firecrawl_scrape (cache_key TEXT PRIMARY KEY, "
            "payload_json TEXT NOT NULL, cached_at_ts REAL NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO firecrawl_scrape VALUES (?, ?, ?)",
            (key, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        if conn:
            conn.close()


def _parse_article_date(metadata: Dict[str, Any]) -> Optional[str]:
    """`YYYY-MM-DD`, jinak `None` — nikdy odhad."""
    raw = (
        metadata.get("publishedTime") or metadata.get("article:published_time")
        or metadata.get("datePublished")
    )
    if not raw:
        return None
    try:
        return str(raw)[:10]
    except Exception:
        return None


def fetch_article_markdown(url: str, api_key: Optional[str] = None, timeout: int = 20) -> Optional[Dict[str, Any]]:
    """
    Firecrawl `/v1/scrape` -> `{"markdown", "medium", "datumClanku"}`.

    `datumClanku` je `None`, když Firecrawl datum publikace nevrátí —
    `build_role_flip_leads` takové citáty zahazuje, nikdy datum neodhaduje.
    """
    api_key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key or not url:
        return None

    cache_key_ = "scrape:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
    cached = _scrape_cache_get(cache_key_)
    if cached is not None:
        return cached

    body = json.dumps({"url": url, "formats": ["markdown"]}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/scrape",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, Exception):
        return None

    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    markdown = data.get("markdown", "")
    if not markdown:
        return None
    metadata = data.get("metadata", {}) or {}

    result = {
        "markdown": markdown,
        "medium": urllib.parse.urlparse(url).netloc,
        "datumClanku": _parse_article_date(metadata),
    }
    _scrape_cache_set(cache_key_, result)
    return result


# --------------------------------------------------------------------------- #
# Extrakce přímých citací (přísná attribuce)
# --------------------------------------------------------------------------- #

QUOTE_EXTRACTION_PROMPT = """# ROLE: extrakce PŘÍMÝCH citací jednoho konkrétního politika

Dostaneš text novinového článku (markdown) a jméno politika. Najdi věty,
které jsou PŘÍMOU, doslovnou citací TOHOTO politika — ne shrnutí, ne
parafráze novináře, ne citace nikoho jiného z článku.

Pravidla:
1. Citace musí být buď v uvozovkách, nebo uvedená jasnou uvozovací větou,
   která jmenuje přímo tohoto politika („uvedl X", „řekl X pro Y", „X: ...").
2. Když článek cituje více lidí, vezmi JEN věty připsané jmenovanému politikovi.
3. `citace` musí být DOSLOVNÝ, nezkrácený úryvek z dodaného textu — žádné
   spojování vět z různých míst, žádná parafráze.
4. Kratší přesná citace je lepší než delší nepřesná. Nejvýš 400 znaků na citaci.
5. Když si nejsi jistý/á, že jde o přímou citaci TOHOTO politika, vynech ji —
   je v pořádku vrátit prázdný seznam.
6. Nejvýš 5 nejvýznamnějších citací z článku.

Vrať POUZE JSON pole:
[{"citace": "<doslovný úryvek z textu>"}]
"""


def _name_near_quote(markdown: str, citace: str, surname: str, window: int = NAME_PROXIMITY_WINDOW) -> bool:
    idx = markdown.find(citace)
    if idx == -1 or not surname:
        return False
    start = max(0, idx - window)
    end = min(len(markdown), idx + len(citace) + window)
    return surname.casefold() in markdown[start:end].casefold()


def extract_attributed_quotes(
    backend, markdown: str, politician_name: str, surname: str, model_name: str
) -> List[Dict[str, Any]]:
    """LLM navrhne citace; každá musí přežít podřetězcovou i jmennou kontrolu."""
    payload = {"POLITIK": politician_name, "CLANEK": markdown[:20000]}
    user_payload = json.dumps(payload, ensure_ascii=False)
    ck = cache_key(model_name, "MRF_CITACE::{}::{}".format(PROMPT_VERSION, user_payload))
    raw = backend.call("MRF_CITACE", QUOTE_EXTRACTION_PROMPT, user_payload, model_name, ck=ck)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []

    out = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        citace = str(item.get("citace", "")).strip()
        if not citace or len(citace) > MAX_QUOTE_CHARS:
            continue
        if markdown.find(citace) == -1:
            continue
        if not _name_near_quote(markdown, citace, surname):
            continue
        out.append({"citace": citace})
    return out


# --------------------------------------------------------------------------- #
# Sestavení leadu
# --------------------------------------------------------------------------- #

def build_record(
    id_osoba: str, politician_name: str, citace: str, zdroj: Dict[str, Any],
    role_pri_citatu: str, tisk_info, final_vote: Dict[str, Any],
    stance: Dict[str, Any], vote: Dict[str, Any], role_pri_hlasovani: str,
    klub_pomer: Optional[Dict[str, int]],
) -> Dict[str, Any]:
    """
    Sestaví lead ve tvaru kompatibilním se `slovo_cin.challenge_mismatch`
    (`receno.citace`, `tisk.nazev`, `postoj`, `hlasovani.hlas/klub/klubPomer`)
    — beze změny té funkce, jen se jí nabídne stejně tvarovaná data.
    """
    if vote["hlas"] == "PRO":
        hlas_smer = "PRO"
    elif vote["hlas"] == "PROTI":
        hlas_smer = "PROTI"
    else:
        hlas_smer = None

    if hlas_smer is None:
        shoda = "NEHLASOVAL"
    elif hlas_smer == stance["postoj"]:
        shoda = "SHODA"
    else:
        shoda = "NESHODA"

    lead_id = "mrf-" + hashlib.sha1(
        (id_osoba + "::" + citace + "::" + final_vote["idHlasovani"]).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "id": lead_id,
        "idOsoba": id_osoba,
        "politik": politician_name,
        "receno": {
            "citace": citace,
            "rolePriCitatu": role_pri_citatu,
            "zdroj": zdroj,
        },
        "postoj": stance["postoj"],
        "postojOduvodneni": stance["oduvodneni"],
        "tisk": {"cislo": tisk_info.cislo, "nazev": tisk_info.cely_nazev, "url": tisk_info.url},
        "hlasovani": {
            "idHlasovani": final_vote["idHlasovani"],
            "url": final_vote["url"],
            "cislo": final_vote["cisloHlasovani"],
            "schuze": final_vote["schuze"],
            "vysledekSlovy": final_vote["vysledekSlovy"],
            "prijat": final_vote["prijat"],
            "historieUrl": final_vote["historieUrl"],
            "hlas": vote["hlas"],
            "omluven": vote["omluven"],
            "klub": vote["klub"],
            "klubPomer": klub_pomer,
            "rolePriHlasovani": role_pri_hlasovani,
        },
        "shoda": shoda,
    }


def store_record(conn, record: Dict[str, Any], model_name: str, parovani_plati: bool, rozpor_mizi: bool) -> None:
    """
    `INSERT OR REPLACE` na stejné `id` (stejná osoba+citace+hlasování) nesmí
    smazat dřívější schválení — `schvaleno`/`schvaleno_at` se proto přebírají
    z existujícího řádku přes `COALESCE`, ne přepisují natvrdo.
    """
    conn.execute(
        "INSERT OR REPLACE INTO media_role_flip "
        "(id, id_osoba, citace, zdroj_url, medium, datum_clanku, tisk, id_hlasovani, "
        " postoj, hlas, shoda, parovani_plati, rozpor_mizi, zaznam_json, schvaleno, "
        " schvaleno_at, produced_at, model_name, engine_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "        COALESCE((SELECT schvaleno FROM media_role_flip WHERE id = ?), 0), "
        "        (SELECT schvaleno_at FROM media_role_flip WHERE id = ?), ?, ?, ?)",
        (
            record["id"], record["idOsoba"], record["receno"]["citace"],
            record["receno"]["zdroj"]["url"], record["receno"]["zdroj"]["medium"],
            record["receno"]["zdroj"]["datumClanku"], record["tisk"]["cislo"],
            record["hlasovani"]["idHlasovani"], record["postoj"], record["hlasovani"]["hlas"],
            record["shoda"], 1 if parovani_plati else 0, 1 if rozpor_mizi else 0,
            json.dumps(record, ensure_ascii=False), record["id"], record["id"],
            now_iso(), model_name, ENGINE_VERSION,
        ),
    )
    conn.commit()


def load_leads(conn) -> List[Dict[str, Any]]:
    """Všechny leady (schválené i ne) pro `/interni/prehled` — fronta k rozhodnutí."""
    rows = conn.execute(
        "SELECT id, zaznam_json, schvaleno, schvaleno_at, parovani_plati, rozpor_mizi "
        "FROM media_role_flip ORDER BY produced_at DESC"
    ).fetchall()
    out = []
    for row in rows:
        record = json.loads(row["zaznam_json"])
        record["schvaleno"] = bool(row["schvaleno"])
        record["schvalenoAt"] = row["schvaleno_at"]
        record["parovaniPlati"] = bool(row["parovani_plati"])
        record["rozporMizi"] = bool(row["rozpor_mizi"])
        out.append(record)
    return out


def approve_lead(conn, lead_id: str) -> bool:
    """Nastaví `schvaleno=1` pro jediný lead. `False`, pokud `lead_id` neexistuje."""
    cur = conn.execute(
        "UPDATE media_role_flip SET schvaleno = 1, schvaleno_at = ? WHERE id = ?",
        (now_iso(), lead_id),
    )
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Orchestrace
# --------------------------------------------------------------------------- #

def build_role_flip_leads(
    politician_names: List[str], conn, registry, tisky_registry, client, backend,
    firecrawl_key: Optional[str], model_name: str, limit_clanky: int = DEFAULT_LIMIT_CLANKY,
) -> List[Dict[str, Any]]:
    """Pro každé jméno: vyhledá články, extrahuje citace, spáruje s hlasováním."""
    organ = str(registry.term_organ_id)
    tisky_pro_prompt = [
        {"cislo": info.cislo, "nazev": info.cely_nazev}
        for info in tisky_registry.all_for_organ(organ)
    ]

    results = []
    for jmeno in politician_names:
        id_osoba = resolve_id_osoba(registry, jmeno)
        if not id_osoba:
            print(f"  [-] {jmeno}: nenalezen v registru")
            continue
        person = registry.people[id_osoba]
        surname = person.prijmeni

        articles = search_related_articles(f"{jmeno} rozhovor vyjádření", api_key=firecrawl_key, limit=limit_clanky)
        for article in articles:
            scraped = fetch_article_markdown(article["url"], api_key=firecrawl_key)
            if not scraped or not scraped.get("datumClanku"):
                continue
            try:
                clanek_datum = datetime.strptime(scraped["datumClanku"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if clanek_datum < TERM_START_DATE:
                continue

            role_pri_citatu = registry.political_role_at(id_osoba, clanek_datum)["role"]
            if not (_is_government_side(role_pri_citatu) or _is_opposition_side(role_pri_citatu)):
                continue

            quotes = extract_attributed_quotes(backend, scraped["markdown"], jmeno, surname, model_name)
            zdroj = {
                "url": article["url"], "medium": scraped["medium"], "datumClanku": scraped["datumClanku"],
            }

            for quote in quotes:
                kandidat = find_tisk_candidate(backend, quote["citace"], tisky_pro_prompt, model_name)
                if not kandidat:
                    continue
                tisk_info = tisky_registry.get_tisk(kandidat["cislo"], organ=organ)
                if not tisk_info:
                    continue

                final_vote = latest_final_vote(client, kandidat["cislo"], conn, id_organ=organ)
                if not final_vote or not final_vote.get("idHlasovani"):
                    continue
                vote_row = conn.execute(
                    "SELECT datum, cas FROM hlasovani WHERE id_hlasovani = ?",
                    (final_vote["idHlasovani"],),
                ).fetchone()
                if not vote_row:
                    continue
                try:
                    hlasovani_datum = datetime.strptime(vote_row["datum"], "%d.%m.%Y").date()
                except ValueError:
                    continue

                role_pri_hlasovani = registry.political_role_at(id_osoba, hlasovani_datum)["role"]
                # Lead vzniká, jen když se strana skutečně liší mezi citátem a hlasováním.
                if _is_government_side(role_pri_citatu) == _is_government_side(role_pri_hlasovani):
                    continue
                if not (_is_government_side(role_pri_hlasovani) or _is_opposition_side(role_pri_hlasovani)):
                    continue

                id_poslanec = registry.deputy_id(id_osoba)
                vote = resolve_vote(
                    client, conn, final_vote["idHlasovani"], id_osoba, id_poslanec,
                    vote_row["datum"], vote_row["cas"], id_organ=organ,
                )
                if not vote:
                    continue

                stance = classify_stance(backend, {"rawSpan": quote["citace"]}, tisk_info.cely_nazev, model_name)
                # NEUTRALNI/NEURCITELNE nese nulovou informaci o postoji k
                # tisku — dál zpracovaný by z něj vznikla nesmyslná
                # SHODA/NESHODA (stejná pojistka jako `slovo_cin.py`).
                if stance["postoj"] not in PUBLIKOVATELNE_POSTOJE:
                    continue
                klub_pomer = klub_tally_for_ballot(
                    conn, registry, final_vote["idHlasovani"], vote.get("klub") or "", hlasovani_datum,
                )

                record = build_record(
                    id_osoba, jmeno, quote["citace"], zdroj, role_pri_citatu, tisk_info,
                    final_vote, stance, vote, role_pri_hlasovani, klub_pomer,
                )

                prezkum_parovani = challenge_pairing(
                    backend, quote["citace"], tisk_info.cely_nazev, kandidat["zduvodneni"], model_name,
                )

                rozpor_mizi = True
                if record["shoda"] == "NESHODA":
                    obhajoba = challenge_mismatch(backend, record, model_name)
                    rozpor_mizi = obhajoba["rozporMizi"]
                    record["obhajoba"] = obhajoba["vyklad"]

                record["parovani"] = prezkum_parovani["vyklad"]
                store_record(
                    conn, record, model_name,
                    parovani_plati=prezkum_parovani["parovaniPlati"], rozpor_mizi=rozpor_mizi,
                )
                results.append(record)

    return results


def main() -> None:
    import argparse

    from db import open_engine_db
    from psp.client import PspClient
    from psp.opendata import Registry
    from psp.tisky import TiskyRegistry

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poslanec", action="append", required=True, dest="poslanci",
                        help="Celé jméno politika (opakovatelné).")
    parser.add_argument("--limit-clanky", type=int, default=DEFAULT_LIMIT_CLANKY)
    parser.add_argument("--backend", choices=["auto", "gemini", "api", "jsonl"], default="auto")
    args = parser.parse_args()

    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not firecrawl_key:
        print("FIRECRAWL_API_KEY chybí v .env — bez něj nemá tenhle nástroj co dělat.")
        return

    from claims import CLAIM_EXTRACTION_MODEL
    from model_backend import ApiBackend, GeminiBackend, JsonlBackend

    conn = open_engine_db()
    backend_choice = args.backend
    if backend_choice == "auto":
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            backend_choice = "gemini"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            backend_choice = "api"
        else:
            backend_choice = "gemini"

    if backend_choice == "jsonl":
        backend = JsonlBackend(conn)
    elif backend_choice == "gemini":
        backend = GeminiBackend(conn)
    else:
        backend = ApiBackend(conn)
    model_name = getattr(backend, "default_model", CLAIM_EXTRACTION_MODEL)

    client = PspClient()
    registry = Registry.load(client)
    tisky_registry = TiskyRegistry.load(client)

    leads = build_role_flip_leads(
        args.poslanci, conn, registry, tisky_registry, client, backend,
        firecrawl_key, model_name, limit_clanky=args.limit_clanky,
    )
    print(f"rolový obrat: {len(leads)} nových/aktualizovaných leadů. "
          f"Schválení: python pipeline/promote_media_lead.py --lead-id <id> (viz /interni/prehled)")


if __name__ == "__main__":
    main()
