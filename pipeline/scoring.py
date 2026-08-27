"""
Kompozitní skóre — skládá finální confidenceScore z měřitelných signálů.

Sebehodnocení modelu přestává být jediný zdroj jistoty. Skóre se skládá z:

  - NLI pravděpodobnost CONTRADICTION z cross-encoderu (`nli.py`)
  - Kosinová podobnost z bi-encoder retrievalu (`retrieval.py`)
  - Shoda rolí tribunálu (žalobce + soudce)
  - U VOTE_MISMATCH: tvrdý SQL fakt z `facts.py` (1.0 nebo 0.0)
  - Sebehodnocení modelu (confidenceScore z arbitra)

Váhy jsou odborný úsudek. Kalibrační křivku fitovat až nad gold setem
z Fáze D — do té doby oba prahy zůstávají odborným úsudkem, a metodika
to má říkat.

    from scoring import compute_composite_score

    signals = {
        "p_contradiction": 0.87,
        "retrieval_similarity": 0.72,
        "role_match": True,
        "vote_hard_fact": None,   # nebo 1.0/0.0 u VOTE_MISMATCH
        "model_self_assessment": 0.91,
    }
    score = compute_composite_score(signals)
"""

from typing import Any, Dict, Optional

# --------------------------------------------------------------------------
# Váhy (odborný úsudek — kalibrační křivka po Fázi D)
# --------------------------------------------------------------------------

#: Běžné kategorie (CONTRADICTION_TIME, FACTUAL_MISSTATEMENT, VALUE_SHIFT).
_DEFAULT_WEIGHTS = {
    "p_contradiction": 0.35,
    "retrieval_similarity": 0.20,
    "role_match": 0.15,
    "model_self_assessment": 0.30,
}

#: VOTE_MISMATCH — tvrdý SQL fakt přebírá váhu od měkkých signálů.
_VOTE_MISMATCH_WEIGHTS = {
    "p_contradiction": 0.15,
    "retrieval_similarity": 0.10,
    "role_match": 0.10,
    "vote_hard_fact": 0.40,
    "model_self_assessment": 0.25,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_composite_score(
    signals: Dict[str, Any],
    is_vote_mismatch: bool = False,
) -> float:
    """
    Složí finální confidenceScore z měřitelných signálů.

    `signals` může obsahovat:
      - p_contradiction (float 0–1): NLI CONTRADICTION pravděpodobnost
      - retrieval_similarity (float 0–1): bi-encoder kosinová podobnost
      - role_match (bool): shoda žalobce + soudce v tribunálu
      - vote_hard_fact (float|None): 1.0 pokud SQL fakt potvrzuje rozpor,
                                      0.0 pokud ne, None pokud nejde o VM
      - model_self_assessment (float 0–1): confidenceScore z arbitra/modelu

    Chybějící signál se nahrazuje neutrální hodnotou 0.5 (neovlivňuje
    výsledek výrazně ani nahoru, ani dolů).

    Vrací float 0–1.
    """
    weights = _VOTE_MISMATCH_WEIGHTS if is_vote_mismatch else _DEFAULT_WEIGHTS

    total = 0.0
    weight_sum = 0.0

    for key, weight in weights.items():
        raw = signals.get(key)
        if raw is None:
            value = 0.5  # neutrální — signál chybí
        elif isinstance(raw, bool):
            value = 1.0 if raw else 0.0
        else:
            value = _clamp(float(raw))
        total += weight * value
        weight_sum += weight

    if weight_sum == 0.0:
        return 0.5

    return _clamp(total / weight_sum)


def build_signals_from_pipeline(
    nli_scores: Optional[Dict[str, float]] = None,
    retrieval_score: Optional[float] = None,
    tribunal_passed: Optional[bool] = None,
    arbiter_confidence: Optional[float] = None,
    vote_fact_confirmed: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Pomocná funkce pro `run_pipeline.py` — složí signály z výstupů
    jednotlivých fází do slovníku pro `compute_composite_score`.
    """
    signals: Dict[str, Any] = {}

    if nli_scores:
        signals["p_contradiction"] = nli_scores.get("CONTRADICTION", 0.5)

    if retrieval_score is not None:
        signals["retrieval_similarity"] = retrieval_score

    if tribunal_passed is not None:
        signals["role_match"] = tribunal_passed

    if arbiter_confidence is not None:
        signals["model_self_assessment"] = arbiter_confidence

    if vote_fact_confirmed is not None:
        signals["vote_hard_fact"] = 1.0 if vote_fact_confirmed else 0.0

    return signals


if __name__ == "__main__":
    # Self-test: typické hodnoty pro různé scénáře
    print("=== Kompozitní skóre — self-test ===")

    # Silný rozpor s potvrzeným NLI
    strong = compute_composite_score({
        "p_contradiction": 0.92,
        "retrieval_similarity": 0.85,
        "role_match": True,
        "model_self_assessment": 0.95,
    })
    print("silný rozpor: {:.3f} (čekáno > 0.90)".format(strong))
    assert strong > 0.85

    # Slabý signál
    weak = compute_composite_score({
        "p_contradiction": 0.45,
        "retrieval_similarity": 0.30,
        "role_match": False,
        "model_self_assessment": 0.60,
    })
    print("slabý signál: {:.3f} (čekáno < 0.80)".format(weak))
    assert weak < 0.80

    # VOTE_MISMATCH s tvrdým faktem
    vm_confirmed = compute_composite_score({
        "p_contradiction": 0.70,
        "retrieval_similarity": 0.50,
        "role_match": True,
        "vote_hard_fact": 1.0,
        "model_self_assessment": 0.85,
    }, is_vote_mismatch=True)
    print("VM potvrzený: {:.3f} (čekáno > 0.80)".format(vm_confirmed))
    assert vm_confirmed > 0.75

    # VOTE_MISMATCH bez potvrzení faktu
    vm_unconfirmed = compute_composite_score({
        "p_contradiction": 0.70,
        "retrieval_similarity": 0.50,
        "role_match": True,
        "vote_hard_fact": 0.0,
        "model_self_assessment": 0.85,
    }, is_vote_mismatch=True)
    print("VM nepotvrzený: {:.3f} (čekáno < VM potvrzený)".format(vm_unconfirmed))
    assert vm_unconfirmed < vm_confirmed

    # Chybějící signály → neutrální
    missing = compute_composite_score({})
    print("žádné signály: {:.3f} (čekáno ~0.50)".format(missing))
    assert 0.45 <= missing <= 0.55

    print("\nself-test OK")
