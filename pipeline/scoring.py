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
    vote_is_procedural: Optional[bool] = None,
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

    if vote_is_procedural:
        # Procedurální hlasování (odročení, pořad) nemůže být penalizováno jako věcný rozpor
        signals["vote_hard_fact"] = 0.0
    elif vote_fact_confirmed is not None:
        signals["vote_hard_fact"] = 1.0 if vote_fact_confirmed else 0.0

    return signals



# ---------------------------------------------------------------------------
# Index konzistence poslance (Stance Consistency Index — SCI)
# ---------------------------------------------------------------------------

def compute_sci(
    total_commitments: int,
    contradiction_scores: list,
    threshold: float = 0.80,
) -> float:
    """
    Spočítá Index konzistence poslance (SCI_p) — míru názorové stálosti v čase.

    Vzorec:
        SCI_p = 1.0 - (1/N) * Σ w(c_i) * I(Score(c_i) >= threshold)

    Kde:
      - `total_commitments` (N): celkový počet atomických výroků typu
        STANCE_COMMITMENT daného poslance ze `claims` tabulky.
      - `contradiction_scores`: list kompozitních skóre (float 0–1) pro páry,
        které model označil jako rozpory (jsou to finální composite scores
        z `verdicts` tabulky, typ CONTEXT_DEVELOPMENT + PUBLISHED).
      - `threshold`: hranice, od které uvažujeme rozpor za „podstatný"
        (výchozí 0.80 = shodné s CONTEXT_DEVELOPMENT/PUBLISHED pásmem).

    Váha w(c_i) je rovna `Score(c_i)` samotné — silnější rozpor váží více.

    Returns:
        float 0–1, kde 1.0 = absolutní konzistence, 0.0 = maximální nestálost.
        Vrátí 1.0 pro poslance s 0 závazkovými výroky (žádná data).
    """
    if not total_commitments or total_commitments <= 0:
        return 1.0

    weighted_sum = sum(
        score for score in contradiction_scores if score >= threshold
    )
    # Normalizace váženým součtem dělená počtem závazků, ne počtem sporů.
    raw = weighted_sum / total_commitments
    return round(_clamp(1.0 - raw), 4)


def sci_label(sci: float) -> str:
    """Vrátí lidsky čitelný popis SCI skóre pro zobrazení na profilu poslance."""
    if sci >= 0.95:
        return "Vysoká konzistence"
    if sci >= 0.85:
        return "Mírně proměnlivé postoje"
    if sci >= 0.70:
        return "Znatelné obraty v čase"
    return "Výrazná nestálost postojů"


# ---------------------------------------------------------------------------
# Atribuční analýza obratu (Causal Flip Attribution)
# ---------------------------------------------------------------------------

# Čtyři diskrétní třídy příčiny obratu — viz popis v metodice.
FLIP_EXTERNAL_SHOCK = "EXTERNAL_SHOCK"
FLIP_COALITION_COMPROMISE = "COALITION_COMPROMISE"
FLIP_PROCEDURAL_EVASION = "PROCEDURAL_EVASION"
FLIP_OPPORTUNISTIC = "OPPORTUNISTIC_FLIP"


def compute_flip_attribution(
    arbiter_rationale: str,
    defense_evaluated: str,
    is_vote_mismatch: bool = False,
    macro_context_available: bool = False,
    macro_shock_confirmed: bool = False,
    composite_score: float = 0.0,
    defense_passed: bool = True,
) -> str:
    """
    Klasifikuje příčinu postav obratu do 4 diskrétních tříd.

    Pracuje na textovém výstupu Tribunálu — jednoduché klíčové fráze
    jsou lepší než přetěžování LLM dalším promptem.

    Pravidla (v pořadí priority):
      1. EXTERNAL_SHOCK — obhajoba odkazuje na vnější ekonomický nebo
         bezpečnostní šok a `macro_context_available` ho potvrzuje.
      2. COALITION_COMPROMISE — obhajoba odkazuje na koaliční vyjednávání
         (klíčová slova v rationale/defense text).
      3. PROCEDURAL_EVASION — jde o hlasování o procedurálním bodě
         (is_vote_mismatch + procedurální kontext) nebo je composite_score
         jen těsně nad prahem (< 0.82) se slabou Žalobcovou pozicí.
      4. OPPORTUNISTIC_FLIP — default; defense neobstála (defense_passed=True,
         tj. Soudce zamítl obhajobu) a jiná třída nebyla potvrzena.

    Returns:
        Jedna ze čtyř konstant FLIP_*.
    """
    rationale_lower = (arbiter_rationale or "").lower()
    defense_lower = (defense_evaluated or "").lower()
    combined = rationale_lower + " " + defense_lower

    # 1. Vnější šok (potvrzený makrodaty nebo explicitně zmíněný)
    external_keywords = [
        "inflac", "inflač", "recese", "hospodářsk", "ekonomick", "pandemie", "covid",
        "válk", "war", "energetick", "krize", "shock", "šok", "exogenní", "vnější šok",
        "úrokové sazby", "repo sazba", "cnb", "čnb",
    ]
    if any(kw in combined for kw in external_keywords):
        if macro_shock_confirmed or macro_context_available:
            return FLIP_EXTERNAL_SHOCK

    # 2. Koaliční kompromis
    coalition_keywords = [
        "koalic", "kompromis", "partner", "dohod", "vyjednáv", "pozměňovac",
        "koaliční smlouv", "vládní partner",
    ]
    if any(kw in combined for kw in coalition_keywords):
        return FLIP_COALITION_COMPROMISE

    # 3. Procedurální vyhýbání (slabé skóre nebo procedurální hlasování)
    if is_vote_mismatch and composite_score < 0.82:
        return FLIP_PROCEDURAL_EVASION
    procedural_keywords = [
        "odroč", "přerušen", "technick", "formáln", "procedur",
    ]
    if any(kw in combined for kw in procedural_keywords):
        return FLIP_PROCEDURAL_EVASION

    # 4. Výchozí: čistá oportunistická otočka
    return FLIP_OPPORTUNISTIC


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
