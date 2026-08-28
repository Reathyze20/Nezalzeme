"""
Klasifikátor typu hlasování Poslanecké sněmovny PSP ČR.

Rozlišuje meritorní hlasování o zákonech od procedurálních návrhů (program,
odročení, noční jednání, volební akty). Slouží k eliminaci falešných pozitiv
v kategorii VOTE_MISMATCH.
"""

import re
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class VoteClassification:
    vote_type: str
    is_substantive: bool
    is_procedural: bool
    clean_subject: str
    matched_rule: str


# --------------------------------------------------------------------------
# Regex vzory pro jednotlivé kategorie
# --------------------------------------------------------------------------

# Závěrečná hlasování o zákonu (v PSP značena dvěma hvězdičkami nebo 'jako celek')
_FINAL_LAW_PATTERNS = [
    (re.compile(r"\*\*\s*$"), "psp_asterisk_final_reading"),
    (re.compile(r"\bjako\s+celek\b", re.I), "jako_celek"),
    (re.compile(r"návrh\s+(?:ústavního\s+)?zákona\s+.*?(?:3\.\s*čtení|třetí\s+čtení)", re.I), "treti_cteni"),
    (re.compile(r"vyslovení\s+(?:ne)?důvěry\s+vládě", re.I), "duvera_vlade"),
]

# Pozměňovací návrhy a dílčí hlasování k zákonu
_AMENDMENT_PATTERNS = [
    (re.compile(r"pozměňovac[íi]\s+návrh", re.I), "pozmenovaci_navrh"),
    (re.compile(r"\bzamítnutí\s+(?:návrhu|zákona|předlohy)\b", re.I), "zamitnuti_navrhu"),
    (re.compile(r"\bvrácení\s+(?:návrhu|zákona)\s+výboru\b", re.I), "vraceni_vyboru"),
    (re.compile(r"doprovodn[éé]\s+usnesení", re.I), "doprovodne_usneseni"),
    (re.compile(r"návrh\s+usnesení\s+k\s+", re.I), "navrh_usneseni_k"),
]

# Procedurální hlasování: pořad schůze
_AGENDA_PATTERNS = [
    (re.compile(r"^pořad\s+schůze", re.I), "porad_schuze"),
    (re.compile(r"změn[ay]\s+pořadu", re.I), "zmena_poradu"),
    (re.compile(r"(?:zařazení|vyřazení|přeřazení)\s+(?:nového\s+)?bodu", re.I), "zarazeni_bodu"),
    (re.compile(r"stanovení\s+pořadu", re.I), "stanoveni_poradu"),
]

# Procedurální hlasování: čas, odročení, přestávky
_ADJOURNMENT_PATTERNS = [
    (re.compile(r"přerušení\s+(?:schůze|jednání|bodu)", re.I), "preruseni_schuze"),
    (re.compile(r"odročení", re.I), "odroceni"),
    (re.compile(r"jednání\s+po\s+(?:21|24|14|19)\.?\s*hodin", re.I), "nocni_jednani"),
    (re.compile(r"zkrácení\s+řečnické\s+doby", re.I), "zkraceni_doby"),
    (re.compile(r"sloučen[áé]\s+rozprav[ay]", re.I), "sloucena_rozprava"),
]

# Stav legislativní nouze
_EMERGENCY_PATTERNS = [
    (re.compile(r"legislativní\s+nouz[ei]", re.I), "legislativni_nouze"),
]

# Personální a komisionální volby
_PERSONNEL_PATTERNS = [
    (re.compile(r"volebn[íi]\s+komis[ei]", re.I), "volebni_komise"),
    (re.compile(r"volb[ay]\s+(?:členů|předsed|místopředsed)", re.I), "volba_funkcionaru"),
    (re.compile(r"ustavení\s+(?:výboru|komise)", re.I), "ustaveni_komise"),
    (re.compile(r"ověřovatel", re.I), "overovatel"),
]

# Interpelace
_INTERPELLATION_PATTERNS = [
    (re.compile(r"odpověď\s+na\s+písemnou\s+interpelaci", re.I), "interpelace"),
]


def classify_vote(subject: str, number: Optional[int] = None) -> VoteClassification:
    """
    Klasifikuje hlasování PSP ČR na základě názvu předmětu hlasování.

    Vrací VoteClassification s přesným typem a příznakem is_substantive / is_procedural.
    """
    clean = (subject or "").strip()

    # 1. Procedurální: Pořad schůze
    for pat, rule in _AGENDA_PATTERNS:
        if pat.search(clean):
            return VoteClassification(
                vote_type="PROCEDURAL_AGENDA",
                is_substantive=False,
                is_procedural=True,
                clean_subject=clean,
                matched_rule=rule,
            )

    # 2. Procedurální: Přerušení, odročení, noční hodiny
    for pat, rule in _ADJOURNMENT_PATTERNS:
        if pat.search(clean):
            return VoteClassification(
                vote_type="PROCEDURAL_ADJOURNMENT",
                is_substantive=False,
                is_procedural=True,
                clean_subject=clean,
                matched_rule=rule,
            )

    # 3. Procedurální: Stav legislativní nouze
    for pat, rule in _EMERGENCY_PATTERNS:
        if pat.search(clean):
            return VoteClassification(
                vote_type="PROCEDURAL_EMERGENCY",
                is_substantive=False,
                is_procedural=True,
                clean_subject=clean,
                matched_rule=rule,
            )

    # 4. Procedurální: Personální volby a komise
    for pat, rule in _PERSONNEL_PATTERNS:
        if pat.search(clean):
            return VoteClassification(
                vote_type="PROCEDURAL_PERSONNEL",
                is_substantive=False,
                is_procedural=True,
                clean_subject=clean,
                matched_rule=rule,
            )

    # 5. Procedurální: Interpelace
    for pat, rule in _INTERPELLATION_PATTERNS:
        if pat.search(clean):
            return VoteClassification(
                vote_type="PROCEDURAL_INTERPELLATION",
                is_substantive=False,
                is_procedural=True,
                clean_subject=clean,
                matched_rule=rule,
            )

    # 6. Meritorní: Závěrečné hlasování o zákonu
    for pat, rule in _FINAL_LAW_PATTERNS:
        if pat.search(clean):
            return VoteClassification(
                vote_type="SUBSTANTIVE_FINAL",
                is_substantive=True,
                is_procedural=False,
                clean_subject=clean,
                matched_rule=rule,
            )

    # 7. Meritorní: Pozměňovací návrhy a usnesení
    for pat, rule in _AMENDMENT_PATTERNS:
        if pat.search(clean):
            return VoteClassification(
                vote_type="SUBSTANTIVE_AMENDMENT",
                is_substantive=True,
                is_procedural=False,
                clean_subject=clean,
                matched_rule=rule,
            )

    # Pokud začíná "Novela z." nebo "Zákon o", jde typicky o věcné hlasování k zákonu
    if re.search(r"^(?:Novela\s+z\.|Zákon\s+o|Vládní\s+návrh)", clean, re.I):
        return VoteClassification(
            vote_type="SUBSTANTIVE_FINAL",
            is_substantive=True,
            is_procedural=False,
            clean_subject=clean,
            matched_rule="law_prefix_fallback",
        )

    # Výchozí konzervativní klasifikace
    return VoteClassification(
        vote_type="PROCEDURAL_OTHER",
        is_substantive=False,
        is_procedural=True,
        clean_subject=clean,
        matched_rule="default_procedural_fallback",
    )


def is_valid_vote_mismatch(
    verbal_commitment: str,
    vote_of_speaker: str,
    classification: VoteClassification,
) -> Tuple[bool, str]:
    """
    Ověří, zda je rozdíl mezi slovním závazkem a hlasováním legitimní kandidát na VOTE_MISMATCH.

    Vrací (is_candidate, reason).
    """
    if classification.is_procedural:
        return False, f"Procedurální hlasování ({classification.vote_type}: {classification.matched_rule}) nelze párovat se stanoviskem k zákonu."

    if not verbal_commitment or not vote_of_speaker:
        return False, "Chybí slovní závazek nebo záznam o hlasování."

    # Normalizace
    comm = verbal_commitment.strip().upper()
    vote = vote_of_speaker.strip().upper()

    if comm == vote:
        return False, "Slovní závazek odpovídá hlasování (shoda)."

    return True, f"Meritorní rozpor ({classification.vote_type}): řečník deklaroval {comm}, ale hlasoval {vote}."
