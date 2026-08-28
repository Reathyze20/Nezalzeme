"""
Příprava kandidátů pro ruční labeling (CONTRADICTION_TIME, FACTUAL_MISSTATEMENT, VALUE_SHIFT).

    python pipeline/prepare_gold_candidates.py [--count 10]

Vezme výstup run_pipeline.py z engine.sqlite (existující verdikty), pro každou
kategorii vybere top N kandidátů s nejvyšším NLI contradiction skóre a ke
každému připojí kontext (cleanText aktuální + cleanText historický).

Vygeneruje JSON šablonu `pipeline/data/gold_candidates.json`, do které vy
doplníte `expectedTier` a `expectedType`.

Pravidlo: žádný případ s vymyšleným poslancem; každý musí odkazovat na
existující messageId.
"""

import argparse
import glob
import io
import json
import os
import sys
from typing import Any, Dict, List, Optional

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PIPELINE_DIR, "data", "psp")
OUTPUT = os.path.join(PIPELINE_DIR, "data", "gold_candidates.json")

sys.path.insert(0, PIPELINE_DIR)

from db import open_engine_db  # noqa: E402
from psp.facts import ENGINE_SQLITE_PATH  # noqa: E402


def load_messages() -> Dict[str, Dict[str, Any]]:
    """Načte všechna vystoupení z korpusu, indexovaná messageId."""
    messages: Dict[str, Dict[str, Any]] = {}
    for fpath in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        with io.open(fpath, encoding="utf-8") as handle:
            debates = json.load(handle)
        for debate in debates:
            for msg in debate.get("messages", []):
                messages[msg["messageId"]] = msg
    return messages


def extract_candidates(conn, messages: Dict, count_per_category: int) -> List[Dict[str, Any]]:
    """Vybere top-N kandidátů z engine.sqlite pro ruční labeling."""

    # Všechny páry s CONTRADICTION a jejich verdikty
    rows = conn.execute("""
        SELECT n.pair_id, n.contradiction, n.nli_relation,
               p.claim_id_a, p.claim_id_b,
               ca.message_id AS msg_a, ca.claim_json AS claim_a_json,
               cb.message_id AS msg_b, cb.claim_json AS claim_b_json
        FROM nli_results n
        JOIN candidate_pairs p ON n.pair_id = p.pair_id
        JOIN claims ca ON p.claim_id_a = ca.claim_id
        JOIN claims cb ON p.claim_id_b = cb.claim_id
        WHERE n.nli_relation = 'CONTRADICTION'
        ORDER BY n.contradiction DESC
        LIMIT ?
    """, (count_per_category * 5,)).fetchall()  # extra buffer for filtering

    candidates: List[Dict[str, Any]] = []
    seen_messages: set = set()

    for row in rows:
        msg_a_id = row["msg_a"]
        msg_b_id = row["msg_b"]

        # Deduplicate by message pair
        pair_key = tuple(sorted([msg_a_id, msg_b_id]))
        if pair_key in seen_messages:
            continue
        seen_messages.add(pair_key)

        msg_a = messages.get(msg_a_id)
        msg_b = messages.get(msg_b_id)
        if not msg_a or not msg_b:
            continue

        claim_a = json.loads(row["claim_a_json"])
        claim_b = json.loads(row["claim_b_json"])

        candidates.append({
            "caseId": "manual-{}".format(len(candidates) + 1),
            "pairId": row["pair_id"],
            "contradictionScore": round(float(row["contradiction"]), 4),
            "messageIdCurrent": msg_a_id,
            "messageIdPast": msg_b_id,
            "speaker": msg_a.get("speaker", ""),
            "dateCurrent": msg_a.get("date", ""),
            "datePast": msg_b.get("date", ""),
            "claimCurrent": {
                "rawSpan": claim_a.get("rawSpan", ""),
                "subject": claim_a.get("subject", ""),
                "predicate": claim_a.get("predicate", ""),
                "object": claim_a.get("object", ""),
            },
            "claimPast": {
                "rawSpan": claim_b.get("rawSpan", ""),
                "subject": claim_b.get("subject", ""),
                "predicate": claim_b.get("predicate", ""),
                "object": claim_b.get("object", ""),
            },
            "contextCurrent": (msg_a.get("cleanText") or "")[:500],
            "contextPast": (msg_b.get("cleanText") or "")[:500],
            "sourceUrlCurrent": (msg_a.get("source") or {}).get("stenoUrl", ""),
            "sourceUrlPast": (msg_b.get("source") or {}).get("stenoUrl", ""),
            # --- DOPLŇTE RUČNĚ ---
            "expectedTier": "TODO",
            "expectedType": "TODO",
            "category": "TODO",
            "notes": "",
        })

        if len(candidates) >= count_per_category * 3:
            break

    return candidates


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Připraví kandidáty pro ruční labeling gold setu."
    )
    parser.add_argument(
        "--count", type=int, default=10,
        help="Počet kandidátů na kategorii (výchozí: 10).",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(ENGINE_SQLITE_PATH):
        print("engine.sqlite neexistuje ({}). Spusť nejdřív run_pipeline.py.".format(
            ENGINE_SQLITE_PATH))
        return 1

    conn = open_engine_db(ENGINE_SQLITE_PATH)
    messages = load_messages()
    if not messages:
        print("Žádná vystoupení v korpusu.")
        return 1

    candidates = extract_candidates(conn, messages, args.count)

    with io.open(OUTPUT, "w", encoding="utf-8") as handle:
        json.dump(candidates, handle, ensure_ascii=False, indent=2)

    print("Zapsáno {} kandidátů do {}".format(len(candidates), OUTPUT))
    print()
    print("Dalšá krok: otevřete soubor a doplňte 'expectedTier', 'expectedType'")
    print("a 'category' pro každý případ. Poté přesuňte olabelované případy")
    print("do gold_eval.json ve formátu kompatibilním s eval_gold.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
