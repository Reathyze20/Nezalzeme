"""
Export staženého korpusu do jednoho artefaktu pro web.

    python pipeline/export_web.py

Tohle je **jediný šev mezi pipeline a aplikací**. Web nikdy nečte soubory
z `pipeline/data/psp/` přímo — čte výhradně `src/data/psp/dataset.json`, který
vzniká tady. Až korpus přeroste do SQLite, změní se jen zdroj čtení v tomhle
souboru; aplikace o tom nebude vědět.

Co se cestou děje:

  * zahazuje se `rawText` (u většiny vystoupení je totožný s `cleanText`
    a zdvojnásoboval by velikost artefaktu),
  * dopočítá se rejstřík řečníků a klubů — web ho nesmí odvozovat sám,
    protože klub se váže k datu vystoupení, ne k dnešku,
  * doplní se hlavička `meta` s tím, **kolik vystoupení už prošlo analýzou**.
    To je klíčový údaj: bez něj rozhraní neumí odlišit „zkontrolováno a čisté"
    od „zatím nezkontrolováno" a začne tvrdit první místo druhého.
"""

import glob
import io
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import (  # noqa: E402
    analyzed_message_ids,
    load_annotations_for_message,
    open_engine_db,
)
from psp.build import CLUB_COLORS  # noqa: E402
from psp.client import PspClient  # noqa: E402
from psp.facts import ENGINE_SQLITE_PATH  # noqa: E402
from psp.opendata import Registry  # noqa: E402
from verify_proof import verify_all_annotations  # noqa: E402

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(PIPELINE_DIR)
SOURCE_DIR = os.path.join(PIPELINE_DIR, "data", "psp")
TARGET_DIR = os.path.join(ROOT, "src", "data", "psp")
TARGET_JSON = os.path.join(TARGET_DIR, "dataset.json")

STENO_INDEX = "https://www.psp.cz/eknih/2025ps/stenprot/index.htm"
PROFILE_URL = "https://www.psp.cz/sqw/detail.sqw?id={}"

#: Pole, která do webu neposíláme. `rawText` je duplicita `cleanText`.
DROP_MESSAGE_FIELDS = ("rawText",)


def slugify(value: str) -> str:
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c)
    )
    out = []
    for char in stripped.lower():
        out.append(char if char.isalnum() and char.isascii() else "-")
    return "-".join(part for part in "".join(out).split("-") if part)


def politician_slug(name: str) -> str:
    """
    Slug z **celého** jména, ne jen z příjmení.

    V korpusu jsou dvě Kovářové a dva Zůnové; slug z příjmení by je sloučil do
    jednoho profilu a jeden by tiše přepsal druhého.
    """
    return slugify(name)


def load_debates() -> List[Dict[str, Any]]:
    debates: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(SOURCE_DIR, "*.json"))):
        with io.open(path, encoding="utf-8") as handle:
            debates.extend(json.load(handle))
    return debates


def slim_message(message: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in message.items() if k not in DROP_MESSAGE_FIELDS}


def build_politicians(debates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rejstřík řečníků odvozený z korpusu.

    Univerzum poslanců nesmí být ruční seznam – musí to být přesně ti, kdo
    v korpusu opravdu mluvili, jinak profily nesedí na vystoupení.
    """
    people: Dict[str, Dict[str, Any]] = {}
    for debate in debates:
        for message in debate["messages"]:
            name = message["speaker"]
            record = people.setdefault(name, {
                "name": name,
                "slug": politician_slug(name),
                "idOsoba": message["source"]["idOsoba"],
                "party": "",
                "roles": {},
                "speechCount": 0,
                "lastSpokeAt": "",
            })
            record["speechCount"] += 1
            record["roles"][message["role"]] = record["roles"].get(message["role"], 0) + 1
            # Klub bereme z nejnovějšího vystoupení – u přeběhlíka je to ten
            # současný, u ministra bez mandátu zůstane prázdný.
            when = message["date"]
            if when >= record["lastSpokeAt"]:
                record["lastSpokeAt"] = when
                if message.get("party"):
                    record["party"] = message["party"]

    politicians = []
    for record in people.values():
        roles = record.pop("roles")
        record["role"] = max(roles.items(), key=lambda kv: (kv[1], kv[0]))[0]
        record["profileUrl"] = PROFILE_URL.format(record["idOsoba"])
        politicians.append(record)

    # Kolizi celého jména (dvě osoby stejného jména) rozliší id ze Sněmovny.
    seen: Dict[str, List[Dict[str, Any]]] = {}
    for politician in politicians:
        seen.setdefault(politician["slug"], []).append(politician)
    for slug, group in seen.items():
        if len(group) > 1:
            for politician in group:
                politician["slug"] = "{}-{}".format(slug, politician["idOsoba"])

    return sorted(politicians, key=lambda p: p["name"])


def build_parties(politicians: List[Dict[str, Any]], registry: Registry) -> List[Dict[str, Any]]:
    used = sorted({p["party"] for p in politicians if p["party"]})
    parties = []
    for zkratka in used:
        parties.append({
            "name": zkratka,
            "fullName": registry.club_full_name(zkratka) or zkratka,
            "color": CLUB_COLORS.get(zkratka, "#64748B"),
        })
    return parties


def main() -> int:
    debates = load_debates()
    if not debates:
        print("V {} nejsou žádná stažená data. Spusť nejdřív pipeline/fetch_psp.py.".format(
            SOURCE_DIR), file=sys.stderr)
        return 1

    for debate in debates:
        debate["messages"] = [slim_message(m) for m in debate["messages"]]

    # ---------- Fáze C: anotace z engine.sqlite, ne z korpusových souborů ----------
    # Korpusové JSON soubory nesou pouze text a metadata — žádné `annotations`.
    # Zdrojem anotací je výhradně engine.sqlite (verdikty s proof_verified=1).
    # Pokud soubor neexistuje (engine ještě neběžel), přeskočíme prázdnou DB.
    engine_conn = None
    engine_analyzed_ids: set = set()
    if os.path.exists(ENGINE_SQLITE_PATH):
        engine_conn = open_engine_db(ENGINE_SQLITE_PATH)
        engine_analyzed_ids = analyzed_message_ids(engine_conn)

    for debate in debates:
        for msg in debate["messages"]:
            mid = msg["messageId"]
            if engine_conn:
                anns = load_annotations_for_message(engine_conn, mid)
                msg["annotations"] = anns
                msg["hasAnomalies"] = len(anns) > 0
                if mid in engine_analyzed_ids:
                    msg["analyzedAt"] = msg.get("analyzedAt") or "engine"
            else:
                msg.setdefault("annotations", [])
                msg.setdefault("hasAnomalies", False)

    # ---------- Důkazní brána (Fáze B) ----------
    # Ověří, že každá anotace z engine.sqlite má doložení ověřitelné na zdroji.
    # proof_verified=1 v engine.sqlite znamená, že verify_proof.py již prošlo
    # v run_pipeline.py — tady je to pojistná kontrola při každém exportu.
    all_annotations = [
        ann
        for debate in debates
        for msg in debate["messages"]
        for ann in msg.get("annotations", [])
    ]
    if all_annotations:
        client = PspClient()
        def _label(ann):
            return ann.get("id") or ann.get("shortBadgeLabel") or "?"
        failures = verify_all_annotations(all_annotations, client, label_fn=_label)
        if failures:
            print("=== DŮKAZNÍ BRÁNA: export zastaven ===", file=sys.stderr)
            for failure_msg in failures:
                print("  [BRÁNA] {}".format(failure_msg), file=sys.stderr)
            print(
                "{} anotaci/í neprošlo ověřením.".format(len(failures)),
                file=sys.stderr,
            )
            return 1

    politicians = build_politicians(debates)
    registry = Registry.load(PspClient())
    parties = build_parties(politicians, registry)

    messages = [m for d in debates for m in d["messages"]]
    # `analyzedAt` je nastaven pro každé vystoupení, nad kterým engine extrahoval
    # tvrzení (i ta, kde nenašel žádný rozpor). Čteme z engine_analyzed_ids, ne
    # z pole v korpusovém JSON — to je po Fázi A prázdné a engine ho neplní.
    analyzed = [m for m in messages if m.get("analyzedAt")]

    days = sorted({(d["sessionNumber"], d["date"]) for d in debates})
    dataset = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "source": STENO_INDEX,
            "term": debates[0]["term"],
            "chamber": debates[0]["chamber"],
            "sittingDays": [{"sessionNumber": s, "date": d} for s, d in days],
            "debateCount": len(debates),
            "messageCount": len(messages),
            "analyzedMessageCount": len(analyzed),
            "annotationCount": sum(len(m["annotations"]) for m in messages),
            "politicianCount": len(politicians),
            # Rozpad podle provenience. Po Fázi A jsou ruční ukázky odpojeny od
            # korpusu, takže `handAuthored` je vždy 0. `engine` roste, jakmile
            # run_pipeline.py proběhne a uloží tvrzení do engine.sqlite.
            "byProvenance": {
                "engine": len(engine_analyzed_ids),
                "handAuthored": 0,
            },
        },
        "parties": parties,
        "politicians": politicians,
        "debates": debates,
    }

    os.makedirs(TARGET_DIR, exist_ok=True)
    with io.open(TARGET_JSON, "w", encoding="utf-8") as handle:
        json.dump(dataset, handle, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(TARGET_JSON)
    print("zapsáno: {}".format(TARGET_JSON))
    print("  {} rozprav, {} vystoupení, {} řečníků, {} klubů".format(
        len(debates), len(messages), len(politicians), len(parties)))
    print("  analyzováno: {} z {} vystoupení, {} značek".format(
        len(analyzed), len(messages), dataset["meta"]["annotationCount"]))
    print("  velikost: {:.1f} MB".format(size / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
