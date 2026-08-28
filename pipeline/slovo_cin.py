"""
Slovo vs. Čin (Fáze 3) — postoj z rozpravy vedle jmenovitého hlasování.

Nahrazuje detekci rozporů mezi projevy, která na sněmovním materiálu
nefungovala (906 vystoupení -> 30 789 párů -> 0 publikovatelných nálezů).
Politik v připraveném projevu neřekne „A" a za rok „ne-A"; hlasování je ale
binární a veřejné, takže se s výrokem porovnat dá.

Řetěz, na kterém to stojí — každý článek ověřený proti skutečným datům:

    claim (STANCE_COMMITMENT, OWN_STANCE)
      -> vystoupení -> (turn, kotva #rN, id_osoba)
      -> rec.unl        -> id_bod          [psp/opendata_hlasovani.py]
      -> bod_schuze.unl -> číslo tisku
      -> historie.sqw   -> FINÁLNÍ hlasování o tisku   [psp/tisk_historie.py]
      -> hlasy.sqw?G=   -> jak hlasoval TENHLE poslanec [psp/hlasovani.py]

Čtyři pojistky, bez kterých by z toho bylo křivé obvinění:

1. **Které hlasování je to finální, určuje Sněmovna, ne my.** Název hlasování
   v dumpu je jméno bodu pořadu — u tisku 82 nese všech 24 hlasování stejný
   název a jedno z nich je návrh na přerušení schůze. Proto `tisk_historie`,
   ne `vote_classifier`.
2. **Schůze rozpravy se musí rovnat schůzi hlasování.** Jinak by se výrok
   z března pároval s hlasováním z dubna po vrácení zákona Senátem.
3. **Hlas se čte z HTML `hlasy.sqw`, ne z dumpu.** Dump slučuje „zdržel se"
   a „nehlasoval" do kódu `K`; publikovat „zdržel se" na základě `K` by bylo
   tvrzení nad rámec dat.
4. **Model smí říct „nevím".** Postoj `NEURCITELNE` (a `NEUTRALNI`) se
   nepublikuje. Prompt dostane jen text výroku a název tisku — nic o tom,
   jak se hlasovalo, aby si odpověď nemohl domyslet zpětně.
"""

import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import cache_key, now_iso  # noqa: E402
from psp.hlasovani import load_ballot  # noqa: E402
from psp.opendata_hlasovani import (  # noqa: E402
    bod_info,
    find_id_bod,
    is_omluven,
)
from psp.tisk_historie import fetch_final_vote, tisk_number_from_ref  # noqa: E402

ENGINE_VERSION = "slovo-cin-v1"

#: Verze promptů. Musí být v cache klíči — `model_backend` počítá klíč jen
#: z payloadu, takže bez tohohle by se po zpřísnění promptu vracely staré
#: odpovědi na nový prompt.
PROMPT_VERSION = "v2"

#: Kotva `#rN` na konci `source.stenoUrl`.
_ANCHOR_RE = re.compile(r"#r(\d+)\s*$")

#: Postoje, které smí jít na web. `NEUTRALNI` a `NEURCITELNE` nikdy —
#: z výroku, který k návrhu nezaujímá stanovisko, se nedá nic dovodit.
PUBLIKOVATELNE_POSTOJE = ("PRO", "PROTI")

STANCE_PROMPT = """# ROLE: URČENÍ POSTOJE VÝROKU K NÁVRHU ZÁKONA

Dostaneš doslovný výrok poslance z rozpravy a název sněmovního tisku,
o kterém se v té rozpravě jednalo.

Rozhodni, jaký postoj výrok zaujímá **k přijetí toho návrhu**:

- "PRO"          — výrok návrh podporuje, obhajuje nebo vyzývá k jeho přijetí
- "PROTI"        — výrok návrh odmítá, kritizuje jako celek nebo vyzývá k zamítnutí
- "NEUTRALNI"    — výrok se návrhu týká, ale stanovisko k přijetí nezaujímá
                   (popis, dotaz, procedurální poznámka, řečnická vsuvka)
- "NEURCITELNE"  — z výroku to nejde poznat, nebo se návrhu netýká

PRAVIDLA:
1. Rozhoduj VÝHRADNĚ podle předloženého výroku. Nedomýšlej si, co řečník
   říkal jindy, ani jak nakonec hlasoval.
2. Kritika jednotlivého ustanovení NENÍ "PROTI" návrhu jako celku.
   Stejně tak pochvala detailu není "PRO".
3. PODMÍNĚNOST JE "NEURCITELNE". Jakmile výrok podporu nebo odpor váže na
   podmínku, výhradu nebo omezení, není to "PRO" ani "PROTI". Signály:
   "pokud", "za podmínky", "ale", "podtrhuji", "dočasně", "za jasně
   definovaných podmínek", "jsem pro princip, ovšem".
   Příklad: "je legitimní, aby vláda takový nástroj měla — ale podtrhuji
   dočasně a za jasných podmínek" => "NEURCITELNE", NIKOLI "PRO".
   Souhlas s principem nebo s cílem není souhlas s TÍMTO návrhem.
4. Když si nejsi jistý, vrať "NEURCITELNE". Chybné určení postoje je horší
   než žádné — vede k veřejnému tvrzení, že se někdo rozešel se svým slovem.

Vrať POUZE JSON objekt:
{"postoj": "PRO"|"PROTI"|"NEUTRALNI"|"NEURCITELNE", "oduvodneni": "<max 200 znaků>"}
"""


def _anchor_of(message: Dict[str, Any]) -> Optional[int]:
    source = message.get("source") or {}
    match = _ANCHOR_RE.search(source.get("stenoUrl") or "")
    return int(match.group(1)) if match else None


def load_corpus_index(corpus_dir: str) -> Dict[str, Dict[str, Any]]:
    """`messageId -> {message, debate}` ze souborů korpusu."""
    import glob

    index: Dict[str, Dict[str, Any]] = {}
    for path in sorted(glob.glob(os.path.join(corpus_dir, "*.json"))):
        with open(path, encoding="utf-8") as handle:
            for debate in json.load(handle):
                for message in debate.get("messages", []):
                    index[message["messageId"]] = {"message": message, "debate": debate}
    return index


def find_candidates(conn, corpus_index: Dict[str, Dict[str, Any]], client,
                    id_organ: str = "174") -> List[Dict[str, Any]]:
    """
    Výroky, ke kterým existuje finální hlasování o témže tisku na téže schůzi.

    Vrací jen to, co projde všemi pojistkami — ostatní se tiše vynechá,
    protože „nevíme" je legitimní výsledek, ne chyba.
    """
    tisk_cache: Dict[str, Any] = {}
    candidates: List[Dict[str, Any]] = []

    rows = conn.execute(
        "SELECT claim_id, message_id, claim_json FROM claims ORDER BY claim_id"
    ).fetchall()

    for row in rows:
        claim = json.loads(row["claim_json"])
        if claim.get("claimCategory") != "STANCE_COMMITMENT":
            continue
        # Citace oponenta ani řečnická figura není vlastní závazek řečníka.
        if claim.get("speechAct") != "OWN_STANCE":
            continue

        entry = corpus_index.get(row["message_id"])
        if not entry:
            continue
        message, debate = entry["message"], entry["debate"]
        source = message.get("source") or {}
        turn, id_osoba = source.get("turn"), source.get("idOsoba")
        anchor = _anchor_of(message)
        if turn is None or anchor is None or not id_osoba:
            continue
        # Předsedající řídí schůzi, nezaujímá postoj.
        if source.get("isChair"):
            continue

        schuze = debate.get("sessionNumber")
        id_bod = find_id_bod(conn, id_organ, schuze, turn, anchor, id_osoba)
        if not id_bod:
            continue
        info = bod_info(conn, id_bod)
        if not info:
            continue
        tisk = tisk_number_from_ref(info.get("tisk_ref"))
        if not tisk:
            continue

        if tisk not in tisk_cache:
            tisk_cache[tisk] = fetch_final_vote(
                client, tisk, conn=conn, id_organ=id_organ, prefer_schuze=schuze
            )
        final_vote = tisk_cache[tisk]
        if not final_vote or not final_vote.get("idHlasovani"):
            continue
        # Pojistka 2: výrok a hlasování musí patřit k téže schůzi.
        if final_vote["schuze"] != schuze:
            continue

        candidates.append({
            "claimId": row["claim_id"],
            "messageId": row["message_id"],
            "idOsoba": str(id_osoba),
            "claim": claim,
            "message": message,
            "debate": debate,
            "bod": info,
            "tisk": tisk,
            "finalVote": final_vote,
        })

    return candidates


def classify_stance(backend, claim: Dict[str, Any], tisk_nazev: str,
                    model_name: str) -> Dict[str, Any]:
    """Postoj výroku k návrhu. Prompt nezná výsledek hlasování — schválně."""
    payload = {
        "VYROK": claim.get("rawSpan", ""),
        "TVRZENI": " ".join(filter(None, [
            claim.get("subject", ""), claim.get("predicate", ""), claim.get("object", ""),
        ])).strip(),
        "NAZEV_TISKU": tisk_nazev,
    }
    user_payload = json.dumps(payload, ensure_ascii=False)
    # Explicitní cache klíč: `model_backend._make_cache_key` počítá klíč jen
    # z payloadu, takže bez role by se sem mohla vrátit odpověď na úplně jiný
    # systémový prompt se shodným vstupem.
    ck = cache_key(model_name, "SLOVO_CIN_POSTOJ::{}::{}".format(PROMPT_VERSION, user_payload))
    raw = backend.call("SLOVO_CIN_POSTOJ", STANCE_PROMPT, user_payload, model_name, ck=ck)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"postoj": "NEURCITELNE", "oduvodneni": "odpověď modelu nešla přečíst"}

    postoj = str(parsed.get("postoj", "")).upper().strip()
    if postoj not in ("PRO", "PROTI", "NEUTRALNI", "NEURCITELNE"):
        postoj = "NEURCITELNE"
    return {"postoj": postoj, "oduvodneni": str(parsed.get("oduvodneni", ""))[:200]}


def resolve_vote(client, conn, id_hlasovani: str, id_osoba: str, id_poslanec: Optional[str],
                 datum: str, cas: str, id_organ: str = "174") -> Optional[Dict[str, Any]]:
    """
    Jak hlasoval konkrétní poslanec — z HTML hlasovacího lístku.

    Pojistka 3: dump slučuje „zdržel se" a „nehlasoval", HTML je rozlišuje
    (`psp/hlasovani.py`). Publikovaná položka musí stát na HTML.
    """
    try:
        ballot = load_ballot(client, id_hlasovani)
    except Exception:
        return None

    problems = ballot.discrepancies()
    if problems:
        # Nepřečetli jsme celý jmenný seznam — na takovém hlasování se nedá stavět.
        return None

    vote = ballot.vote_of(id_osoba)
    if vote is None:
        return None

    return {
        "hlas": vote.value,
        "pritomen": vote.present,
        "klub": vote.club,
        "omluven": is_omluven(conn, id_organ, id_poslanec, datum, cas) if id_poslanec else False,
        "vysledek": ballot.result,
        "url": ballot.url,
    }


def build_record(candidate: Dict[str, Any], stance: Dict[str, Any],
                 vote: Dict[str, Any], klub_pomer: Optional[Dict[str, int]]) -> Dict[str, Any]:
    """Sestaví položku `SlovoCin` pro web."""
    claim = candidate["claim"]
    message = candidate["message"]
    source = message.get("source") or {}
    final_vote = candidate["finalVote"]

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

    return {
        "id": "sc-{}-{}".format(candidate["claimId"], final_vote["idHlasovani"]),
        "claimId": candidate["claimId"],
        "messageId": candidate["messageId"],
        "idOsoba": candidate["idOsoba"],
        "receno": {
            "citace": claim.get("rawSpan", ""),
            "start": claim.get("sourceCharStart", 0),
            "end": claim.get("sourceCharEnd", 0),
            "datum": message.get("date", ""),
            "stenoUrl": source.get("stenoUrl", ""),
            "debateId": candidate["debate"].get("debateId", ""),
            "debateTitle": candidate["debate"].get("title", ""),
        },
        "postoj": stance["postoj"],
        "postojOduvodneni": stance["oduvodneni"],
        "hlasovani": {
            "idHlasovani": final_vote["idHlasovani"],
            "url": final_vote["url"],
            "cislo": final_vote["cisloHlasovani"],
            "schuze": final_vote["schuze"],
            "nazev": candidate["bod"]["nazev"],
            "vysledekSlovy": final_vote["vysledekSlovy"],
            "prijat": final_vote["prijat"],
            "historieUrl": final_vote["historieUrl"],
            "hlas": vote["hlas"],
            "omluven": vote["omluven"],
            "klub": vote["klub"],
            "klubPomer": klub_pomer,
        },
        "tisk": {
            "cislo": candidate["tisk"],
            "nazev": candidate["bod"]["nazev"],
            "url": "https://www.psp.cz/sqw/historie.sqw?o=10&T={}".format(candidate["tisk"]),
        },
        "shoda": shoda,
    }


def store_record(conn, record: Dict[str, Any], model_name: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO slovo_cin "
        "(id, claim_id, message_id, id_osoba, id_hlasovani, tisk, postoj, hlas, shoda, "
        " zaznam_json, overeno, produced_at, model_name, engine_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
        (
            record["id"], record["claimId"], record["messageId"], record["idOsoba"],
            record["hlasovani"]["idHlasovani"], record["tisk"]["cislo"],
            record["postoj"], record["hlasovani"]["hlas"], record["shoda"],
            json.dumps(record, ensure_ascii=False), now_iso(), model_name, ENGINE_VERSION,
        ),
    )


def klub_tally_for_ballot(conn, registry, id_hlasovani: str, klub: str,
                          when) -> Optional[Dict[str, int]]:
    """Poměr hlasů řečníkova klubu u téhož hlasování — kvůli klubové kázni."""
    if not klub:
        return None
    osoba_by_poslanec = {idp: ido for ido, idp in registry.deputy_ids()}
    counts = {"pro": 0, "proti": 0, "zdrzelNeboNehlasoval": 0, "neprihlasen": 0}
    rows = conn.execute(
        "SELECT id_poslanec, kod FROM hlas_poslance WHERE id_hlasovani = ?",
        (id_hlasovani,),
    ).fetchall()
    for row in rows:
        id_osoba = osoba_by_poslanec.get(row["id_poslanec"])
        if not id_osoba or registry.club_at(id_osoba, when) != klub:
            continue
        if row["kod"] == "A":
            counts["pro"] += 1
        elif row["kod"] == "B":
            counts["proti"] += 1
        elif row["kod"] == "K":
            counts["zdrzelNeboNehlasoval"] += 1
        else:
            counts["neprihlasen"] += 1
    return counts if any(counts.values()) else None


OBHAJOBA_PROMPT = """# ROLE: OBHÁJCE — existuje výklad, při kterém rozpor mizí?

Dostaneš výrok poslance z rozpravy, návrh zákona, jak poslanec hlasoval
a jak hlasoval jeho klub.

Tvrzení k přezkumu: „řečník se v rozpravě postavil {postoj} návrhu, ale
hlasoval {hlas}".

Najdi NEJSILNĚJŠÍ výklad, při kterém to žádný rozpor není. Zvaž hlavně:

1. **Podmíněnost.** Vyjadřuje výrok podporu/odpor jen za podmínek („dočasně",
   „za jasně definovaných podmínek", „pokud", „ale")? Pak přijetí návrhu,
   který podmínky nesplňuje, výroku neodporuje.
2. **Předmět.** Mluví výrok o principu nebo o jiné části problému, ne
   o přijetí TOHOTO návrhu?
3. **Role.** Cituje řečník někoho jiného, shrnuje debatu, nebo se ptá?
4. **Klub.** Hlasoval-li stejně jako drtivá většina klubu, je pravděpodobnější,
   že se výrok četl špatně, než že se rozešel s vlastním slovem.

Vrať POUZE JSON:
{{"rozporMizi": true|false, "vyklad": "<max 250 znaků>"}}

`true` = existuje rozumný výklad bez rozporu (pak se NEPUBLIKUJE).
Při jakékoli pochybnosti vracej `true`. Nepublikovat pravdivý rozpor je
mnohem menší chyba než veřejně tvrdit rozpor, který neexistuje.
"""


def challenge_mismatch(backend, record: Dict[str, Any], model_name: str) -> Dict[str, Any]:
    """
    Adversariální přezkum kandidáta na NESHODU.

    Běží jen na neshodách — jen u nich se něco tvrdí o rozporu mezi slovem
    a činem, a jen tam tedy hrozí křivé obvinění. Shoda ani „nehlasoval"
    nikoho z ničeho neviní.
    """
    hlasovani = record["hlasovani"]
    payload = {
        "VYROK": record["receno"]["citace"],
        "NAZEV_TISKU": record["tisk"]["nazev"],
        "HLAS_POSLANCE": hlasovani["hlas"],
        "POSTOJ_URCENY_MODELEM": record["postoj"],
        "KLUB": hlasovani["klub"],
        "KLUB_POMER": hlasovani["klubPomer"],
    }
    user_payload = json.dumps(payload, ensure_ascii=False)
    ck = cache_key(model_name, "SLOVO_CIN_OBHAJOBA::{}::{}".format(PROMPT_VERSION, user_payload))
    raw = backend.call(
        "SLOVO_CIN_OBHAJOBA",
        OBHAJOBA_PROMPT.format(postoj=record["postoj"], hlas=hlasovani["hlas"]),
        user_payload,
        model_name,
        ck=ck,
    )
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Nepřečtená odpověď = neprokázáno = nepublikovat.
        return {"rozporMizi": True, "vyklad": "odpověď obhájce nešla přečíst"}

    return {
        "rozporMizi": bool(parsed.get("rozporMizi", True)),
        "vyklad": str(parsed.get("vyklad", ""))[:250],
    }
