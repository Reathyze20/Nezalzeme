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

from typing import Dict

DEFAULT_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

NLI_RELATIONS = ("ENTAILMENT", "NEUTRAL", "CONTRADICTION")


class CrossEncoderNli:
    """Tenká obálka nad `transformers`, aby model šel v testech nahradit fake objektem."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.model_name = model_name
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._model.eval()
        # id2label je specifické pro každý checkpoint — nikdy nehardcodovat pořadí tříd.
        self._id2label = {int(i): str(label).upper() for i, label in self._model.config.id2label.items()}

    def classify(self, premise: str, hypothesis: str) -> Dict:
        """
        `premise` = historický výrok, `hypothesis` = aktuální výrok — ptáme
        se, jestli aktuální výrok logicky obstojí vedle historického
        kontextu, ne naopak.
        """
        inputs = self._tokenizer(premise, hypothesis, return_tensors="pt", truncation=True)
        with self._torch.no_grad():
            logits = self._model(**inputs).logits[0]
        probs = self._torch.softmax(logits, dim=-1).tolist()
        scores = {self._id2label[i]: p for i, p in enumerate(probs)}
        relation = max(scores, key=scores.get)
        if relation not in NLI_RELATIONS:
            relation = "NEUTRAL"
        return {"nliRelation": relation, "scores": scores}


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
    for premise, hypothesis, expected in cases:
        result = nli.classify(premise, hypothesis)
        mark = "OK" if result["nliRelation"] == expected else "NESHODA"
        print("[{}] cekano={:<13} vysledek={:<13} scores={}".format(
            mark, expected, result["nliRelation"],
            {k: round(v, 2) for k, v in result["scores"].items()}))
