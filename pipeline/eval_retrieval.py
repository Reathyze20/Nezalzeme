"""
Kvalitativní brána nad retrievalem a NLI (Fáze 3).

    python pipeline/eval_retrieval.py

Měří dvě věci ODDĚLENĚ, jak žádá plán — objeví se skutečný odpovídající
minulý výrok vůbec v top-K, které vybral bi-encoder (`retrieval.py`), a
shoduje se `nliRelation` cross-encoderu (`nli.py`) s ručním štítkem? Jde o
dvě různá selhání: retrieval, který nenajde kandidáta vůbec, se nedá
opravit lepším NLI, a naopak.

Na rozdíl od `eval_gold.py` (Fáze 1, čistě deterministický kód) je řetězec
retrieval -> NLI první skutečný model v enginu mimo LLM extrakci Claim.
Plán výslovně říká: dokud čísla neřeknou, že obecný vícejazyčný baseline
na češtině (konjunktiv, elipsy, procedurální formule) selhává, se
nepředpokládá potřeba doménového finetuningu. Proto jsou řádky
přesnosti/recallu POZOR (informativní), ne CHYBA — blokující zůstává jen
integrita samotných gold sad.
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nli import CrossEncoderNli, NLI_RELATIONS  # noqa: E402
from retrieval import BiEncoder, retrieve_candidates  # noqa: E402

GOLD_NLI_FILE = os.path.join(os.path.dirname(__file__), "data", "gold_nli.json")
GOLD_RETRIEVAL_FILE = os.path.join(os.path.dirname(__file__), "data", "gold_retrieval.json")

MIN_NLI_PAIRS = 12
MIN_PER_RELATION = 3
MIN_QUERIES = 8
TOP_K = 5


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


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def evaluate_nli(report: Report) -> None:
    pairs = load(GOLD_NLI_FILE)
    report.add("minimální velikost gold_nli.json", len(pairs), MIN_NLI_PAIRS,
                [] if len(pairs) >= MIN_NLI_PAIRS else ["jen {} párů".format(len(pairs))])

    by_relation = {r: 0 for r in NLI_RELATIONS}
    for pair in pairs:
        if pair.get("expectedRelation") in by_relation:
            by_relation[pair["expectedRelation"]] += 1
    coverage_problems = [
        "{} má jen {} párů, minimum je {}".format(r, n, MIN_PER_RELATION)
        for r, n in by_relation.items() if n < MIN_PER_RELATION
    ]
    report.add("pokrytí všech 3 vztahů v gold_nli.json",
                sum(1 for n in by_relation.values() if n >= MIN_PER_RELATION),
                len(NLI_RELATIONS), coverage_problems)

    print("Načítám cross-encoder NLI model...")
    nli = CrossEncoderNli()

    confusion = {expected: {predicted: 0 for predicted in NLI_RELATIONS} for expected in NLI_RELATIONS}
    mismatches = []
    for pair in pairs:
        # premise = historický výrok, hypothesis = aktuální výrok.
        result = nli.classify(pair["textB"], pair["textA"])
        predicted = result["nliRelation"]
        expected = pair["expectedRelation"]
        confusion[expected][predicted] += 1
        if predicted != expected:
            mismatches.append("{}: čekáno {}, vyšlo {} (scores={})".format(
                pair["pairId"], expected, predicted,
                {k: round(v, 2) for k, v in result["scores"].items()}))

    correct = sum(confusion[r][r] for r in NLI_RELATIONS)
    report.add("shoda NLI s gold štítkem ({})".format(nli.model_name), correct, len(pairs), mismatches, blocking=False)

    print("\nMatice záměn NLI (řádek = čekáno, sloupec = vyšlo):")
    print("  {:<15}{}".format("", "".join("{:>15}".format(r) for r in NLI_RELATIONS)))
    for expected in NLI_RELATIONS:
        total = sum(confusion[expected].values())
        recall = confusion[expected][expected] / total if total else float("nan")
        print("  {:<15}{}   (recall {:.2f})".format(
            expected, "".join("{:>15}".format(confusion[expected][p]) for p in NLI_RELATIONS), recall))
    print()


def evaluate_retrieval(report: Report) -> None:
    data = load(GOLD_RETRIEVAL_FILE)
    corpus, queries = data["corpus"], data["queries"]

    report.add("minimální počet retrieval dotazů", len(queries), MIN_QUERIES,
                [] if len(queries) >= MIN_QUERIES else ["jen {} dotazů".format(len(queries))])

    print("Načítám bi-encoder...")
    encoder = BiEncoder()
    now = datetime.now().isoformat()
    by_id = {c["claimId"]: c for c in corpus}

    hit = 0
    leaked = []
    recall_problems = []
    for query in queries:
        candidates = retrieve_candidates(query, corpus, encoder, top_k=TOP_K, retrieved_at=now)
        candidate_ids = [c.candidate_claim_id for c in candidates]

        if query["expectedMatchClaimId"] in candidate_ids:
            hit += 1
        else:
            recall_problems.append("{}: {} není v top-{} ({})".format(
                query["queryId"], query["expectedMatchClaimId"], TOP_K, candidate_ids))

        for candidate_id in candidate_ids:
            if by_id[candidate_id]["speakerIdOsoba"] != query["speakerIdOsoba"]:
                leaked.append("{}: kandidát {} patří jinému řečníkovi".format(query["queryId"], candidate_id))

    report.add("kandidáti jsou vždy téhož řečníka (same-speaker-only)",
                len(queries) - len(leaked), len(queries), leaked)
    report.add("recall@{} retrievalu ({})".format(TOP_K, encoder.model_name),
                hit, len(queries), recall_problems, blocking=False)


def main() -> int:
    report = Report()
    evaluate_nli(report)
    evaluate_retrieval(report)

    print(report.render())
    print()
    if report.ok():
        print("Gold sady pro Fázi 3 mají v pořádku schéma a pokrytí.")
        print("Přesnost NLI a recall retrievalu výše jsou POZOR řádky — informují rozhodnutí")
        print("o doménovém finetuningu, negatují build (viz otevřené riziko v plánu).")
        return 0
    print("Gold sady pro Fázi 3 narazily na regresi ve schématu/pokrytí — viz CHYBA výše.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
