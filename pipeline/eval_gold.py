"""
Kvalitativní brána nad gold setem — měří precision/recall skutečného enginu.

    python pipeline/eval_gold.py

Vstupem PŘESTÁVÁ být ručně napsaný candidate a stává se jím vystoupení;
měří se, co engine skutečně najde. Precision a recall zvlášť, PUBLISHED
pásmo zvlášť — false positive v obviňujícím pásmu je jiná kategorie chyby
než v neutrálním.

Zdroje gold dat:
  - `pipeline/data/gold_eval.json` — ruční případy (CONTRADICTION_TIME,
    FACTUAL_MISSTATEMENT, VALUE_SHIFT + DROPPED/PUBLISHED/CONTEXT_DEVELOPMENT)
  - `pipeline/data/gold_votes.json` — automatické VOTE_MISMATCH případy
    z `build_gold_votes.py`

Zachovává oddělené měření recallu retrievalu od precision NLI
(`eval_retrieval.py` už tak je) — jinak nejde poznat, jestli engine minul
kandidáta, nebo ho zamítl.

Návratový kód 1 znamená, že aspoň jedna blokující kontrola selhala.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detector import (  # noqa: E402
    CANONICAL_TYPES,
    PRESENTATION_TIERS,
    apply_adversarial_verdict,
    apply_confidence_gate,
    get_presentation_tier,
    normalize_annotation,
)
from db import (  # noqa: E402
    load_annotations_for_message,
    open_engine_db,
)
from psp.facts import ENGINE_SQLITE_PATH  # noqa: E402

GOLD_EVAL_FILE = os.path.join(os.path.dirname(__file__), "data", "gold_eval.json")
GOLD_VOTES_FILE = os.path.join(os.path.dirname(__file__), "data", "gold_votes.json")

REJECT_REASONS = ("below_threshold", "dismissed_by_adversarial_check", "procedural_excluded")

#: Regresní pojistky proti tichému zúžení gold setu.
MIN_TOTAL_CASES = 20
MIN_PER_CATEGORY = 3
MIN_PER_TIER = 1


class Report:
    def __init__(self):
        self.checks = []

    def add(self, name, passed, total, problems=None, blocking=True):
        self.checks.append((name, passed, total, list(problems or []), blocking))

    def ok(self):
        return all(not problems for _, _, _, problems, blocking in self.checks if blocking)

    def render(self):
        lines = []
        for name, passed, total, problems, blocking in self.checks:
            share = "{}/{}".format(passed, total) if total else "n/a"
            mark = "OK   " if not problems else ("CHYBA" if blocking else "POZOR")
            lines.append("  [{}] {:<52} {}".format(mark, name, share))
            for problem in problems[:6]:
                lines.append("            - {}".format(problem))
            if len(problems) > 6:
                lines.append("            - ... a dalších {}".format(len(problems) - 6))
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Načtení gold dat
# --------------------------------------------------------------------------

def load_gold_eval_cases() -> List[Dict[str, Any]]:
    """Ruční gold případy z gold_eval.json (zpětná kompatibilita)."""
    if not os.path.exists(GOLD_EVAL_FILE):
        return []
    with open(GOLD_EVAL_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_gold_vote_cases() -> List[Dict[str, Any]]:
    """Automatické VOTE_MISMATCH případy z build_gold_votes.py."""
    if not os.path.exists(GOLD_VOTES_FILE):
        return []
    with open(GOLD_VOTES_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------
# Vyhodnocení ručních gold případů (deterministická vrstva — zpětná kompatibilita)
# --------------------------------------------------------------------------

def evaluate_deterministic_case(case: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """
    Prožene kandidátní anotaci deterministickou vrstvou enginu.
    Vrací (presentationTier, finální_typ_nebo_None).
    """
    clean_text = case["message"]["cleanText"]
    normalized = normalize_annotation(case["candidate"], clean_text)
    if normalized is None:
        return "DROPPED", None

    verdict = case.get("adversarialVerdict")
    if verdict is not None:
        normalized = apply_adversarial_verdict(normalized, verdict)
        if normalized is None:
            return "DROPPED", None

    published, context_development, _dropped = apply_confidence_gate([normalized])
    if published:
        return "PUBLISHED", published[0]["type"]
    if context_development:
        return "CONTEXT_DEVELOPMENT", context_development[0]["type"]
    return "DROPPED", None


# --------------------------------------------------------------------------
# Vyhodnocení proti engine.sqlite (skutečný engine)
# --------------------------------------------------------------------------

def evaluate_engine_case(
    case: Dict[str, Any], conn
) -> Tuple[str, Optional[str], int]:
    """
    Podívá se, co engine skutečně našel pro dané messageId v engine.sqlite.
    Vrací (actual_tier, actual_type, annotation_count).
    """
    mid = case.get("messageId") or case.get("message", {}).get("messageId", "")
    if not mid or not conn:
        return "DROPPED", None, 0

    annotations = load_annotations_for_message(conn, mid)
    if not annotations:
        return "DROPPED", None, 0

    # Najít nejvyšší tier
    best_tier = "DROPPED"
    best_type = None
    for ann in annotations:
        tier = ann.get("presentationTier", get_presentation_tier(ann.get("confidenceScore")))
        if tier == "PUBLISHED":
            best_tier = "PUBLISHED"
            best_type = ann.get("type")
            break
        elif tier == "CONTEXT_DEVELOPMENT" and best_tier != "PUBLISHED":
            best_tier = "CONTEXT_DEVELOPMENT"
            best_type = ann.get("type")

    return best_tier, best_type, len(annotations)


# --------------------------------------------------------------------------
# Precision / Recall metriky
# --------------------------------------------------------------------------

def compute_metrics(
    cases: List[Dict[str, Any]], conn
) -> Dict[str, Any]:
    """
    Počítá precision a recall zvlášť, PUBLISHED pásmo zvlášť.
    """
    tp_all = fp_all = fn_all = 0
    tp_pub = fp_pub = fn_pub = 0
    details: List[Dict] = []

    for case in cases:
        expected_tier = case.get("expectedTier", "DROPPED")
        expected_positive = expected_tier in ("PUBLISHED", "CONTEXT_DEVELOPMENT")
        expected_published = expected_tier == "PUBLISHED"

        actual_tier, actual_type, ann_count = evaluate_engine_case(case, conn)
        actual_positive = actual_tier in ("PUBLISHED", "CONTEXT_DEVELOPMENT")
        actual_published = actual_tier == "PUBLISHED"

        # All tiers
        if expected_positive and actual_positive:
            tp_all += 1
        elif not expected_positive and actual_positive:
            fp_all += 1
        elif expected_positive and not actual_positive:
            fn_all += 1

        # PUBLISHED only
        if expected_published and actual_published:
            tp_pub += 1
        elif not expected_published and actual_published:
            fp_pub += 1
        elif expected_published and not actual_published:
            fn_pub += 1

        details.append({
            "caseId": case.get("caseId", "?"),
            "expected": expected_tier,
            "actual": actual_tier,
            "match": expected_tier == actual_tier,
        })

    def safe_div(a, b):
        return a / b if b else float("nan")

    return {
        "precision_all": safe_div(tp_all, tp_all + fp_all),
        "recall_all": safe_div(tp_all, tp_all + fn_all),
        "tp_all": tp_all, "fp_all": fp_all, "fn_all": fn_all,
        "precision_published": safe_div(tp_pub, tp_pub + fp_pub),
        "recall_published": safe_div(tp_pub, tp_pub + fn_pub),
        "tp_pub": tp_pub, "fp_pub": fp_pub, "fn_pub": fn_pub,
        "details": details,
    }


# --------------------------------------------------------------------------
# Hlavní funkce
# --------------------------------------------------------------------------

def main() -> int:
    report = Report()

    # --- Načtení gold dat ---
    eval_cases = load_gold_eval_cases()
    vote_cases = load_gold_vote_cases()
    all_cases = eval_cases + vote_cases

    print("Gold set: {} ručních + {} VOTE_MISMATCH = {} celkem".format(
        len(eval_cases), len(vote_cases), len(all_cases)))

    # --- Pokrytí ---
    report.add("minimální velikost gold setu", len(all_cases), MIN_TOTAL_CASES,
                [] if len(all_cases) >= MIN_TOTAL_CASES else
                ["gold set má jen {} případů, minimum je {}".format(len(all_cases), MIN_TOTAL_CASES)])

    by_category = {t: 0 for t in CANONICAL_TYPES}
    for c in all_cases:
        cat = c.get("category")
        if cat in by_category:
            by_category[cat] += 1
    category_problems = [
        "kategorie {} má jen {} případů, minimum je {}".format(t, n, MIN_PER_CATEGORY)
        for t, n in by_category.items() if n < MIN_PER_CATEGORY
    ]
    report.add("pokrytí kategorií", sum(1 for n in by_category.values() if n >= MIN_PER_CATEGORY),
                len(CANONICAL_TYPES), category_problems, blocking=False)

    # --- Deterministická vrstva (zpětná kompatibilita s ručními případy) ---
    if eval_cases:
        tier_mismatches = []
        for case in eval_cases:
            if "candidate" not in case:
                continue
            actual_tier, actual_type = evaluate_deterministic_case(case)
            expected_tier = case.get("expectedTier")
            if actual_tier != expected_tier:
                tier_mismatches.append(
                    "{}: čekáno {}, vyšlo {}".format(case["caseId"], expected_tier, actual_tier)
                )
        report.add("shoda deterministické vrstvy (ruční případy)",
                    len(eval_cases) - len(tier_mismatches), len(eval_cases), tier_mismatches)

    # --- Engine precision/recall ---
    conn = None
    if os.path.exists(ENGINE_SQLITE_PATH):
        conn = open_engine_db(ENGINE_SQLITE_PATH)

    if conn:
        metrics = compute_metrics(all_cases, conn)
        print()
        print("=== Precision / Recall (celkový) ===")
        print("  TP={} FP={} FN={}".format(metrics["tp_all"], metrics["fp_all"], metrics["fn_all"]))
        print("  Precision: {:.3f}".format(metrics["precision_all"]))
        print("  Recall:    {:.3f}".format(metrics["recall_all"]))
        print()
        print("=== Precision / Recall (PUBLISHED pásmo) ===")
        print("  TP={} FP={} FN={}".format(metrics["tp_pub"], metrics["fp_pub"], metrics["fn_pub"]))
        print("  Precision: {:.3f}".format(metrics["precision_published"]))
        print("  Recall:    {:.3f}".format(metrics["recall_published"]))

        # False positives v PUBLISHED pásmu jsou nejhorší chyba
        pub_fp_problems = [
            d["caseId"] for d in metrics["details"]
            if d["actual"] == "PUBLISHED" and d["expected"] != "PUBLISHED"
        ]
        report.add("false positives v pásmu PUBLISHED",
                    len(all_cases) - len(pub_fp_problems), len(all_cases),
                    ["FP v PUBLISHED: {}".format(cid) for cid in pub_fp_problems[:10]],
                    blocking=False)

        # Neshody
        mismatches = [d for d in metrics["details"] if not d["match"]]
        if mismatches:
            print()
            print("Neshody (prvních 10):")
            for d in mismatches[:10]:
                print("  {} — čekáno {}, vyšlo {}".format(d["caseId"], d["expected"], d["actual"]))
    else:
        print()
        print("engine.sqlite neexistuje — engine precision/recall přeskočen.")
        print("Spusťte nejdřív: python pipeline/run_pipeline.py --schuze 10 --faze vse")

    # --- VOTE_MISMATCH specifické metriky ---
    if vote_cases and conn:
        vm_metrics = compute_metrics(vote_cases, conn)
        print()
        print("=== VOTE_MISMATCH zvlášť ===")
        print("  Precision: {:.3f}  Recall: {:.3f}".format(
            vm_metrics["precision_all"], vm_metrics["recall_all"]))

    print()
    print(report.render())
    print()

    if report.ok():
        print("Gold set prošel.")
        return 0
    print("Gold set narazil na regresi — viz CHYBA výše.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
