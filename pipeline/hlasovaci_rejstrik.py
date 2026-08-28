"""
Hlasovací rejstřík (Fáze 2) — "o čem se u tohoto bodu hlasovalo a jak kdo hlasoval".

Doplňuje korpus rozprav o jmenovitá hlasování z otevřených dat
(`psp/opendata_hlasovani.py`), a to **term-wide**: dosud se hlasování párovalo
jen tehdy, když odkaz `hlasy.sqw?G=` ležel fyzicky uvnitř bloku projevu
(`psp/stenoprotokol.py`), což zachytilo 64 vystoupení z 2 082 — a z toho 56
předsedajících, protože ten odkaz čte předsedající, ne řečník.

Data se ukládají **na úroveň rozpravy, ne vystoupení**. V rozpravě o jednom
bodu pořadu (např. žádost o důvěru vládě: 8 hlasování, 53 řečníků) by uložení
ke každému vystoupení znamenalo stejných 8 hlasování 53× — několik MB navíc
v `dataset.json` bez jediné nové informace. Rozprava proto nese hlasování
jednou (`hlasovani`) a hlasy řečníků jednou na řečníka (`hlasyRecniku`).

Tenhle modul **netvrdí nic o rozporu** mezi slovem a hlasem — to je Fáze 3
(`slovo_cin.py`). Tady jde jen o doložený výpis, u kterého si závěr dělá
čtenář.
"""

import os
import re
import sys
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psp.opendata import Registry  # noqa: E402
from psp.opendata_hlasovani import (  # noqa: E402
    VOTE_CODE_MAP,
    bod_info,
    find_id_bod,
    is_omluven,
    votes_for_bod,
)
from psp.vote_classifier import classify_vote  # noqa: E402

#: Kotva `#rN` na konci `source.stenoUrl` — pořadí projevu v rámci `turn`.
_ANCHOR_RE = re.compile(r"#r(\d+)\s*$")

#: Kód z dumpu -> hodnota pro web. `K` slučuje "zdržel se" a "nehlasoval",
#: takže se ani ve výstupu nesmí tvářit jako jedno z nich — viz
#: `VoteValueLedger` v `src/types/debate.ts`.
LEDGER_VALUE_BY_CODE = {
    "A": "PRO",
    "B": "PROTI",
    "K": "ZDRZEL_SE_NEBO_NEHLASOVAL",
    "@": "NEPRIHLASEN",
}


def _parse_unl_date(value: str) -> Optional[date]:
    """`dd.mm.yyyy` z `hl2025s.unl`."""
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except (ValueError, AttributeError):
        return None


def _anchor_of(message: Dict[str, Any]) -> Optional[int]:
    source = message.get("source") or {}
    match = _ANCHOR_RE.search(source.get("stenoUrl") or "")
    return int(match.group(1)) if match else None


def resolve_debate_bod(conn, debate: Dict[str, Any], id_organ: str) -> Optional[Dict[str, Any]]:
    """
    Bod pořadu, ke kterému rozprava patří.

    `debateId` je `psp-<schuze>-<den>-<poradi>`, kde poslední složka je pořadí
    bloku v jednacím dni, **ne** číslo bodu pořadu — to se musí dohledat přes
    `rec.unl`. Bere se modus přes všechna vystoupení: jeden blok stenozáznamu
    může okrajově zasahovat do sousedního bodu (u ověřované rozpravy
    `psp-5-3-3` sedělo 193 vystoupení z 196 na bod 51).
    """
    schuze = debate.get("sessionNumber")
    if schuze is None:
        return None

    counts: Dict[str, int] = {}
    for message in debate.get("messages", []):
        source = message.get("source") or {}
        turn = source.get("turn")
        id_osoba = source.get("idOsoba")
        anchor = _anchor_of(message)
        if turn is None or anchor is None or not id_osoba:
            continue
        id_bod = find_id_bod(conn, id_organ, schuze, turn, anchor, id_osoba)
        if id_bod:
            counts[id_bod] = counts.get(id_bod, 0) + 1

    if not counts:
        return None
    id_bod = max(counts, key=lambda key: counts[key])
    info = bod_info(conn, id_bod)
    if not info:
        return None
    return {
        "idBod": info["id_bod"],
        "cislo": info["bod"],
        "nazev": info["nazev"],
        "idTisk": info["id_tisk"],
        "tiskRef": info["tisk_ref"] or None,
        "podilVystoupeni": round(counts[id_bod] / max(1, len(debate.get("messages", []))), 3),
    }


def club_tallies(conn, registry: Registry, id_hlasovani: str,
                 when: Optional[date], osoba_by_poslanec: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Poměr hlasů po klubech u jednoho hlasování.

    Klub se bere **k datu hlasování** (`Registry.club_at`), ne k dnešku —
    přeběhy mezi kluby jsou v datech zachycené intervalem.
    """
    rows = conn.execute(
        "SELECT id_poslanec, kod FROM hlas_poslance WHERE id_hlasovani = ?",
        (id_hlasovani,),
    ).fetchall()

    buckets: Dict[str, Dict[str, int]] = {}
    for row in rows:
        id_osoba = osoba_by_poslanec.get(row["id_poslanec"])
        klub = registry.club_at(id_osoba, when) if (id_osoba and when) else None
        if not klub:
            continue
        bucket = buckets.setdefault(klub, {"pro": 0, "proti": 0,
                                           "zdrzelNeboNehlasoval": 0, "neprihlasen": 0})
        value = LEDGER_VALUE_BY_CODE.get(row["kod"])
        if value == "PRO":
            bucket["pro"] += 1
        elif value == "PROTI":
            bucket["proti"] += 1
        elif value == "ZDRZEL_SE_NEBO_NEHLASOVAL":
            bucket["zdrzelNeboNehlasoval"] += 1
        elif value == "NEPRIHLASEN":
            bucket["neprihlasen"] += 1

    return [
        {"klub": klub, **counts}
        for klub, counts in sorted(buckets.items(), key=lambda item: -sum(item[1].values()))
    ]


def build_debate_ledger(conn, registry: Registry, debate: Dict[str, Any],
                        id_organ: str, faze: Optional[str] = None) -> Dict[str, Any]:
    """
    Hlasování a hlasy řečníků pro jednu rozpravu.

    Vrací `{"bod", "hlasovani", "hlasyRecniku"}`; prázdné hodnoty, když se bod
    nepodařilo dohledat (typicky u bloků mimo projednávání bodu — zahájení
    jednacího dne, procedurální vsuvky).
    """
    empty = {"bod": None, "hlasovani": [], "hlasyRecniku": []}
    bod = resolve_debate_bod(conn, debate, id_organ)
    if not bod or bod["cislo"] is None:
        return empty

    ballots = votes_for_bod(conn, id_organ, debate["sessionNumber"], bod["cislo"])
    if not ballots:
        return {"bod": bod, "hlasovani": [], "hlasyRecniku": []}

    osoba_by_poslanec = {idp: ido for ido, idp in registry.deputy_ids()}

    hlasovani = []
    for ballot in ballots:
        when = _parse_unl_date(ballot["datum"])
        classification = classify_vote(ballot["nazev"], ballot["cislo"])
        hlasovani.append({
            "ballotId": ballot["id_hlasovani"],
            "url": ballot["url"],
            "cislo": ballot["cislo"],
            "nazev": ballot["nazev"],
            "datum": when.isoformat() if when else ballot["datum"],
            "cas": ballot["cas"],
            "vysledek": ballot["vysledek"],
            "prijato": ballot["vysledek"] == "A",
            "pro": ballot["pro"],
            "proti": ballot["proti"],
            "zdrzel": ballot["zdrzel"],
            "nehlasoval": ballot["nehlasoval"],
            "typ": classification.vote_type,
            "jeVecne": classification.is_substantive,
            "faze": faze,
            "klubyPomer": club_tallies(conn, registry, ballot["id_hlasovani"],
                                       when, osoba_by_poslanec),
        })

    # Hlasy řečníků — jednou na řečníka, ne na každé jeho vystoupení.
    speakers: Dict[str, str] = {}
    for message in debate.get("messages", []):
        source = message.get("source") or {}
        id_osoba = source.get("idOsoba")
        if id_osoba and not (source.get("isChair") or False):
            speakers.setdefault(str(id_osoba), message.get("speaker", ""))

    hlasy_recniku = []
    for id_osoba, jmeno in speakers.items():
        id_poslanec = registry.deputy_id(id_osoba)
        if not id_poslanec:
            continue
        hlasy = []
        for ballot in ballots:
            row = conn.execute(
                "SELECT kod FROM hlas_poslance WHERE id_hlasovani = ? AND id_poslanec = ?",
                (ballot["id_hlasovani"], id_poslanec),
            ).fetchone()
            if not row:
                continue
            omluven = is_omluven(conn, id_organ, id_poslanec, ballot["datum"], ballot["cas"])
            hlasy.append({
                "ballotId": ballot["id_hlasovani"],
                "hlas": LEDGER_VALUE_BY_CODE.get(row["kod"], "NEPRIHLASEN"),
                "omluven": omluven,
            })
        if hlasy:
            hlasy_recniku.append({"idOsoba": id_osoba, "jmeno": jmeno, "hlasy": hlasy})

    return {"bod": bod, "hlasovani": hlasovani, "hlasyRecniku": hlasy_recniku}


def voting_balance(conn, registry: Registry, id_osoba: str, id_organ: str) -> Optional[Dict[str, Any]]:
    """
    Hlasovací bilance poslance za celé volební období — počitatelná veličina.

    Účast je podíl hlasování, u kterých je poslanec v dumpu veden jako
    přihlášený (`A`/`B`/`K`), ze všech nezmatečných hlasování období. Omluvená
    neúčast se počítá zvlášť, aby se z omluvy nestala "absence".
    """
    id_poslanec = registry.deputy_id(id_osoba)
    if not id_poslanec:
        return None

    rows = conn.execute(
        "SELECT h.kod AS kod, v.datum AS datum, v.cas AS cas "
        "FROM hlas_poslance h JOIN hlasovani v ON h.id_hlasovani = v.id_hlasovani "
        "WHERE h.id_poslanec = ? AND v.id_organ = ? AND v.is_zmatecne = 0",
        (id_poslanec, str(id_organ)),
    ).fetchall()
    if not rows:
        return None

    tally = {"pro": 0, "proti": 0, "zdrzelNeboNehlasoval": 0, "neprihlasen": 0, "omluven": 0}
    for row in rows:
        value = LEDGER_VALUE_BY_CODE.get(row["kod"])
        if value == "PRO":
            tally["pro"] += 1
        elif value == "PROTI":
            tally["proti"] += 1
        elif value == "ZDRZEL_SE_NEBO_NEHLASOVAL":
            tally["zdrzelNeboNehlasoval"] += 1
        else:
            tally["neprihlasen"] += 1
            if is_omluven(conn, id_organ, id_poslanec, row["datum"], row["cas"]):
                tally["omluven"] += 1

    celkem = len(rows)
    pritomen = tally["pro"] + tally["proti"] + tally["zdrzelNeboNehlasoval"]
    return {
        "celkem": celkem,
        **tally,
        "ucast": round(pritomen / celkem, 4) if celkem else 0.0,
    }
