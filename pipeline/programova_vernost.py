"""
Programová věrnost (Fáze 4) — závazek z Programového prohlášení vlády vedle
hlasování koaličních klubů o odpovídajícím sněmovním tisku.

Zdroj: https://vlada.gov.cz/cz/vlada/programove-prohlaseni/programove-prohlaseni-vlady-224629/
Schváleno vládou 5. 1. 2026 (koalice ANO 2011, Motoristé sobě, SPD — jediné
kluby, které se k prohlášení zavázaly; `psp.opendata.COALITION_CLUBS_AFTER_SWITCH`).

**Proč tahle fáze nese jiné riziko než Slovo vs. Čin (`slovo_cin.py`).**
Tam je vazba výrok -> hlasování strukturální: `rec.unl` dá `id_bod`,
`bod_schuze.unl` dá číslo tisku, žádný model o tom nerozhoduje. Tady žádná
taková vazba neexistuje — text prohlášení a číslo sněmovního tisku spojuje
jen model, a jediné, co má k dispozici, je NÁZEV tisku (`tisky.unl`), ne jeho
plné znění nebo důvodová zpráva. Název tisku bývá věcný („Vládní návrh
zákona, kterým se mění zákon č. 117/1995 Sb., o státní sociální podpoře"),
ale shoda tématu není totéž co shoda obsahu. Proto:

1. **Citace je vždy doslovný podřetězec uloženého textu kapitoly**
   (`programove_kapitoly.text`) — stejná disciplína jako `claims.py`.
2. **Spárování navrhuje jeden model, ale musí přežít nezávislý přezkum
   druhého volání** (`challenge_pairing`), který se ptá jen na jednu věc:
   odpovídá název tisku věcně KONKRÉTNÍMU opatření ze závazku, nebo jen širší
   oblasti? Na rozdíl od `slovo_cin.challenge_mismatch` (kde nečitelná
   odpověď = obhájeno = nepublikovat neshodu) je tu bezpečný výchozí stav
   OPAČNÝ směrem: nečitelná nebo nejistá odpověď = spárování NEPLATÍ =
   nepublikovat vazbu vůbec. Tvrdit spojení, které neexistuje, je tu to
   riziko, ne tvrdit rozpor, který neexistuje.
3. **Publikuje se jen tisk s dokončeným projednáním** (`tisk_historie`) —
   u tisků, které ještě neprošly 3. čtením, se závazek k ničemu nepřirovnává.
4. **Výsledek je vždy tři čísla vedle sebe (poměr hlasů v každém koaličním
   klubu), ne verdikt.** Žádné „splněno/nesplněno" — schválení tisku, který
   opatření řeší, je nejsilnější doklad, ale ne důkaz nad rámec toho, co
   název tisku říká.
"""

import hashlib
import html as _html
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import cache_key, now_iso  # noqa: E402
from psp.client import PspClient  # noqa: E402
from psp.opendata import COALITION_CLUBS_AFTER_SWITCH  # noqa: E402
from psp.tisk_historie import (  # noqa: E402
    DEFAULT_OBDOBI,
    HISTORIE_URL,
    fetch_final_vote,
    parse_historie,
)
from slovo_cin import klub_tally_for_ballot  # noqa: E402

ENGINE_VERSION = "programova-vernost-v1"

#: Verze promptů v cache klíči — beze změny by po úpravě promptu
#: `model_backend` vrátil starou odpověď na nový dotaz (viz `slovo_cin.py`).
PROMPT_VERSION = "v1"

PROHLASENI_URL = (
    "https://vlada.gov.cz/cz/vlada/programove-prohlaseni/programove-prohlaseni-vlady-224629/"
)
#: Datum schválení vládou (ověřeno webem vlada.gov.cz a dobovým zpravodajstvím
#: 28. 8. 2026) — použité jako kontext v UI, ne jako vstup do žádného výpočtu.
SCHVALENO = "2026-01-05"

#: Pořadí a `id` kotev `<h2><a id="...">` na stránce prohlášení — kontrola,
#: že se struktura stránky mezitím nezměnila (jinak `parse_kapitoly` spadne
#: hlasitě, ne že by potichu vrátil méně kapitol).
KAPITOLY_ID = [
    "preambule_a_priority", "finance_a_hospodareni", "vnitrni_bezpecnost_a_verejna_sprava",
    "obranna_politika_a_armada", "zahranicni_politika", "pravo_a_spravedlnost",
    "hospodarstvi_prumysl_energetika", "doprava", "vzdelavani",
    "socialni_politika_a_zamestnanost", "zdravotnictvi", "zemedelstvi",
    "zivotni_prostredi", "kultura", "bydleni_a_regionalni_rozvoj",
    "sport_prevence_zdravi", "veda_vyzkum_inovace", "digitalizace",
]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ARTICLE = re.compile(r'<article class="article">(.*?)</article>', re.S)
_H2 = re.compile(
    r'<h2[^>]*><a\s+id="(?P<id>[^"]+)"[^>]*>.*?</a>\s*(?:\d+\.\s*)?(?P<nazev>.*?)</h2>',
    re.S,
)


def _plain(raw: str) -> str:
    """HTML -> holý text. `unescape` až po stripnutí tagů (viz `tisk_historie._plain`)."""
    return _WS.sub(" ", _html.unescape(_TAG.sub(" ", raw))).strip()


def fetch_prohlaseni_client(cache_dir: Optional[str] = None) -> PspClient:
    """Vlastní klient/cache mimo `psp_cache` — jiná doména, jiný účel."""
    if cache_dir is None:
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vlada_cache")
    return PspClient(
        cache_dir=cache_dir,
        user_agent="nezalzeme.cz/0.1 (zpracovani programoveho prohlaseni vlady CR)",
    )


def parse_kapitoly(html: str) -> List[Dict[str, Any]]:
    """
    Rozdělí stránku prohlášení na kapitoly podle `<h2 id="...">` kotev.

    Vrací seznam v pořadí na stránce; každá položka nese holý text ohraničený
    danou kapitolou (nadpisy podkapitol i odstavce dohromady — prohlášení
    nemá kotvy níž než na kapitolu, takže citace se dá vázat jen sem).
    """
    article_match = _ARTICLE.search(html)
    if not article_match:
        raise ValueError("stránka prohlášení nemá očekávaný <article class=\"article\">")
    body = article_match.group(1)

    marks = list(_H2.finditer(body))
    found_ids = [m.group("id") for m in marks]
    if found_ids != KAPITOLY_ID:
        raise ValueError(
            "struktura kapitol prohlášení se změnila: očekáváno {}, nalezeno {}".format(
                KAPITOLY_ID, found_ids)
        )

    kapitoly = []
    for index, match in enumerate(marks):
        start = match.end()
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        kapitoly.append({
            "id": match.group("id"),
            "poradi": index + 1,
            "nazev": _plain(match.group("nazev")),
            "text": _plain(body[start:end]),
        })
    return kapitoly


def ingest_kapitoly(conn, client: PspClient) -> List[Dict[str, Any]]:
    """Stáhne (nebo použije z cache) prohlášení a uloží kapitoly do `programove_kapitoly`."""
    html = client.get_text(PROHLASENI_URL)
    kapitoly = parse_kapitoly(html)
    for kapitola in kapitoly:
        conn.execute(
            "INSERT OR REPLACE INTO programove_kapitoly (id, poradi, nazev, text, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (kapitola["id"], kapitola["poradi"], kapitola["nazev"], kapitola["text"], now_iso()),
        )
    conn.commit()
    return kapitoly


ZAVAZEK_PROMPT = """# ROLE: rozklad Programového prohlášení vlády na ověřitelné závazky

Dostaneš text jedné kapitoly Programového prohlášení vlády ČR. Najdi věty,
které slibují KONKRÉTNÍ, OVĚŘITELNÉ opatření — takové, u kterého by šlo
rozumně čekat, že si vyžádá změnu zákona nebo hlasování Sněmovny o něčem
jmenovitém. Vynechej obecné hodnotové proklamace („chceme silný a
sebevědomý stát"), procesní věty a nadpisy.

Pravidla:
1. `citace` musí být DOSLOVNÝ, nezkrácený úryvek z dodaného textu — žádné
   parafráze, žádné spojování vět z různých míst. Kratší přesná citace je
   lepší než delší nepřesná.
2. Jedna citace = jeden slib, ne shrnutí celého odstavce.
3. Když si nejsi jistý/á, že jde o měřitelný závazek (ne proklamaci), vynech
   ho — je v pořádku vrátit prázdný seznam.
4. Nejvýš 8 nejkonkrétnějších závazků z kapitoly.

Vrať POUZE JSON pole:
[{"citace": "<doslovný úryvek z textu>"}]
"""


def extract_zavazky(backend, kapitola: Dict[str, Any], model_name: str) -> List[Dict[str, Any]]:
    """LLM najde konkrétní závazky v textu kapitoly; každý se ověří jako podřetězec."""
    payload = {"KAPITOLA": kapitola["nazev"], "TEXT": kapitola["text"]}
    user_payload = json.dumps(payload, ensure_ascii=False)
    ck = cache_key(model_name, "PV_ZAVAZKY::{}::{}".format(PROMPT_VERSION, user_payload))
    raw = backend.call("PV_ZAVAZKY", ZAVAZEK_PROMPT, user_payload, model_name, ck=ck)
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
        if not citace:
            continue
        start = kapitola["text"].find(citace)
        if start == -1:
            # Nedoslovná citace se nepublikuje — stejné pravidlo jako u claims.py.
            continue
        zavazek_id = "pz-" + hashlib.sha1(
            (kapitola["id"] + "::" + citace).encode("utf-8")
        ).hexdigest()[:16]
        out.append({
            "id": zavazek_id,
            "kapitolaId": kapitola["id"],
            "citace": citace,
            "charStart": start,
            "charEnd": start + len(citace),
        })
    return out


def store_zavazek(conn, zavazek: Dict[str, Any], model_name: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO programove_zavazky "
        "(id, kapitola_id, citace, char_start, char_end, produced_at, model_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            zavazek["id"], zavazek["kapitolaId"], zavazek["citace"],
            zavazek["charStart"], zavazek["charEnd"], now_iso(), model_name,
        ),
    )


PAROVANI_PROMPT = """# ROLE: existuje sněmovní tisk, který tenhle konkrétní slib naplňuje?

Dostaneš doslovný závazek z Programového prohlášení vlády a seznam
sněmovních tisků tohoto volebního období (číslo a plný název — nic víc,
plné znění zákona nemáš k dispozici).

Vyber NEJVÝŠ JEDEN tisk, jehož název věcně a konkrétně odpovídá opatření
ze závazku — ne jen širšímu tématu. „Snížíme daně živnostníkům" a tisk
„Novela zákona o daních z příjmů" je shoda; „Podpoříme bydlení" a tisk
o stavebním právu je JEN tematická blízkost, ne totéž opatření — u té
druhé dvojice vrať žádný výsledek.

Když si nejsi jistý/á, nebo žádný název neodpovídá dost konkrétně,
vrať `"cisloTisku": null`. Prázdný výsledek je mnohem levnější chyba
než tvrdit spojení, které tam není.

Vrať POUZE JSON:
{"cisloTisku": "<číslo tisku>"|null, "zduvodneni": "<max 200 znaků, jaká konkrétní shoda>"}
"""


def find_tisk_candidate(backend, zavazek_citace: str, tisky: List[Dict[str, str]],
                        model_name: str) -> Optional[Dict[str, Any]]:
    """
    Navrhne nejvýš jeden kandidátní tisk pro daný závazek.

    `tisky` = [{"cislo": ..., "nazev": ...}, ...] pro celé volební období —
    typicky pár set položek, vejde se do jednoho promptu bez retrievalu.
    """
    payload = {"ZAVAZEK": zavazek_citace, "TISKY": tisky}
    user_payload = json.dumps(payload, ensure_ascii=False)
    ck = cache_key(model_name, "PV_PAROVANI::{}::{}".format(PROMPT_VERSION, user_payload))
    raw = backend.call("PV_PAROVANI", PAROVANI_PROMPT, user_payload, model_name, ck=ck)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    cislo = parsed.get("cisloTisku")
    if not cislo:
        return None
    cislo = str(cislo).strip()
    if not any(t["cislo"] == cislo for t in tisky):
        # Model si vymyslel číslo mimo nabídnutý seznam — nedůvěryhodné.
        return None
    return {"cislo": cislo, "zduvodneni": str(parsed.get("zduvodneni", ""))[:200]}


OBHAJOBA_PAROVANI_PROMPT = """# ROLE: OPONENT — obstojí tohle spárování před skeptickým čtenářem?

Dostaneš závazek z vládního prohlášení, název sněmovního tisku, kterým ho
někdo označil za naplnění závazku, a zdůvodnění spárování.

Tvoje jediná otázka: odpovídá název tisku věcně KONKRÉTNÍMU opatření ze
závazku, tak, že by to obstálo, kdyby to redakce ukázala novináři? Neznáš
plné znění zákona — posuzuj jen z názvu. Sdílené téma NESTAČÍ, musí sedět
konkrétní opatření.

Buď přísný/á. Když váháš, spárování NEPLATÍ.

Vrať POUZE JSON:
{"parovaniPlati": true|false, "vyklad": "<max 200 znaků>"}
"""


def challenge_pairing(backend, zavazek_citace: str, tisk_nazev: str, zduvodneni: str,
                      model_name: str) -> Dict[str, Any]:
    """
    Nezávislý přezkum spárování. Běží na KAŽDÉM navrženém spárování, ne jen
    na sporných — tady je totiž riskantní tvrzení už samo spárování, ne jen
    nesouhlas s ním (na rozdíl od `slovo_cin.challenge_mismatch`).

    Nečitelná nebo chybějící odpověď => spárování neplatí. Bezpečný směr je
    tu opačný než u obhájce v `slovo_cin.py`.
    """
    payload = {
        "ZAVAZEK": zavazek_citace,
        "NAZEV_TISKU": tisk_nazev,
        "ZDUVODNENI_SPAROVANI": zduvodneni,
    }
    user_payload = json.dumps(payload, ensure_ascii=False)
    ck = cache_key(model_name, "PV_OBHAJOBA::{}::{}".format(PROMPT_VERSION, user_payload))
    raw = backend.call("PV_OBHAJOBA", OBHAJOBA_PAROVANI_PROMPT, user_payload, model_name, ck=ck)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"parovaniPlati": False, "vyklad": "odpověď oponenta nešla přečíst"}
    if not isinstance(parsed, dict):
        return {"parovaniPlati": False, "vyklad": "odpověď oponenta nešla přečíst"}

    return {
        "parovaniPlati": bool(parsed.get("parovaniPlati", False)),
        "vyklad": str(parsed.get("vyklad", ""))[:200],
    }


def latest_final_vote(client: PspClient, tisk: str, conn, id_organ: str = "174",
                      obdobi: int = DEFAULT_OBDOBI) -> Optional[Dict[str, Any]]:
    """
    Poslední finální hlasování o tisku (ne první) — u tisku vráceného Senátem
    je až druhé hlasování to, které skutečně rozhoduje o osudu zákona.
    `psp.tisk_historie.fetch_final_vote` bez `prefer_schuze` bere první; tady
    žádná řeč není, ke které by se dalo schůzi vázat, takže se bere poslední.
    """
    try:
        html = client.get_text(HISTORIE_URL.format(obdobi=obdobi, tisk=tisk))
    except Exception:
        return None
    kandidati = [k for k in parse_historie(html) if k["schuze"] is not None]
    if not kandidati:
        return None
    posledni = kandidati[-1]
    return fetch_final_vote(
        client, tisk, conn=conn, id_organ=id_organ, obdobi=obdobi,
        prefer_schuze=posledni["schuze"],
    )


def build_record(zavazek: Dict[str, Any], kapitola: Dict[str, Any], tisk_info,
                 final_vote: Dict[str, Any], zduvodneni: str,
                 kluby: Dict[str, Optional[Dict[str, int]]], datum: str = "") -> Dict[str, Any]:
    """Sestaví položku `ProgramovaVernost` pro web."""
    return {
        "id": "pv-{}-{}".format(zavazek["id"], final_vote["idHlasovani"]),
        "zavazekId": zavazek["id"],
        "zavazek": {
            "kapitolaId": kapitola["id"],
            "kapitolaPoradi": kapitola["poradi"],
            "kapitolaNazev": kapitola["nazev"],
            "citace": zavazek["citace"],
            "url": PROHLASENI_URL + "#" + kapitola["id"],
            "schvaleno": SCHVALENO,
        },
        "tisk": {
            "cislo": tisk_info["cislo"],
            "nazev": tisk_info["nazev"],
            "url": HISTORIE_URL.format(obdobi=DEFAULT_OBDOBI, tisk=tisk_info["cislo"]),
        },
        "hlasovani": {
            "idHlasovani": final_vote["idHlasovani"],
            "url": final_vote["url"],
            "cislo": final_vote["cisloHlasovani"],
            "schuze": final_vote["schuze"],
            "datum": datum,
            "vysledekSlovy": final_vote["vysledekSlovy"],
            "prijat": final_vote["prijat"],
            "historieUrl": final_vote["historieUrl"],
        },
        "duvodSparovani": zduvodneni,
        "kluby": kluby,
    }


def store_record(conn, record: Dict[str, Any], model_name: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO programova_vernost "
        "(id, zavazek_id, tisk, id_hlasovani, zaznam_json, overeno, produced_at, "
        " model_name, engine_version) "
        "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)",
        (
            record["id"], record["zavazekId"], record["tisk"]["cislo"],
            record["hlasovani"]["idHlasovani"], json.dumps(record, ensure_ascii=False),
            now_iso(), model_name, ENGINE_VERSION,
        ),
    )


def kluby_tally_for_ballot(conn, registry, id_hlasovani: str, when) -> Dict[str, Optional[Dict[str, int]]]:
    """Poměr hlasů KAŽDÉHO koaličního klubu (ne jen řečníkova) u hlasování."""
    return {
        klub: klub_tally_for_ballot(conn, registry, id_hlasovani, klub, when)
        for klub in sorted(COALITION_CLUBS_AFTER_SWITCH - {"ANO"})
    }
