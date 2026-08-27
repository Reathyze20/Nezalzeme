"""
Bi-encoder retrieval (Fáze 3, první polovina).

Najde pro dané tvrzení nejbližší kandidáty z historie **téhož řečníka** —
pravidlo "jen stejný řečník" veřejně deklaruje `src/app/metodika/page.tsx`
a retrieval napříč řečníky by ho porušil. Bi-encoder dělá jen levný
předvýběr top-K; o skutečném (ne)rozporu rozhoduje až cross-encoder NLI v
`pipeline/nli.py` s plnou cross-attention.

Žádná samostatná vektorová databáze: embeddingy se počítají za běhu jako
obyčejné numpy pole. `sqlite-vec` nad `pipeline/psp/facts.py` databází by
dávalo smysl při řádově větším korpusu; tady by šlo o první trvale běžící
službu v jinak staticky generovaném projektu.
"""

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@dataclass
class CandidatePair:
    """
    Mezientita mezi retrievalem a NLI. Drží obě fáze nezávisle testovatelné
    a odlišuje "retrieval kandidáta nenašel" od "NLI ho vyhodnotil jako
    NEUTRAL/ENTAILMENT" — dvě různé věci, které by se jinak slily do
    jednoho "nic se nenašlo".
    """
    claim_id: str
    candidate_claim_id: str
    bi_encoder_score: float
    rank: int
    retrieved_at: str


def claim_text(claim: Dict) -> str:
    """
    Kanonický text tvrzení k embeddingu.

    Zjednodušená gold fixtura (`gold_retrieval.json`) nese rovnou `text`;
    skutečný `Claim` z `pipeline/claims.py` ho skládá ze
    subjekt/predikát/objekt/časový rámec.
    """
    if "text" in claim:
        return claim["text"]
    parts = [claim.get("subject", ""), claim.get("predicate", ""), claim.get("object", "")]
    time_frame = claim.get("timeFrame")
    if time_frame and time_frame != "NEURČENO":
        parts.append("({})".format(time_frame))
    return " ".join(p for p in parts if p).strip()


class BiEncoder:
    """Tenká obálka nad `sentence-transformers`, aby model šel v testech nahradit fake objektem."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: List[str]) -> np.ndarray:
        # normalize_embeddings=True -> kosinová podobnost je prostý skalární součin.
        return np.asarray(self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False))


def retrieve_candidates(
    query_claim: Dict,
    corpus_claims: List[Dict],
    encoder: BiEncoder,
    top_k: int,
    retrieved_at: str,
) -> List[CandidatePair]:
    """
    Až `top_k` kandidátů ze `corpus_claims` **téhož řečníka**
    (`speakerIdOsoba`), seřazených podle kosinové podobnosti sestupně.

    Kandidát s vlastním `claimId` dotazu se vyřazuje — jinak by tvrzení
    vždy "kontradiktovalo" samo sebe s podobností 1.0.
    """
    speaker = query_claim["speakerIdOsoba"]
    same_speaker = [
        c for c in corpus_claims
        if c["speakerIdOsoba"] == speaker and c["claimId"] != query_claim.get("claimId")
    ]
    if not same_speaker:
        return []

    texts = [claim_text(query_claim)] + [claim_text(c) for c in same_speaker]
    vectors = encoder.embed(texts)
    query_vec, corpus_vecs = vectors[0], vectors[1:]
    scores = corpus_vecs @ query_vec

    order = np.argsort(-scores)[:top_k]
    return [
        CandidatePair(
            claim_id=query_claim.get("claimId", query_claim.get("queryId", "")),
            candidate_claim_id=same_speaker[i]["claimId"],
            bi_encoder_score=float(scores[i]),
            rank=rank + 1,
            retrieved_at=retrieved_at,
        )
        for rank, i in enumerate(order)
    ]


if __name__ == "__main__":
    # Malý self-test se skutečným modelem (vyžaduje síť napoprvé, pak cache
    # HF Hubu). Ne syntetický fake — chceme vidět, jak si multilingual
    # MiniLM reálně poradí s párem vět v češtině.
    from datetime import datetime

    corpus = [
        {"claimId": "a", "speakerIdOsoba": "x", "text": "Nezvýšíme daň z příjmu fyzických osob."},
        {"claimId": "b", "speakerIdOsoba": "x", "text": "Investice do digitalizace úřadů zdvojnásobíme."},
        {"claimId": "c", "speakerIdOsoba": "y", "text": "Nezvýšíme daň z příjmu fyzických osob."},
    ]
    query = {"claimId": "q", "speakerIdOsoba": "x", "text": "Garantujeme, že daň z příjmu fyzických osob zvyšovat nebudeme."}

    encoder = BiEncoder()
    now = datetime.now().isoformat()
    results = retrieve_candidates(query, corpus, encoder, top_k=5, retrieved_at=now)
    for pair in results:
        print("  rank={} candidate={} score={:.3f}".format(pair.rank, pair.candidate_claim_id, pair.bi_encoder_score))
    assert results[0].candidate_claim_id == "a", "nejbližší kandidát měl být 'a' (stejný řečník, stejné téma)"
    assert all(r.candidate_claim_id != "c" for r in results), "kandidát 'c' patří jinému řečníkovi a neměl se objevit"
    print("self-test OK: nejbližší je 'a', 'c' (jiný řečník) se neobjevilo")
