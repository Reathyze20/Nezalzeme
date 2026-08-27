"""
Důkazní brána — ověřuje, že `proof.pastQuote` skutečně leží na `proof.sourceUrl`
a že `proof.votingBallotId` popisuje hlasování se správným datem a schůzí.

Funguje jako tvrdá brána v `export_web.py`: anotace, jejíž doložení selže,
se na web nedostane. Skript lze spustit i samostatně nad libovolným souborem
s anotacemi.

    # Přejímací test: všechny ruční ukázky musí selhat (doložení je smyšlené)
    python pipeline/verify_proof.py --input pipeline/data/hand_authored_examples.json

    # Produkční kontrola nad výstupem enginu:
    python pipeline/verify_proof.py --input pipeline/data/psp/schuze-014-den-1-2026-04-14.json

Výstup: popis každého selhání + nenulový kód, pokud aspoň jedno existuje.
"""

import argparse
import io
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psp.client import PspClient
from psp.hlasovani import load_ballot

# ---------------------------------------------------------------------------
# Interní helpery
# ---------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_ENTITY = re.compile(r"&(?:nbsp|amp|lt|gt|quot);")
_ENTITY_MAP = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"'}
_BALLOT_NUM = re.compile(r"[čc]\.\s*(\d+)", re.I)
_BALLOT_DATE = re.compile(r"\((\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\)")
_BALLOT_SESSION = re.compile(r"(\d+)\.\s*sch[ůu]ze", re.I)


def _strip_html(html: str) -> str:
    """Odstraní HTML tagy a normalizuje bílé znaky."""
    text = _TAG.sub(" ", html)
    text = _ENTITY.sub(lambda m: _ENTITY_MAP.get(m.group(0), " "), text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Ověření pastQuote
# ---------------------------------------------------------------------------

def verify_quote(proof: Dict[str, Any], client: PspClient) -> Optional[str]:
    """
    Vrátí popis selhání nebo `None` při úspěchu.

    Podmínka: normalizovaný `pastQuote` musí být podřetězcem textu stránky
    po odstranění HTML tagů a normalizaci bílých znaků.
    """
    source_url = (proof.get("sourceUrl") or "").strip()
    past_quote = (proof.get("pastQuote") or "").strip()

    if not source_url:
        return "chybí proof.sourceUrl"
    if not past_quote:
        return "chybí proof.pastQuote"

    try:
        html = client.get_text(source_url)
    except Exception as exc:
        return "nepodařilo se stáhnout {}: {}".format(source_url, exc)

    page_text = _strip_html(html)
    normalized_quote = re.sub(r"\s+", " ", past_quote).strip()

    if normalized_quote in page_text:
        return None

    # Diagnostický výpis prvních 80 znaků citátu pro ladicí účely
    short = normalized_quote[:80] + ("…" if len(normalized_quote) > 80 else "")
    return "pastQuote nenalezena na {}: {!r}".format(source_url, short)


# ---------------------------------------------------------------------------
# Ověření hlasovacího záznamu
# ---------------------------------------------------------------------------

def _parse_claimed_ballot(voting_ballot_id: str):
    """
    Extrahuje z textového řetězce `votingBallotId` číslo hlasování, číslo
    schůze a datum.

    Formát: "Hlasování č. 87115, 14. schůze (14. 4. 2026)"
    Vrátí trojici (ballot_number, session, date) nebo (None, None, None).
    """
    from datetime import date as _date

    num_m = _BALLOT_NUM.search(voting_ballot_id)
    ballot_number = num_m.group(1) if num_m else None

    session_m = _BALLOT_SESSION.search(voting_ballot_id)
    session = int(session_m.group(1)) if session_m else None

    date_m = _BALLOT_DATE.search(voting_ballot_id)
    if date_m:
        try:
            claimed_date = _date(int(date_m.group(3)), int(date_m.group(2)), int(date_m.group(1)))
        except ValueError:
            claimed_date = None
    else:
        claimed_date = None

    return ballot_number, session, claimed_date


def verify_ballot(proof: Dict[str, Any], client: PspClient) -> Optional[str]:
    """
    Ověří, že hlasování v `proof.votingBallotId` skutečně proběhlo v uvedené
    schůzi a v uvedeném datu. Vrátí popis selhání nebo `None` při úspěchu.

    Tato kontrola by zachytila hlasování č. 87120, které bylo popsáno jako
    "29.5.2026, tisk 314" — skutečně je to 14.4.2026, jiná schůze, jiný výsledek.
    """
    voting_ballot_id = (proof.get("votingBallotId") or "").strip()
    if not voting_ballot_id:
        return None  # bez votingBallotId ověření nevyžadujeme

    ballot_number, claimed_session, claimed_date = _parse_claimed_ballot(voting_ballot_id)

    if not ballot_number:
        return "nelze extrahovat číslo hlasování z {!r}".format(voting_ballot_id)

    try:
        ballot = load_ballot(client, ballot_number)
    except Exception as exc:
        return "nepodařilo se stáhnout hlasování č. {}: {}".format(ballot_number, exc)

    errors = []

    if claimed_session is not None and ballot.session is not None:
        if ballot.session != claimed_session:
            errors.append(
                "schůze: tvrzeno {}, skutečnost {}".format(claimed_session, ballot.session)
            )

    if claimed_date is not None and ballot.date is not None:
        if ballot.date != claimed_date:
            errors.append(
                "datum: tvrzeno {}, skutečnost {}".format(claimed_date, ballot.date)
            )

    if errors:
        return "hlasování č. {} — {}".format(ballot_number, "; ".join(errors))

    return None


# ---------------------------------------------------------------------------
# Veřejné rozhraní
# ---------------------------------------------------------------------------

def verify_annotation(annotation: Dict[str, Any], client: PspClient) -> Optional[str]:
    """
    Ověří jednu anotaci. Vrátí popis selhání nebo `None` při úspěchu.

    Volá se z `export_web.py` jako brána před zápisem dataset.json.
    """
    proof = annotation.get("proof")
    if not proof:
        return "chybí pole proof"

    quote_err = verify_quote(proof, client)
    if quote_err:
        return quote_err

    ballot_err = verify_ballot(proof, client)
    if ballot_err:
        return ballot_err

    return None


def verify_all_annotations(
    annotations: List[Dict[str, Any]],
    client: PspClient,
    label_fn=None,
) -> List[str]:
    """
    Ověří všechny anotace. Vrátí seznam popisů selhání (prázdný = vše OK).

    `label_fn(annotation)` → str pro identifikaci anotace ve výpisu.
    """
    failures = []
    for ann in annotations:
        err = verify_annotation(ann, client)
        if err:
            label = label_fn(ann) if label_fn else ann.get("id") or ann.get("shortBadgeLabel") or "?"
            failures.append("{}: {}".format(label, err))
    return failures


# ---------------------------------------------------------------------------
# Standalone režim
# ---------------------------------------------------------------------------

def _collect_from_file(path: str) -> List[Dict[str, Any]]:
    """
    Načte anotace z:
      - `hand_authored_examples.json` (klíč `examples`)
      - korpusového souboru `pipeline/data/psp/*.json` (zanořeno v messages)
    """
    with io.open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    # hand_authored_examples.json
    if isinstance(data, dict) and "examples" in data:
        return data["examples"]

    # seznam rozprav (korpusový soubor)
    annotations = []
    debates = data if isinstance(data, list) else data.get("debates", [])
    for debate in debates:
        for msg in debate.get("messages", []):
            for ann in msg.get("annotations", []):
                ann.setdefault("_source_message", msg.get("messageId"))
                annotations.append(ann)
    return annotations


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Ověří, že proof.pastQuote leží na proof.sourceUrl."
    )
    parser.add_argument(
        "--input", required=True,
        help="Soubor s anotacemi (hand_authored_examples.json nebo korpusový *.json).",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Ignorovat diskovou cache a znovu stáhnout stránky.",
    )
    args = parser.parse_args(argv)

    client = PspClient(refresh=args.refresh)
    annotations = _collect_from_file(args.input)

    if not annotations:
        print("V souboru {} nejsou žádné anotace.".format(args.input))
        return 0

    print("Ověřuji {} anotaci/í z {}...".format(len(annotations), args.input))

    def label(ann):
        parts = [
            ann.get("speaker") or ann.get("_source_message"),
            ann.get("shortBadgeLabel"),
        ]
        return " / ".join(p for p in parts if p) or "?"

    ok = fail = 0
    for ann in annotations:
        err = verify_annotation(ann, client)
        lbl = label(ann)
        if err:
            print("  [SELHAL] {} — {}".format(lbl, err))
            fail += 1
        else:
            print("  [OK    ] {}".format(lbl))
            ok += 1

    print()
    print("Výsledek: {} OK, {} selhalo".format(ok, fail))
    print("  cache: {} hitů, {} stažení".format(client.stats["hits"], client.stats["misses"]))

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
