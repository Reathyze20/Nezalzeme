"""
Text Cleaner & Normalizer for PSP ČR Parliamentary Transcripts.
Filters out formal and procedural parliamentary boilerplate phrases
while preserving exact text mapping for downstream character offset annotations.
"""

import re
from typing import Tuple, List, Dict, Any

# Common procedural boilerplate patterns in Czech Chamber of Deputies (PSP ČR)
PROCEDURAL_PATTERNS = [
    # Addressing presiding officer / chamber
    r"^(?:Vážená\s+)?(?:paní|pane)\s+(?:předsedající|předsedkyně|místopředsedkyně|předsedo|místopředsedo)[,\.]?\s*",
    r"^(?:Vážené\s+kolegyně|Vážení\s+kolegové|Vážené\s+paní\s+poslankyně|Vážení\s+páni\s+poslanci)[,\.]?\s*",
    r"^(?:Vážená\s+vládo|Vážená\s+sněmovno|Dámy\s+a\s+pánové)[,\.]?\s*",
    r"^(?:Děkuji\s+(?:vám\s+)?za\s+slovo[,\.]?\s*(?:vážená\s+paní\s+předsedající|vážený\s+pane\s+předsedající)?[,\.]?\s*)",
    r"^(?:Děkuji\s+pěkně\s+za\s+slovo[,\.]?\s*)",
    r"^(?:Děkuji,\s+paní\s+místopředsedkyně[,\.]?\s*)",
    r"^(?:Děkuji,\s+pane\s+místopředsedo[,\.]?\s*)",
    # Procedural notifications
    r"^(?:Dovolte\s+mi,\s+abych\s+načetl\s+omluvenku[,\.]?\s*)",
    r"^(?:Přihlašuji\s+se\s+(?:pouze\s+)?s\s+faktickou\s+poznámkou[,\.]?\s*)",
    r"^(?:Já\s+budu\s+velmi\s+stručný[,\.]?\s*)",
    r"^(?:Budu\s+reagovat\s+jenom\s+v\s+krátkosti\s+na\s+předřečníka[,\.]?\s*)",
    r"^(?:Dovolte\s+mi\s+krátkou\s+reakci\s+na\s+kolegu[,\.]?\s*)",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in PROCEDURAL_PATTERNS]

def clean_speech_text(raw_text: str) -> Tuple[str, int]:
    """
    Cleans raw speech text from PSP ČR by stripping procedural prefixes.
    Returns (cleaned_text, start_offset_removed).
    """
    text = raw_text.strip()

    changed = True
    while changed:
        changed = False
        for pattern in COMPILED_PATTERNS:
            match = pattern.match(text)
            if match:
                text = text[match.end():].lstrip()
                changed = True
                break

    # Also clean trailing procedural signoffs (e.g. "Děkuji za pozornost.")
    trailing_patterns = [
        r"\s*Děkuji\s+(?:vám\s+)?za\s+pozornost[\.!]*\s*$",
        r"\s*Děkuji[\.!]*\s*$",
    ]
    for tp in trailing_patterns:
        text = re.sub(tp, "", text, flags=re.IGNORECASE).strip()

    # Offset se odvozuje ze skutečné pozice zbytku v původním textu; sčítání
    # délek jednotlivých ořezů nesedělo, protože mezi nimi ubývaly i mezery.
    offset = raw_text.find(text) if text else len(raw_text)
    return text, offset


def verify_annotation_indices(clean_text: str, annotations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Validates that each annotation's `start` and `end` indices match `targetSnippet` exactly.
    Fixes slight boundary discrepancies if targetSnippet exists in cleanText.
    """
    validated = []
    for original in annotations:
        ann = dict(original)
        snippet = ann.get("targetSnippet", "")
        start = ann.get("start", 0)
        end = ann.get("end", len(snippet))

        actual_slice = clean_text[start:end]
        if actual_slice == snippet:
            validated.append(ann)
        else:
            # Attempt to locate snippet in text
            idx = clean_text.find(snippet)
            if idx != -1:
                ann["start"] = idx
                ann["end"] = idx + len(snippet)
                validated.append(ann)
            else:
                # Rozsah nelze dohledat — anotaci zahazujeme. Ponechat ji se
                # špatnými indexy by znamenalo zvýraznit v projevu jiné místo,
                # než ke kterému se důkaz vztahuje. Stejné pravidlo má
                # detector.normalize_annotation.
                print(f"[Warning] Snippet '{snippet[:30]}...' nenalezen, anotace zahozena")
    return validated
