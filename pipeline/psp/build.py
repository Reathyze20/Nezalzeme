"""
Převod staženého stenozáznamu do datového modelu enginu (`src/types/debate.ts`).

Jeden **bod pořadu schůze** = jedna rozprava (`Debate`), jedno **vystoupení** =
jedna zpráva (`Message`). Anotace se tady nevytvářejí – ty jsou úkol Fází 1–5.
Výstup je tedy vstup do detektoru, ne jeho výsledek, a `annotations` je vždy
prázdné pole.

Co se naopak doplňuje hned, protože to plyne přímo ze zdroje:

  * `party` – klub **k datu vystoupení** (přeběhy mezi kluby jsou v datech).
  * `timestamp` – čas ze skrytého komentáře stenozáznamu, ne odhad.
  * `source` – kotva do stenoprotokolu a napárovaná jmenovitá hlasování;
    z toho staví Fáze 3 svůj Voting Ledger a Fáze 5 svůj `proof.sourceUrl`.
"""

import os
import re
import sys
from datetime import date
from typing import Any, Dict, List, Optional

from .client import PspClient
from .hlasovani import Ballot, load_ballots
from .opendata import Registry
from .stenoprotokol import DayRecord, Speech, load_day_speeches

# `cleaner` leží o úroveň výš, vedle detektoru. Cesta se doplňuje jen tehdy,
# když modul ještě není dosažitelný – při spuštění z adresáře `pipeline/` je.
_PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PIPELINE_DIR not in sys.path:
    sys.path.append(_PIPELINE_DIR)
from cleaner import clean_speech_text  # noqa: E402

#: Funkce, u nichž vystoupení řídí schůzi místo toho, aby zaujímalo postoj.
CHAIR_ROLES = ("Předseda PSP", "Předsedkyně PSP", "Místopředseda PSP", "Místopředsedkyně PSP")

#: Barvy klubů 10. volebního období pro odznak u jména ve feedu.
CLUB_COLORS = {
    "ANO2011": "#0044A5",
    "ODS": "#0033A0",
    "STAN": "#EC5D25",
    "SPD": "#263C63",
    "Piráti": "#000000",
    "KDU-ČSL": "#F9A11B",
    "TOP09": "#7E2A8E",
    "MS": "#1B1B1B",
}

_TISK = re.compile(r"sněmovní tisk\s*(\d+)", re.I)

#: Úvodní číslo bodu ("12. ") a závěrečná poznámka o tisku, které patří do
#: plného názvu, ale ne do stručného označení tématu.
_LEADING_NUMBER = re.compile(r"^\s*\d+\.\s*")
_TISK_CLAUSE = re.compile(r"\s*/[^/]*sněmovní tisk[^/]*/.*$", re.I)


def short_topic(title: str) -> str:
    """Název bodu bez pořadového čísla a bez dovětku o sněmovním tisku."""
    topic = _TISK_CLAUSE.sub("", _LEADING_NUMBER.sub("", title)).strip(" –-—/")
    return topic or title


def is_chair(speech: Speech) -> bool:
    role = speech.role
    return any(role.startswith(prefix) for prefix in CHAIR_ROLES)


def message_id(day: DayRecord, debate_index: int, speech: Speech) -> str:
    """
    Stabilní identifikátor vystoupení.

    Bez pořadí rozpravy by identifikátory kolidovaly: `order` se počítá uvnitř
    bodu pořadu, ale `turn` přetéká přes hranici bodu, takže dvě vystoupení
    z různých bodů mohou vyjít na tutéž dvojici. Kolize by rozbila kotvy
    `#messageId` i klíče v seznamech.
    """
    return "psp-{}-{}-{}-{}-{}".format(
        day.session, day.day, debate_index, speech.turn or 0, speech.order)


def _clean(raw_text: str) -> str:
    """
    Odstraní úvodní a závěrečné zdvořilostní fráze.

    `cleaner.clean_speech_text` je psaný na jeden odstavec; stenozáznam jich má
    víc, takže se čistí první a poslední zvlášť a zbytek zůstává beze změny.

    Krátké procedurální vstupy ("Děkuji." jako celý projev) by se čištěním
    vyprázdnily. Prázdný `cleanText` ale znamená, že by značka neměla text,
    do kterého by ukázala znakovými indexy – v takovém případě se proto
    vrací původní znění.
    """
    paragraphs = [p for p in raw_text.split("\n") if p.strip()]
    if not paragraphs:
        return ""
    cleaned = list(paragraphs)
    cleaned[0] = clean_speech_text(cleaned[0])[0]
    if len(cleaned) > 1:
        cleaned[-1] = clean_speech_text(cleaned[-1])[0]
    result = "\n".join(p for p in cleaned if p.strip())
    return result if result.strip() else "\n".join(paragraphs)


def build_message(
    speech: Speech,
    day: DayRecord,
    debate_index: int,
    registry: Registry,
    ballots: Dict[str, Ballot],
) -> Dict[str, Any]:
    when: date = day.date
    # Noční jednání pokračuje pod datem, kdy začalo; kalendářní datum projevu
    # ve 2:10 je proto o den vyšší než datum jednacího dne.
    spoken_at = speech.moment(when) if when else None
    spoken_date = spoken_at.date() if spoken_at else when
    club = registry.club_at(speech.id_osoba, when) or ""
    clean_text = _clean(speech.text)

    paired = []
    for ballot_id in speech.ballot_ids:
        ballot = ballots.get(ballot_id)
        if not ballot:
            continue
        paired.append({
            "ballotId": ballot.ballot_id,
            "url": ballot.url,
            "number": ballot.number,
            "subject": ballot.subject,
            "result": ballot.result,
            "clock": ballot.clock.isoformat() if ballot.clock else None,
            "voteOfSpeaker": (lambda v: v.value if v else None)(ballot.vote_of(speech.id_osoba)),
        })

    message: Dict[str, Any] = {
        "messageId": message_id(day, debate_index, speech),
        "speaker": speech.speaker,
        "party": club,
        "role": speech.role or "Poslanec",
        "timestamp": speech.clock.strftime("%H:%M") if speech.clock else "",
        "date": spoken_date.isoformat() if spoken_date else "",
        "rawText": speech.text,
        "cleanText": clean_text,
        "hasAnomalies": False,
        "annotations": [],
        # Vlastní blok, který v `Message` není: drží doložitelnost výroku.
        # Detektor z něj bere `proof.sourceUrl` a Voting Ledger.
        "source": {
            "idOsoba": speech.id_osoba,
            "idPoslanec": registry.deputy_id(speech.id_osoba),
            "stenoUrl": speech.source_url,
            "sectionUrl": speech.page_url,
            "turn": speech.turn,
            "clockExact": speech.clock.isoformat() if speech.clock else None,
            "spokenAt": spoken_at.isoformat() if spoken_at else None,
            "dayOffset": speech.day_offset,
            "anchorVerified": speech.anchor_verified,
            "isChair": is_chair(speech),
            "ballots": paired,
        },
    }
    # Volitelná pole se vynechávají, ne posílají jako null: typ `Message` je má
    # jako `?: string`, a `null` by do něj neprošel.
    color = CLUB_COLORS.get(club)
    if color:
        message["partyColor"] = color
    return message


def build_debates(
    client: PspClient,
    day: DayRecord,
    registry: Registry,
    term: str = "10. volební období (2025–)",
) -> List[Dict[str, Any]]:
    """Jeden jednací den -> seznam rozprav podle bodů pořadu schůze."""
    speeches = load_day_speeches(client, day)
    ballots = load_ballots(client, sorted({b for s in speeches for b in s.ballot_ids}))

    sections: Dict[str, List[Speech]] = {}
    for speech in speeches:
        sections.setdefault(speech.section_title, []).append(speech)

    debates: List[Dict[str, Any]] = []
    for index, (title, group) in enumerate(sections.items(), start=1):
        tisk = _TISK.search(title)
        debates.append({
            "debateId": "psp-{}-{}-{}".format(day.session, day.day, index),
            "title": title,
            "topic": short_topic(title),
            "chamber": "Poslanecká sněmovna Parlamentu ČR",
            "term": term,
            "sessionNumber": day.session,
            "date": day.date.isoformat() if day.date else "",
            **({"tiskNumber": tisk.group(1)} if tisk else {}),
            "description": "Stenografický zápis {}. schůze, {}. jednací den.".format(
                day.session, day.day
            ),
            "status": "PROJEDNÁNO",
            "messages": [build_message(s, day, index, registry, ballots) for s in group],
            "source": {
                "dayUrl": day.url,
                "sectionUrls": sorted({s.page_url.split("#")[0] for s in group}),
                "ballotIds": sorted({b for s in group for b in s.ballot_ids}),
            },
        })
    return debates


def latest_day(client: PspClient, term_path: str = "eknih/2025ps") -> Optional[DayRecord]:
    """Poslední jednací den, který má Sněmovna zveřejněný."""
    from .stenoprotokol import list_days, load_day

    days = list_days(client, term_path)
    if not days:
        return None
    return load_day(client, days[-1])
