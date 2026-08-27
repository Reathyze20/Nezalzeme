"""
Atomizace výroků do entity `Claim` (Fáze 2b).

Dekomponuje jedno vystoupení do atomických, kanonických tvrzení
`[Subjekt][Predikát][Objekt][Časový rámec][Podmínka]` podle Fáze 1–2
`SYSTEM_PROMPT` v `detector.py` — jen zúžených na samotnou extrakci, bez
retrievalu, NLI, adversariálního přezkumu a mediálního zarovnání, které
patří do Fází 3–6.

Tohle je první skutečné volání jazykového modelu v repozitáři. Rozhraní je
schválně malé a jednosměrné:

    build_claim_extraction_prompt(message) -> str      # čistá funkce, testovatelná bez sítě
    call_claim_extraction_model(payload) -> str         # jediné místo, které volá API
    parse_claims_response(raw_json, message) -> List[dict]  # čistá funkce, testovatelná bez sítě
    extract_claims(message) -> List[dict]               # sešívá všechny tři kroky

Vyžaduje `ANTHROPIC_API_KEY` v prostředí (stejná konvence jako zbytek
`anthropic` SDK) — bez něj `call_claim_extraction_model` skončí chybou SDK,
ne tichým výpadkem. `linkedFactIds` se extrakcí nechává prázdné; napárování
na `Fact` z `pipeline/psp/facts.py` je úkol Fáze 3 (retrieval).
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detector import CLAIM_CATEGORIES, SPEECH_ACTS, nearest_occurrence  # noqa: E402

REQUIRED_CLAIM_KEYS = (
    "subject", "predicate", "object", "timeFrame", "condition",
    "claimCategory", "speechAct", "rawSpan", "extractionConfidence",
)

CLAIM_EXTRACTION_MODEL = "claude-sonnet-5"

CLAIM_EXTRACTION_PROMPT = """# ROLE: ATOMIZACE VÝROKŮ (FÁZE 1–2)
Dostaneš jedno vystoupení poslance (`cleanText`). Tvým jediným úkolem je
rozložit ho na atomická, kanonická tvrzení — neposuzuješ pravdivost ani
rozpor, to patří dalším fázím.

1. Dekontextualizace: převeď zájmena a zástupné výrazy na konkrétní entity,
   jak jen to jde ze samotného textu vystoupení (bez vnějšího kontextu).
2. Pro každé samostatné tvrzení urči:
   - subject, predicate, object — volný text, ne uzavřený výčet,
   - timeFrame — explicitní časový rámec; není-li ve výroku vyjádřený, napiš
     "NEURČENO", nikdy si nedomýšlej "teď",
   - condition — podmínka, za které tvrzení platí; prázdný řetězec, není-li žádná,
   - claimCategory: FACTUAL_CLAIM (statistika, rozpočtové číslo, legislativní fakt),
     STANCE_COMMITMENT (normativní závazek/slib) nebo PROCEDURAL (formální
     vyjádření k proceduře jednání),
   - speechAct: OWN_STANCE (vlastní postoj), QUOTING_OPPONENT (citace/parafráze
     oponenta — nepřipisuje se řečníkovi) nebo RHETORICAL (ironie, hyperbola,
     metafora — mimo faktické ověřování). Jedno vystoupení může obsahovat
     tvrzení s různým speechAct zároveň.
   - rawSpan — přesný, doslovný úryvek z `cleanText`, ze kterého tvrzení
     pochází (bude se dohledávat zpět v textu, nesmí být parafrázovaný),
   - extractionConfidence — 0–1, jak věrně tvrzení odpovídá výroku.
3. Procedurální a čistě zdvořilostní věty (oslovení, poděkování za slovo)
   nerozkládej na FACTUAL_CLAIM/STANCE_COMMITMENT — označ je claimCategory
   PROCEDURAL.

Výstup je výhradně validní JSON pole, bez komentářů a bez textu okolo:
[
  {
    "subject": "...", "predicate": "...", "object": "...",
    "timeFrame": "...", "condition": "",
    "claimCategory": "STANCE_COMMITMENT", "speechAct": "OWN_STANCE",
    "rawSpan": "přesný úryvek z cleanText",
    "extractionConfidence": 0.9
  }
]
"""


def build_claim_extraction_prompt(message: Dict[str, Any]) -> str:
    """Sestaví vstupní payload pro extrakci (čistá funkce, bez volání API)."""
    payload = {
        "MESSAGE_ID": message.get("messageId"),
        "SPEAKER": message.get("speaker"),
        "CLEAN_TEXT": message.get("cleanText", ""),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def call_claim_extraction_model(payload: str, model: str = CLAIM_EXTRACTION_MODEL) -> str:
    """
    Jediné místo v modulu, které skutečně volá LLM.

    Import `anthropic` je schválně uvnitř funkce: čisté funkce
    (`build_claim_extraction_prompt`, `parse_claims_response`) tak jdou
    testovat i v prostředí bez nainstalovaného SDK.
    """
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=CLAIM_EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": payload}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _validate_raw_claim(raw: Dict[str, Any]) -> Optional[List[str]]:
    missing = [key for key in REQUIRED_CLAIM_KEYS if key not in raw]
    if missing:
        return missing
    return None


def parse_claims_response(raw_json: str, message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Rozparsuje výstup modelu do seznamu `Claim` slovníků a obnoví znakové
    indexy v `cleanText` (stejná logika jako `normalize_annotation`).

    Tvrzení, které se nepodaří dohledat v `cleanText`, se zahodí — stejné
    pravidlo jako u anotací: špatné indexy by ukazovaly na jiné místo
    projevu, než o kterém model mluvil.
    """
    clean_text = message.get("cleanText", "")
    speaker_id = message.get("source", {}).get("idOsoba", "")
    message_id = message.get("messageId", "")

    try:
        raw_claims = json.loads(raw_json)
    except json.JSONDecodeError as err:
        print("[-] {}: model nevrátil validní JSON ({})".format(message_id, err))
        return []
    if not isinstance(raw_claims, list):
        print("[-] {}: očekáváno pole tvrzení, přišlo {}".format(message_id, type(raw_claims).__name__))
        return []

    claims: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_claims, start=1):
        if not isinstance(raw, dict):
            continue
        missing = _validate_raw_claim(raw)
        if missing:
            print("[-] {}: tvrzení #{} postrádá {}".format(message_id, index, ", ".join(missing)))
            continue

        span = raw["rawSpan"]
        start = clean_text.find(span)
        if start == -1:
            start = nearest_occurrence(clean_text, span, None)
            if start is None:
                print("[-] {}: rawSpan {!r} nenalezen v cleanText, tvrzení zahozeno".format(
                    message_id, span[:60]))
                continue

        category = str(raw["claimCategory"]).strip().upper()
        speech_act = str(raw["speechAct"]).strip().upper()
        if category not in CLAIM_CATEGORIES:
            print("[-] {}: neznámá claimCategory {}, tvrzení zahozeno".format(message_id, category))
            continue
        if speech_act not in SPEECH_ACTS:
            print("[-] {}: neznámý speechAct {}, tvrzení zahozeno".format(message_id, speech_act))
            continue

        claims.append({
            "claimId": "{}-c{}".format(message_id, index),
            "messageId": message_id,
            "speakerIdOsoba": speaker_id,
            "subject": raw["subject"],
            "predicate": raw["predicate"],
            "object": raw["object"],
            "timeFrame": raw["timeFrame"],
            "condition": raw.get("condition", ""),
            "claimCategory": category,
            "speechAct": speech_act,
            "sourceCharStart": start,
            "sourceCharEnd": start + len(span),
            "rawSpan": span,
            "extractionConfidence": float(raw["extractionConfidence"]),
            "linkedFactIds": [],
        })
    return claims


def validate_claim(claim: Dict[str, Any], clean_text: str) -> List[str]:
    """Schéma-kontrola jednoho už rozparsovaného `Claim` (pro regresní testy)."""
    errors = []
    label = "claim {}".format(claim.get("claimId", "?"))

    start, end = claim.get("sourceCharStart"), claim.get("sourceCharEnd")
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end <= len(clean_text):
        errors.append("{}: indexy {}-{} mimo rozsah cleanText".format(label, start, end))
    elif clean_text[start:end] != claim.get("rawSpan"):
        errors.append("{}: indexy {}-{} neodpovídají rawSpan".format(label, start, end))

    if claim.get("claimCategory") not in CLAIM_CATEGORIES:
        errors.append("{}: neznámá claimCategory {}".format(label, claim.get("claimCategory")))
    if claim.get("speechAct") not in SPEECH_ACTS:
        errors.append("{}: neznámý speechAct {}".format(label, claim.get("speechAct")))

    confidence = claim.get("extractionConfidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0.0 <= confidence <= 1.0:
        errors.append("{}: extractionConfidence mimo rozsah 0-1".format(label))

    return errors


def extract_claims(message: Dict[str, Any], model: str = CLAIM_EXTRACTION_MODEL) -> List[Dict[str, Any]]:
    """Sešije prompt -> volání modelu -> parsování do jednoho kroku."""
    prompt_payload = build_claim_extraction_prompt(message)
    raw_response = call_claim_extraction_model(prompt_payload, model=model)
    return parse_claims_response(raw_response, message)


if __name__ == "__main__":
    # Self-test bez sítě a bez API klíče: ověřuje jen parse_claims_response
    # a validate_claim (deterministická část modulu). `call_claim_extraction_model`
    # se tady záměrně nevolá — živé volání LLM vyžaduje ANTHROPIC_API_KEY a
    # skutečné síťové spojení, které tenhle self-test nemá k dispozici.
    demo_message = {
        "messageId": "demo-001",
        "speaker": "Ukázková poslankyně",
        "cleanText": "Garantuji, že tato vláda nezvýší daně. Kolega tvrdil, že to je nemožné.",
        "source": {"idOsoba": "9999"},
    }
    canned_model_response = json.dumps([
        {
            "subject": "tato vláda", "predicate": "nezvýší", "object": "daně",
            "timeFrame": "po celé volební období", "condition": "",
            "claimCategory": "STANCE_COMMITMENT", "speechAct": "OWN_STANCE",
            "rawSpan": "Garantuji, že tato vláda nezvýší daně.",
            "extractionConfidence": 0.92,
        },
        {
            "subject": "kolega", "predicate": "tvrdil", "object": "je to nemožné",
            "timeFrame": "NEURČENO", "condition": "",
            "claimCategory": "FACTUAL_CLAIM", "speechAct": "QUOTING_OPPONENT",
            "rawSpan": "Kolega tvrdil, že to je nemožné.",
            "extractionConfidence": 0.85,
        },
        {
            # Chybí extractionConfidence -> musí se zahodit, ne spadnout.
            "subject": "x", "predicate": "y", "object": "z",
            "timeFrame": "NEURČENO", "condition": "",
            "claimCategory": "FACTUAL_CLAIM", "speechAct": "OWN_STANCE",
            "rawSpan": "neexistující úryvek",
        },
    ], ensure_ascii=False)

    claims = parse_claims_response(canned_model_response, demo_message)
    print("rozparsováno {} tvrzení (3. mělo selhat)".format(len(claims)))
    for claim in claims:
        errors = validate_claim(claim, demo_message["cleanText"])
        print("  {} speechAct={} claimCategory={} chyby={}".format(
            claim["claimId"], claim["speechAct"], claim["claimCategory"], errors))
