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
    is_source_allowed(url)                         [source_ranking.py, Fáze 6e — blokuje tier 4/5]
    _looks_like_listing_page(url)                  [Fáze 6f — přeskočí téma/tag/přehled dřív, než se scrapuje]
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
from source_ranking import is_source_allowed  # noqa: E402
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
    """Jméno -> `id_osoba` přes `Person.full_name`. Bez shody `None`, žádné hádání."""
    jmeno_norm = jmeno.strip().casefold()
    for id_osoba, person in registry.people.items():
        if person.full_name.strip().casefold() == jmeno_norm:
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


_TIME_DATETIME_RE = re.compile(r'<time[^>]*\bdatetime="(\d{4}-\d{2}-\d{2})[^"]*"')


def _valid_past_date(raw: Optional[str]) -> Optional[str]:
    """`YYYY-MM-DD`, ověřené jako platné a ne v budoucnosti, jinak `None`."""
    if not raw:
        return None
    try:
        parsed = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    if parsed > date.today():
        return None
    return parsed.isoformat()


def _parse_date_from_time_tag(html: str) -> Optional[str]:
    """
    Záložní zdroj data, když ho Firecrawl nevrátí ve strukturovaných meta
    tazích (ověřeno živě: běžné u českých zpravodajských webů —
    seznamzpravy.cz/respekt.cz/ct24 apod. datum v `<head>` metadatech
    nemají, ale mají ho v `<time datetime="...">` přímo v těle stránky).
    Bere PRVNÍ takový element v dokumentu — u zpravodajských CMS to
    spolehlivě odpovídá datu vlastního článku (ověřeno na živém příkladu:
    další `<time>` prvky na stránce patří k „mohlo by vás zajímat"
    dlaždicím níž, ne k článku samotnému). Pořád čtení skutečného
    strukturovaného HTML5 elementu, ne hádání data z volného textu —
    proto se to nepočítá jako odhad ve smyslu zákazu výš. Datum v
    budoucnosti (špatně zachycený `<time>` prvek) se zahodí jako
    nedůvěryhodné, ne provizorně přijme.
    """
    match = _TIME_DATETIME_RE.search(html)
    if not match:
        return None
    return _valid_past_date(match.group(1))


def _parse_date_with_htmldate(html: str) -> Optional[str]:
    """
    Druhý záložní zdroj, pro weby, které `<time datetime="...">` vůbec
    nepoužívají (ověřeno živě: info.cz, ct24.ceskatelevize.cz a další —
    ani strukturovaná meta, ani tenhle konkrétní HTML5 vzor). `htmldate`
    (nezávislá, hodně používaná knihovna z `trafilatura` ekosystému) zkouší
    víc strukturovaných zdrojů najednou (JSON-LD, Open Graph, další HTML5
    datové vzory, vzor v URL), než bychom sami udrželi jedním regexem na
    doménu.

    Voláno záměrně s `extensive_search=False`: výchozí režim knihovny má
    fallback na hledání data ve VOLNÉM TEXTU stránky, a přesně tohle jsme
    u vlastního regexu na `<time>` už jednou živě nachytali jako nebezpečné
    — reálný scrape jinam vrátil datum z „mohlo by vás zajímat" panelu, ne
    z článku samotného (viz `_parse_date_from_time_tag`). Konzervativní
    režim čte jen strukturovaná pole — stejná disciplína jako zbytek
    modulu, nikdy odhad z volného textu.

    Nepovinná závislost — bez nainstalovaného `htmldate` se krok tiše
    přeskočí, žádná nová tvrdá závislost na běhu bez něj.
    """
    try:
        from htmldate import find_date
    except ImportError:
        return None
    try:
        raw = find_date(html, extensive_search=False, outputformat="%Y-%m-%d")
    except Exception:
        return None
    return _valid_past_date(raw)


def _parse_date_from_html(html: str) -> Optional[str]:
    """
    Oba záložní zdroje data z HTML, v pořadí levnější/přesnější napřed:
    `<time datetime>` (`_parse_date_from_time_tag`), a jen když ten nic
    nenajde, `htmldate` v konzervativním režimu (`_parse_date_with_htmldate`).
    """
    return _parse_date_from_time_tag(html) or _parse_date_with_htmldate(html)


def _no_date_reason(metadata: Dict[str, Any], html: str) -> str:
    """
    Krátký diagnostický popis, PROČ `datumClanku` vyšlo `None` — jen do
    keše vedle výsledku, nikdy se nepoužívá k rozhodování (na rozdíl od
    `datumClanku` samotného, který jediný řídí, jestli citát z téhle
    stránky přežije `build_role_flip_leads`). Zjištěno živou dávkovou
    diagnózou nad 8 poslanci (2026-08-28, viz analýza v konverzaci): bez
    tohohle záznamu nejde z keše zpětně rozlišit „stránka fakt nemá <time>
    tag" od „htmldate ho v konzervativním režimu zahodil", a stejná
    analýza příště by musela dělat nové (a drahé) síťové volání jen kvůli
    tomuhle rozlišení.
    """
    ma_meta_klic = any(
        metadata.get(k) for k in ("publishedTime", "article:published_time", "datePublished")
    )
    ma_time_tag = bool(_TIME_DATETIME_RE.search(html))
    return ",".join([
        "meta:nevalidni" if ma_meta_klic else "meta:prazdna",
        "time-tag:nevalidni" if ma_time_tag else "time-tag:chybi",
        "htmldate:bez-vysledku",
    ])


_LISTING_HOSTS = {"youtube.com", "facebook.com", "m.facebook.com"}
_LISTING_PATH_MARKERS = ("/tema/", "/tag/", "/tagy/", "/stitky/")


def _looks_like_listing_page(url: str) -> bool:
    """
    Konzervativní blacklist stránek, které STRUKTURÁLNĚ nemají vlastní
    datum publikace (téma/tag/přehled, video/sociální síť) — vyřazeno ještě
    před Firecrawl `/v1/scrape`, aby se neplýtval kredit na něco, co
    `build_role_flip_leads` stejně zahodí kvůli chybějícímu `datumClanku`.
    Ověřeno na živých datech (2026-08-28, dávka 8 poslanců): 22 ze 45
    kandidátních URL bylo přesně tohohle typu.

    Záměrně ÚZKÝ seznam, ne obecné pravidlo typu „jeden segment cesty" —
    stejná dávková diagnóza ukázala, že vzory jako `archiv.hn.cz/c1-NNNNNNNN-slug`,
    `cnn.iprima.cz/slug-NNNNNN` nebo `*.gov.cz/.../slug-DDMMYYYY` vypadají
    podobně "ploše" jako přehledová stránka, ale jsou to skutečné datované
    články. Cena falešného zamítnutí tady NENÍ nulová (na rozdíl od
    `source_ranking.is_source_allowed`, kde další článek je zadarmo) —
    proto radši nechat pár skutečných přehledových stránek projít dál (o
    řádek níž je stejně zahodí chybějící `datumClanku`), než omylem
    přeskočit reálný článek.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host in _LISTING_HOSTS:
        return True
    path = parsed.path.lower()
    if any(marker in path for marker in _LISTING_PATH_MARKERS):
        return True
    if path.rstrip("/") == "/aktualne":
        return True
    return False


def fetch_article_markdown(url: str, api_key: Optional[str] = None, timeout: int = 20) -> Optional[Dict[str, Any]]:
    """
    Firecrawl `/v1/scrape` -> `{"markdown", "medium", "datumClanku"}`.

    Datum se zkusí nejdřív ze strukturovaných meta tagů (`_parse_article_date`),
    a chybí-li tam (běžné u českých webů), z HTML přes `_parse_date_from_html`
    — ten sám zkusí nejdřív `<time datetime="...">`, a bez něj `htmldate`
    v konzervativním režimu. Všechny tři jsou čtení skutečného strukturovaného
    pole ze stránky, nikdy odhad z volného textu článku. Selžou-li všechny,
    `datumClanku` je `None` a `build_role_flip_leads` takové citáty zahazuje.
    """
    api_key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key or not url:
        return None

    cache_key_ = "scrape:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
    cached = _scrape_cache_get(cache_key_)
    if cached is not None:
        return cached

    body = json.dumps({"url": url, "formats": ["markdown", "html"]}).encode("utf-8")
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
    html = data.get("html", "") or ""
    datum = _parse_article_date(metadata) or _parse_date_from_html(html)

    result = {
        "markdown": markdown,
        "medium": urllib.parse.urlparse(url).netloc,
        "datumClanku": datum,
    }
    if not datum:
        result["datumDuvodChybi"] = _no_date_reason(metadata, html)
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
# Extrakce citací z videa (Fáze 6c) — mluvčí už ověřen diarizací + ručním
# přiřazením v `tag_video_speaker.py`, netřeba znovu kontrolovat "čí je to
# citace" jako u článků (`_name_near_quote`) — všechen dodaný text patří
# jednomu mluvčímu z konstrukce (filtr podle `speaker_label` v
# `video_diarization.merge_transcript_with_diarization`).
# --------------------------------------------------------------------------- #

VIDEO_QUOTE_EXTRACTION_PROMPT = """# ROLE: extrakce citovatelných výroků z přepisu mluvčího

Dostaneš automatický přepis (ASR, může obsahovat drobné chyby nebo rušivé
zvuky) řeči JEDNOHO konkrétního politika — celý dodaný text patří jemu,
mluvčí je už ověřený diarizací a ručním přiřazením, netřeba ho znovu ověřovat.

Pravidla:
1. Vyber věty, které tvoří srozumitelný, ucelený výrok — ne torzo věty
   přeťaté chybou přepisu nebo cizí vloženou promluvou.
2. `citace` musí být DOSLOVNÝ, nezkrácený úryvek z dodaného textu — žádné
   spojování vět z různých míst, žádná parafráze ani oprava přepisu.
3. Kratší přesná citace je lepší než delší nepřesná. Nejvýš 400 znaků na citaci.
4. Když si nejsi jistý/á srozumitelností nebo úplností výroku, vynech ho —
   je v pořádku vrátit prázdný seznam.
5. Nejvýš 5 nejvýznamnějších citací.

Vrať POUZE JSON pole:
[{"citace": "<doslovný úryvek z textu>"}]
"""


def _speaker_full_text_with_offsets(speaker_segments: List[Dict[str, Any]]):
    """Spojí úseky mezerou a vrátí `(plný_text, [(start_char, end_char, úsek), ...])`."""
    parts = []
    offsets = []
    pos = 0
    for seg in speaker_segments:
        text = seg.get("text", "")
        offsets.append((pos, pos + len(text), seg))
        parts.append(text)
        pos += len(text) + 1
    return " ".join(parts), offsets


def _locate_quote_timestamp(speaker_segments: List[Dict[str, Any]], citace: str) -> Optional[float]:
    """Vteřina úseku, ve kterém citace v spojeném textu začíná — orientační, ne forenzní přesnost."""
    full_text, offsets = _speaker_full_text_with_offsets(speaker_segments)
    idx = full_text.find(citace)
    if idx == -1:
        return None
    for start_char, end_char, seg in offsets:
        if idx < end_char:
            return seg.get("start")
    return offsets[-1][2].get("start") if offsets else None


def extract_quotes_from_speaker_text(
    backend, speaker_segments: List[Dict[str, Any]], politician_name: str, model_name: str
) -> List[Dict[str, Any]]:
    """LLM navrhne citace z přepisu; každá musí přežít podřetězcovou kontrolu a mít dohledatelný timestamp."""
    full_text, _ = _speaker_full_text_with_offsets(speaker_segments)
    payload = {"POLITIK": politician_name, "PREPIS": full_text[:20000]}
    user_payload = json.dumps(payload, ensure_ascii=False)
    ck = cache_key(model_name, "MRF_VIDEO_CITACE::{}::{}".format(PROMPT_VERSION, user_payload))
    raw = backend.call("MRF_VIDEO_CITACE", VIDEO_QUOTE_EXTRACTION_PROMPT, user_payload, model_name, ck=ck)
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
        if full_text.find(citace) == -1:
            continue
        timestamp = _locate_quote_timestamp(speaker_segments, citace)
        if timestamp is None:
            continue
        out.append({"citace": citace, "timestampSeconds": timestamp})
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
            if not is_source_allowed(article["url"]):
                continue
            if _looks_like_listing_page(article["url"]):
                continue
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


def build_role_flip_leads_from_video(
    video_urls: List[str], conn, registry, tisky_registry, client, backend, model_name: str,
) -> List[Dict[str, Any]]:
    """
    Pro každé video: jen jeho ručně tagovaní mluvčí (`video_speakers.id_osoba
    IS NOT NULL`) — netagovaní se přeskočí beze zmínky, ne odhadují. Od
    `find_tisk_candidate` dál stejná brána jako `build_role_flip_leads`.
    Vyžaduje `prepare_video_speakers.py` + `tag_video_speaker.py` předem.
    """
    organ = str(registry.term_organ_id)
    tisky_pro_prompt = [
        {"cislo": info.cislo, "nazev": info.cely_nazev} for info in tisky_registry.all_for_organ(organ)
    ]

    results = []
    for video_url in video_urls:
        cache_row = conn.execute(
            "SELECT medium, datum_videa, segments_json FROM video_transcript_cache WHERE video_url = ?",
            (video_url,),
        ).fetchone()
        if not cache_row:
            print(f"  [-] {video_url}: chybí zpracovaný přepis (spusť prepare_video_speakers.py)")
            continue
        medium, datum_videa, merged = cache_row["medium"], cache_row["datum_videa"], json.loads(cache_row["segments_json"])
        if not datum_videa:
            continue
        try:
            video_datum = datetime.strptime(datum_videa, "%Y-%m-%d").date()
        except ValueError:
            continue
        if video_datum < TERM_START_DATE:
            continue

        speaker_rows = conn.execute(
            "SELECT speaker_label, id_osoba FROM video_speakers WHERE video_url = ? AND id_osoba IS NOT NULL",
            (video_url,),
        ).fetchall()
        if not speaker_rows:
            print(f"  [-] {video_url}: žádný mluvčí není označen (spusť tag_video_speaker.py)")
            continue

        for row in speaker_rows:
            speaker_label, id_osoba = row["speaker_label"], row["id_osoba"]
            person = registry.people.get(id_osoba)
            if not person:
                continue
            jmeno = person.full_name

            speaker_segments = [s for s in merged if s.get("speaker") == speaker_label]
            if not speaker_segments:
                continue

            role_pri_citatu = registry.political_role_at(id_osoba, video_datum)["role"]
            if not (_is_government_side(role_pri_citatu) or _is_opposition_side(role_pri_citatu)):
                continue

            quotes = extract_quotes_from_speaker_text(backend, speaker_segments, jmeno, model_name)
            zdroj = {"url": video_url, "medium": medium, "datumClanku": datum_videa}

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
                if stance["postoj"] not in PUBLIKOVATELNE_POSTOJE:
                    continue
                klub_pomer = klub_tally_for_ballot(
                    conn, registry, final_vote["idHlasovani"], vote.get("klub") or "", hlasovani_datum,
                )

                record = build_record(
                    id_osoba, jmeno, quote["citace"], dict(zdroj, timestampSeconds=quote["timestampSeconds"]),
                    role_pri_citatu, tisk_info, final_vote, stance, vote, role_pri_hlasovani, klub_pomer,
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
    parser.add_argument("--poslanec", action="append", default=[], dest="poslanci",
                        help="Celé jméno politika (opakovatelné) — hledá v novinových článcích.")
    parser.add_argument("--video", action="append", default=[], dest="videa",
                        help="URL videa, zpracovaného přes prepare_video_speakers.py (opakovatelné).")
    parser.add_argument("--limit-clanky", type=int, default=DEFAULT_LIMIT_CLANKY)
    parser.add_argument("--backend", choices=["auto", "gemini", "api", "jsonl"], default="auto")
    args = parser.parse_args()

    if not args.poslanci and not args.videa:
        print("zadej --poslanec (články) nebo --video (zpracovaná videa), aspoň jedno.")
        return

    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if args.poslanci and not firecrawl_key:
        print("FIRECRAWL_API_KEY chybí v .env — bez něj --poslanec nemá co dělat.")
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

    leads = []
    if args.poslanci:
        leads += build_role_flip_leads(
            args.poslanci, conn, registry, tisky_registry, client, backend,
            firecrawl_key, model_name, limit_clanky=args.limit_clanky,
        )
    if args.videa:
        leads += build_role_flip_leads_from_video(
            args.videa, conn, registry, tisky_registry, client, backend, model_name,
        )
    print(f"rolový obrat: {len(leads)} nových/aktualizovaných leadů. "
          f"Schválení: python pipeline/promote_media_lead.py --lead-id <id> (viz /interni/prehled)")


if __name__ == "__main__":
    main()
