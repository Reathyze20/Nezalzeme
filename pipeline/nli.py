"""
Cross-encoder NLI (Fáze 3, druhá polovina).

Rozhoduje o `NliRelation` mezi dvěma tvrzeními plnou cross-attention nad
oběma texty zároveň — na rozdíl od `retrieval.py`, který je jen kosinová
podobnost dvou samostatně spočtených embeddingů. Bi-encoder dělá levný
předvýběr top-K, tohle je skutečné rozhodnutí o (ne)rozporu.

Baseline je obecný vícejazyčný model (mDeBERTa-v3-xnli). Otevřené riziko z
plánu: na české parlamentní mluvě (konjunktiv, elipsy, procedurální
formule) může podávat slabší výkon než na jazycích, na kterých byl trénovaný
primárně. `pipeline/data/gold_nli.json` + `pipeline/eval_retrieval.py`
měří, jestli to tak skutečně je, než se uvažuje o doménovém finetuningu.
"""

from typing import Dict, List, Tuple
import torch

DEFAULT_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

NLI_RELATIONS = ("ENTAILMENT", "NEUTRAL", "CONTRADICTION")


class CrossEncoderNli:
    """Tenká obálka nad `transformers`, aby model šel v testech nahradit fake objektem."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.model_name = model_name
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._model.eval()
        # id2label je specifické pro každý checkpoint — nikdy nehardcodovat pořadí tříd.
        self._id2label = {int(i): str(label).upper() for i, label in self._model.config.id2label.items()}

    def classify_batch(self, pairs: List[Tuple[str, str]], batch_size: int = 32) -> List[Dict]:
        results = []
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            inputs = self._tokenizer(
                [p[0] for p in batch], [p[1] for p in batch],
                padding=True, truncation=True, return_tensors="pt"
            )
            with torch.no_grad():
                logits = self._model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)
            for j in range(len(batch)):
                scores = {self._id2label[k]: float(p) for k, p in enumerate(probs[j])}
                relation = max(scores, key=scores.get)
                if relation not in NLI_RELATIONS:
                    relation = "NEUTRAL"
                results.append({"nliRelation": relation, "scores": scores})
        return results

    def classify(self, premise: str, hypothesis: str) -> Dict:
        """
        `premise` = historický výrok, `hypothesis` = aktuální výrok — ptáme
        se, jestli aktuální výrok logicky obstojí vedle historického
        kontextu, ne naopak.
        """
        return self.classify_batch([(premise, hypothesis)])[0]


if __name__ == "__main__":
    # Malý self-test se skutečným modelem (vyžaduje síť napoprvé, pak cache HF Hubu).
    nli = CrossEncoderNli()
    cases = [
        ("Zvážíme navýšení sazby daně z příjmu fyzických osob o dva procentní body, pokud to schodek rozpočtu vyžádá.",
         "Garantuji, že tato vláda po celé volební období nezvýší sazbu daně z příjmu fyzických osob.",
         "CONTRADICTION"),
        ("Sazbu daně z příjmu fyzických osob nezvýšíme, to platilo od začátku a platí to i teď.",
         "Trváme na tom, že sazbu daně z příjmu fyzických osob nezvýšíme, ať se schodek vyvíjí jakkoliv.",
         "ENTAILMENT"),
        ("Prosazuji rozšíření sdílených úvazků ve státní správě.",
         "Podporuji zrychlení výstavby jaderných bloků.",
         "NEUTRAL"),
    ]
    results = nli.classify_batch([(c[0], c[1]) for c in cases])
    for i, (premise, hypothesis, expected) in enumerate(cases):
        result = results[i]
        mark = "OK" if result["nliRelation"] == expected else "NESHODA"
        print("[{}] cekano={:<13} vysledek={:<13} scores={}".format(
            mark, expected, result["nliRelation"],
            {k: round(v, 2) for k, v in result["scores"].items()}))
