"""
Automatický gold set pro VOTE_MISMATCH z hlasovací knihy.

    python pipeline/build_gold_votes.py

Pro každé vystoupení, které má v `source.ballots` napárované hlasování, je
`voteOfSpeaker` tvrdý fakt. Skript heuristikou v `cleanText` hledá slovní
závazek k hlasování a porovná ho se skutečným hlasem → generuje reálné,
automaticky olabelované případy:

  - MISMATCH (pozitivní): řečník řekl X, hlasoval Y.
  - CONSISTENT (negativní): řečník řekl X, hlasoval X.

Výstup: `pipeline/data/gold_votes.json` — vstup pro nový `eval_gold.py`.

Pravidla:
  - Žádný případ s vymyšleným poslancem.
  - Každý odkazuje na existující messageId a ballotId.
  - verify_proof.py musí doložení potvrdit.
"""

import glob
import io
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PIPELINE_DIR)

from psp.vote_classifier import classify_vote, is_valid_vote_mismatch  # noqa: E402

DATA_DIR = os.path.join(PIPELINE_DIR, "data", "psp")
OUTPUT = os.path.join(PIPELINE_DIR, "data", "gold_votes.json")

# --------------------------------------------------------------------------
# Heuristika: slovní závazek k hlasování v cleanText
# --------------------------------------------------------------------------

# Vzory pro "budeme hlasovat PRO" / "nepodpoříme" / "ruku zdvihneme" atd.
_PRO_PATTERNS = [
    re.compile(r"(?:budem[eo]|budou)\s+hlasovat\s+pro\b", re.I),
    re.compile(r"(?:podpoří|podporuji|podpoříme|podporujeme)\b", re.I),
    re.compile(r"(?:hlasu[jJ]i|hlasujeme)\s+pro\b", re.I),
    re.compile(r"ruku\s+(?:zdvihnu|zdvihneme|zvedneme|zvednu)\b", re.I),
    re.compile(r"(?:naše|moje|naš[eí])\s+ano\b", re.I),
]

_PROTI_PATTERNS = [
    re.compile(r"(?:budem[eo]|budou)\s+hlasovat\s+proti\b", re.I),
    re.compile(r"(?:nepodpoří|nepodporuji|nepodpoříme|nepodporujeme)\b", re.I),
    re.compile(r"(?:hlasu[jJ]i|hlasujeme)\s+proti\b", re.I),
    re.compile(r"ruku\s+(?:nezdvihnu|nezdvihneme|nezvedneme|nezvednu)\b", re.I),
    re.compile(r"odmít(?:nu|neme|áme)\b", re.I),
]

_ABSTAIN_PATTERNS = [
    re.compile(r"(?:zdržím|zdržíme)\s+se\b", re.I),
]


def detect_verbal_commitment(clean_text: str) -> Optional[str]:
    """
    Hledá slovní závazek k hlasování v textu vystoupení.
    Vrací "PRO", "PROTI", "ZDRZEL_SE" nebo None.
    """
    # Hledáme v posledních 40 % textu — závazky typicky stojí na konci projevu.
    tail_start = max(0, int(len(clean_text) * 0.6))
    tail = clean_text[tail_start:]

    for pattern in _PRO_PATTERNS:
        if pattern.search(tail):
            return "PRO"
    for pattern in _PROTI_PATTERNS:
        if pattern.search(tail):
            return "PROTI"
    for pattern in _ABSTAIN_PATTERNS:
        if pattern.search(tail):
            return "ZDRZEL_SE"

    return None


# --------------------------------------------------------------------------
# Generování gold případů
# --------------------------------------------------------------------------

def extract_vote_cases(debates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extrahuje dvojice (slovní závazek, skutečný hlas) z korpusu."""
    cases: List[Dict[str, Any]] = []
    seen: set = set()

    for debate in debates:
        for msg in debate.get("messages", []):
            mid = msg.get("messageId", "")
            ballots = (msg.get("source") or {}).get("ballots", [])
            if not ballots:
                continue

            clean_text = msg.get("cleanText", "")
            commitment = detect_verbal_commitment(clean_text)
            if commitment is None:
                continue

            for ballot in ballots:
                vote = ballot.get("voteOfSpeaker")
                if not vote:
                    continue

                pair_key = "{}::{}".format(mid, ballot.get("ballotId", ""))
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                classification = classify_vote(ballot.get("subject", ""))
                is_mismatch, reason = is_valid_vote_mismatch(commitment, vote, classification)

                cases.append({
                    "caseId": "vm-{}-{}".format(
                        mid[:30], ballot.get("ballotId", "?")
                    ),
                    "category": "VOTE_MISMATCH",
                    "messageId": mid,
                    "speaker": msg.get("speaker", ""),
                    "date": msg.get("date", ""),
                    "ballotId": ballot.get("ballotId", ""),
                    "ballotUrl": ballot.get("url", ""),
                    "ballotSubject": ballot.get("subject", ""),
                    "voteType": classification.vote_type,
                    "isProcedural": classification.is_procedural,
                    "verbalCommitment": commitment,
                    "actualVote": vote,
                    "isMismatch": is_mismatch,
                    "validationReason": reason,
                    "expectedTier": "PUBLISHED" if is_mismatch else "DROPPED",
                    "expectedType": "VOTE_MISMATCH" if is_mismatch else None,
                    "sourceUrl": (msg.get("source") or {}).get("stenoUrl", ""),
                    "snippet": clean_text[max(0, int(len(clean_text)*0.6)):],
                })

    return cases


def load_corpus() -> List[Dict[str, Any]]:
    debates: List[Dict[str, Any]] = []
    for fpath in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        with io.open(fpath, encoding="utf-8") as handle:
            debates.extend(json.load(handle))
    return debates


def main() -> int:
    debates = load_corpus()
    if not debates:
        print("Žádná data v {}. Spusť nejdřív fetch_psp.py.".format(DATA_DIR))
        return 1

    cases = extract_vote_cases(debates)
    mismatches = [c for c in cases if c["isMismatch"]]
    consistent = [c for c in cases if not c["isMismatch"]]

    print("Nalezeno {} párů se slovním závazkem:".format(len(cases)))
    print("  MISMATCH (pozitivní): {}".format(len(mismatches)))
    print("  CONSISTENT (negativní): {}".format(len(consistent)))

    # Omezit negativní případy na max 2× počet pozitivních (balance)
    max_neg = max(len(mismatches) * 2, 50)
    if len(consistent) > max_neg:
        import random
        random.seed(42)
        consistent = random.sample(consistent, max_neg)
        print("  Negativní ořezány na {} (balance).".format(max_neg))

    gold = mismatches + consistent

    with io.open(OUTPUT, "w", encoding="utf-8") as handle:
        json.dump(gold, handle, ensure_ascii=False, indent=2)

    print("\nZapsáno {} případů do {}".format(len(gold), OUTPUT))

    # Statistiky
    speakers = sorted({c["speaker"] for c in gold})
    print("  Řečníků: {}".format(len(speakers)))
    print("  Řečníci (prví 10): {}".format(", ".join(speakers[:10])))

    return 0


if __name__ == "__main__":
    sys.exit(main())
