"""
Kvalitativní brána nad gold setem (pipeline/data/gold_eval.json).

    python pipeline/eval_gold.py

Fáze 1 cíleného plánu: bez sady ručně olabelovaných případů nejde měřit,
jestli retrieval, NLI ani adversariální tribunál (Fáze 2b–4) něco zlepšily
nebo zhoršily. Než tyhle fáze vzniknou, jediné, co dnes reálně rozhoduje o
tom, zda se anomálie zveřejní, je deterministická vrstva v `detector.py`
(`normalize_annotation`, `apply_adversarial_verdict`, `apply_confidence_gate`).
Tento skript ji proto pouští nad gold setem už teď — každý případ nese
`candidate` (kandidátní anotace, jak by ji navrhla Fáze 3/4) a volitelný
`adversarialVerdict` (ručně sepsaný verdikt, jak by ho měl vrátit Ďáblův
advokát / Soudce z Fáze 4) a `expectedTier` (Fáze 5: do kterého ze tří
prezentačních pásem má případ vyjít).

Až přibudou Fáze 2b–4, `candidate`/`adversarialVerdict` přestanou být ručně
psaná fixtura a začnou být živým výstupem modelu — srovnávací logika níže
(`evaluate_case`, `Report`) se nemění, mění se jen zdroj vstupu.

Návratový kód 1 znamená, že aspoň jedna blokující kontrola selhala.
"""

import json
import os
import sys

from detector import (
    PRESENTATION_TIERS,
    REQUIRED_PROOF_KEYS,
    apply_adversarial_verdict,
    apply_confidence_gate,
    normalize_annotation,
)

GOLD_FILE = os.path.join(os.path.dirname(__file__), "data", "gold_eval.json")

CANONICAL_TYPES = (
    "CONTRADICTION_TIME", "VOTE_MISMATCH", "FACTUAL_MISSTATEMENT", "VALUE_SHIFT",
)
REJECT_REASONS = ("below_threshold", "dismissed_by_adversarial_check", "procedural_excluded")

#: Regresní pojistky proti tichému zúžení gold setu při budoucích úpravách.
MIN_TOTAL_CASES = 20
MIN_PER_CATEGORY = 3
MIN_PER_REJECT_REASON = 1
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
            lines.append("  [{}] {:<40} {}".format(mark, name, share))
            for problem in problems[:6]:
                lines.append("            - {}".format(problem))
            if len(problems) > 6:
                lines.append("            - ... a dalších {}".format(len(problems) - 6))
        return "\n".join(lines)


def load_cases():
    with open(GOLD_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def check_raw_indices(case):
    """Znakové indexy kandidáta musí sedět v cleanText ještě před normalizací."""
    clean_text = case["message"]["cleanText"]
    ann = case["candidate"]
    start, end = ann.get("start"), ann.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return "{}: start/end nejsou celá čísla".format(case["caseId"])
    if not (0 <= start <= end <= len(clean_text)):
        return "{}: indexy {}-{} mimo rozsah cleanText".format(case["caseId"], start, end)
    if clean_text[start:end] != ann.get("targetSnippet"):
        return "{}: indexy {}-{} neodpovídají targetSnippet".format(case["caseId"], start, end)
    return None


def check_proof_complete(case):
    proof = case["candidate"].get("proof")
    if not isinstance(proof, dict):
        return "{}: candidate.proof není objekt".format(case["caseId"])
    missing = [key for key in REQUIRED_PROOF_KEYS if not proof.get(key)]
    if missing:
        return "{}: proof postrádá {}".format(case["caseId"], ", ".join(missing))
    return None


def evaluate_case(case):
    """
    Prožene kandidátní anotaci deterministickou vrstvou enginu a vrátí
    (`presentationTier`, finální_typ_nebo_None). Typ je `None` pro DROPPED —
    zahozený kandidát žádnou finální kategorii nenese.
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


def main():
    cases = load_cases()
    report = Report()

    # ---- schéma a doložitelnost kandidátů --------------------------------
    index_problems = [p for p in (check_raw_indices(c) for c in cases) if p]
    report.add("znakové indexy kandidátů sedí v cleanText", len(cases) - len(index_problems), len(cases), index_problems)

    proof_problems = [p for p in (check_proof_complete(c) for c in cases) if p]
    report.add("proof kandidátů je úplný", len(cases) - len(proof_problems), len(cases), proof_problems)

    unknown_tier = [
        "{}: neznámé expectedTier {!r}".format(c["caseId"], c.get("expectedTier"))
        for c in cases if c.get("expectedTier") not in PRESENTATION_TIERS
    ]
    report.add("expectedTier je jedno ze 3 pásem", len(cases) - len(unknown_tier), len(cases), unknown_tier)

    # ---- pokrytí gold setu -------------------------------------------------
    report.add("minimální velikost gold setu", len(cases), MIN_TOTAL_CASES,
                [] if len(cases) >= MIN_TOTAL_CASES else
                ["gold set má jen {} případů, minimum je {}".format(len(cases), MIN_TOTAL_CASES)])

    by_category = {t: 0 for t in CANONICAL_TYPES}
    for c in cases:
        if c.get("category") in by_category:
            by_category[c["category"]] += 1
    category_problems = [
        "kategorie {} má jen {} případů, minimum je {}".format(t, n, MIN_PER_CATEGORY)
        for t, n in by_category.items() if n < MIN_PER_CATEGORY
    ]
    report.add("pokrytí všech 4 kategorií", sum(1 for n in by_category.values() if n >= MIN_PER_CATEGORY),
                len(CANONICAL_TYPES), category_problems)

    by_tier = {t: 0 for t in PRESENTATION_TIERS}
    reject_reasons = {r: 0 for r in REJECT_REASONS}
    for c in cases:
        if c.get("expectedTier") in by_tier:
            by_tier[c["expectedTier"]] += 1
        if c.get("expectedTier") == "DROPPED":
            reason = c.get("rejectReason")
            if reason in reject_reasons:
                reject_reasons[reason] += 1
    tier_problems = [
        "pásmo {} má jen {} případů, minimum je {}".format(t, n, MIN_PER_TIER)
        for t, n in by_tier.items() if n < MIN_PER_TIER
    ]
    report.add("gold set pokrývá všechna 3 prezentační pásma",
                sum(1 for n in by_tier.values() if n >= MIN_PER_TIER), len(PRESENTATION_TIERS), tier_problems)

    reason_problems = [
        "chybí DROPPED případ s rejectReason {}".format(r)
        for r, n in reject_reasons.items() if n < MIN_PER_REJECT_REASON
    ]
    report.add("pokrytí důvodů DROPPED (práh / tribunál / procedurální)",
                sum(1 for n in reject_reasons.values() if n >= MIN_PER_REJECT_REASON),
                len(REJECT_REASONS), reason_problems)

    # ---- shoda s deterministickou vrstvou enginu ---------------------------
    # Dnes je gold set jediný test `normalize_annotation` / `apply_adversarial_verdict`
    # / `apply_confidence_gate` proti ručně rozhodnutým případům, a shoda musí
    # být 100 % — jde o deterministický kód, žádný model. Až Fáze 2b–4 nahradí
    # `candidate`/`adversarialVerdict` živým výstupem modelu, přestane to být
    # čistě deterministické a práh přesnosti/úplnosti se uvolní.
    confusion = {expected: {actual: 0 for actual in PRESENTATION_TIERS} for expected in PRESENTATION_TIERS}
    tier_mismatches = []
    type_mismatches = []
    for case in cases:
        actual_tier, actual_type = evaluate_case(case)
        expected_tier = case.get("expectedTier")
        confusion[expected_tier][actual_tier] += 1

        if actual_tier != expected_tier:
            tier_mismatches.append(
                "{}: čekáno {}, vyšlo {}".format(case["caseId"], expected_tier, actual_tier)
            )
        elif expected_tier in ("PUBLISHED", "CONTEXT_DEVELOPMENT"):
            expected_type = case.get("expectedType")
            if actual_type != expected_type:
                type_mismatches.append(
                    "{}: čekán typ {}, vyšel {}".format(case["caseId"], expected_type, actual_type)
                )

    report.add("shoda prezentačního pásma s gold labelem (trojcestná matice níže)",
                len(cases) - len(tier_mismatches), len(cases), tier_mismatches)
    typed_expected = sum(1 for c in cases if c.get("expectedTier") in ("PUBLISHED", "CONTEXT_DEVELOPMENT"))
    report.add("shoda finální kategorie u PUBLISHED/CONTEXT_DEVELOPMENT případů",
                typed_expected - len(type_mismatches), typed_expected, type_mismatches)

    print("Gold set: {} případů ({} kategorie, {} DROPPED s důvodem)".format(
        len(cases), sum(1 for n in by_category.values() if n > 0), sum(reject_reasons.values())))
    print()
    print("Trojcestná matice záměn (řádek = čekáno, sloupec = vyšlo):")
    header = "  {:<22}".format("") + "".join("{:>22}".format(t) for t in PRESENTATION_TIERS)
    print(header)
    for expected in PRESENTATION_TIERS:
        total = sum(confusion[expected].values())
        recall = confusion[expected][expected] / total if total else float("nan")
        row = "  {:<22}".format(expected) + "".join("{:>22}".format(confusion[expected][a]) for a in PRESENTATION_TIERS)
        print("{}   (recall {:.2f})".format(row, recall))
    print()
    print(report.render())
    print()

    if report.ok():
        print("Gold set prošel deterministickou vrstvou beze srážky.")
        return 0
    print("Gold set narazil na regresi — viz CHYBA výše.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
