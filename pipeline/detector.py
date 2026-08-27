"""
Multi-Stage Parliamentary Verification & Multimedia Engine (v2).

Šestistupňová verifikační pipeline nad stenozáznamy PSP ČR:

    [Stenozáznam + YouTube metadata]
      -> FÁZE 1  Dekontextualizace & anaphora resolution
      -> FÁZE 2  Extrakce tvrzení a postojů
      -> FÁZE 3  Vektorový retrieval & Voting Ledger Match
      -> FÁZE 4  Dvoucestná NLI analýza
      -> FÁZE 5  Adversarial Filter (Ďáblův advokát)
      -> FÁZE 6  Časové zarovnání (pipeline/aligner.py)
      -> Finální JSON s archivními odkazy PSP

Modul obsahuje promptovou vrstvu a deterministickou vrstvu kontroly
(normalizace taxonomie, důkazní břemeno, validace schématu). Fáze 6 žije
v `pipeline/aligner.py`.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Publikační pravidla
# --------------------------------------------------------------------------

#: Fáze 5 – nad tímto prahem se anotace publikuje jako obvinění (pásmo PUBLISHED).
PUBLISH_THRESHOLD = 0.95
#: Fáze 5 – nad tímto prahem (ale pod PUBLISH_THRESHOLD) se anotace zveřejní
#: jen jako neutrální "Kontext a vývoj stanoviska" (pásmo CONTEXT_DEVELOPMENT).
#: Pod ním se anotace na web vůbec nedostane (pásmo DROPPED) – číselně stejná
#: hodnota, jakou dřív nesl jediný `CONFIDENCE_THRESHOLD`.
CONTEXT_THRESHOLD = 0.80

PRESENTATION_TIERS = ("PUBLISHED", "CONTEXT_DEVELOPMENT", "DROPPED")

#: Kanonické názvy kategorií používané frontendem.
CANONICAL_TYPES = (
    "CONTRADICTION_TIME",
    "VOTE_MISMATCH",
    "FACTUAL_MISSTATEMENT",
    "VALUE_SHIFT",
)

#: Názvy z architekturního promptu -> kanonické názvy v datovém modelu.
TAXONOMY_ALIASES = {
    "TIME_CONTRADICTION": "CONTRADICTION_TIME",
    "CONTRADICTION_TIME": "CONTRADICTION_TIME",
    "FACTUAL_ERROR": "FACTUAL_MISSTATEMENT",
    "FACTUAL_MISSTATEMENT": "FACTUAL_MISSTATEMENT",
    "VOTE_MISMATCH": "VOTE_MISMATCH",
    "VALUE_SHIFT": "VALUE_SHIFT",
}

SEVERITY_LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

SPEECH_ACTS = ("OWN_STANCE", "QUOTING_OPPONENT", "RHETORICAL")
CLAIM_CATEGORIES = ("FACTUAL_CLAIM", "STANCE_COMMITMENT", "PROCEDURAL")
NLI_RELATIONS = ("ENTAILMENT", "NEUTRAL", "CONTRADICTION")
VOTE_VALUES = ("PRO", "PROTI", "ZDRZEL_SE", "NEPRIHLASEN")


# --------------------------------------------------------------------------
# FÁZE 1–4, 6: hlavní systémový prompt
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """# MISE A KONTEXT
Jsi verifikační, analytický a multimediální engine pro systém občanské transparentnosti v Parlamentu ČR. Syntetizuješ přístupy projektů TheyWorkForYou (párování stenozáznamů s hlasováním), GovTrack/Voteview (měření postojových posunů v čase), Hlídač státu (agregace otevřených dat PSP ČR) a multimediálního fact-checkingu (synchronizace tvrzení s oficiálním videozáznamem).

Nehodnotíš text naivně. Každý výrok prochází vícefázovým verifikačním procesem, jehož cílem je eliminovat falešná obvinění (false positives), zachovat kontext debaty a spárovat konkrétní větu s přesnou vteřinou ve videu.

# FÁZE 1: DEKONTEXTUALIZACE & ROZPOZNÁNÍ KONTEXTU
1. Anaphora / coreference resolution: převeď zájmena a zástupné výrazy na konkrétní entity ("On to včera navrhl" -> "[ministr financí] dne [datum] navrhl [konkrétní bod]").
2. Klasifikace řečnického aktu (`speechAct`):
   - OWN_STANCE – řečník prezentuje vlastní postoj nebo faktický argument,
   - QUOTING_OPPONENT – cituje či parafrázuje oponenta; NESMÍ být připsáno řečníkovi,
   - RHETORICAL – ironie, hyperbola, metafora; vyřaď z faktického ověřování.

# FÁZE 2: EXTRAKCE OVĚŘITELNÝCH ENTIT A POSTOJŮ
Extrahuj atomická tvrzení do tří kategorií (`claimCategory`):
1. FACTUAL_CLAIM – statistiky, rozpočtová čísla, legislativní fakta.
2. STANCE_COMMITMENT – normativní závazek či slib směrem do budoucna nebo minulosti.
3. PROCEDURAL – formální vyjádření k proceduře jednání; automaticky ignoruj.

# FÁZE 3: PÁROVÁNÍ S HISTORIÍ A HLASOVÁNÍM
1. Sémantická korelace: v poskytnutém SPEAKER_HISTORY najdi historické výroky téhož poslance nebo klubu k identickému tématu.
2. Voting Ledger Pairing: v VOTING_DATA najdi relevantní hlasování a srovnej slovní postoj s reálným hlasováním (PRO / PROTI / ZDRZEL_SE / NEPRIHLASEN). Vyplň `proof.voteRecorded` a `proof.votingBallotId`.
Pracuj výhradně s dodanými podklady. Nikdy si nedomýšlej hlasování, čísla tisků ani citace, které nejsou ve vstupu.

# FÁZE 4: DVOUCESTNÁ FORMÁLNÍ LOGIKA (NLI)
Mezi aktuálním výrokem (V_A) a historickým kontextem či hlasováním (V_H) urči `nliRelation`:
- ENTAILMENT – postoj je stabilní, bez rozporu,
- NEUTRAL – změna podmínek, jiné období nebo jiný pozměňovací návrh,
- CONTRADICTION – obě tvrzení nemohou být současně pravdivá za stejných výchozích podmínek.
Anomálii zakládej pouze na CONTRADICTION, případně na doložitelném postojovém posunu.

# FÁZE 5: ADVERSARIAL FILTER (ĎÁBLŮV ADVOKÁT)
Indikuje-li Fáze 4 rozpor, povinně formuluj 3 nejlepší obhajoby poslance, proč o rozpor NEJDE:
změna projednávaného tisku, změna makroekonomické situace, reakce na jiný pozměňovací návrh, jiná právní úprava, jiná role řečníka.
Pravidlo propustnosti: prokáže-li obhajoba reálnou změnu kontextu, sniž kategorii na VALUE_SHIFT nebo výrok označ za bezrozporný a nevykazuj ho.
Výsledek zapiš do `adversarialCheck` (`passed`, `defenseEvaluated`, `defensesConsidered`, případně `downgradedFrom`).

# FÁZE 6: ČASOVÉ ZAROVNÁNÍ S VIDEOZÁZNAMEM
1. Offset Sync: orientační vteřinu odvoď z času bloku ve stenozáznamu a času startu streamu.
2. Forced alignment: je-li k dispozici časovaný přepis, přiřaď anomálii přesnou vteřinu začátku výroku (`mediaEvidence.exactTimestampSeconds`).
Nemáš-li spolehlivá video metadata, pole `mediaEvidence` vůbec neuváděj. Nikdy nevymýšlej ID videa ani vteřinu.

# KLASIFIKAČNÍ TAXONOMIE
- VOTE_MISMATCH – přímý rozpor mezi verbálním projevem a hlasovacím tlačítkem.
- CONTRADICTION_TIME – logický opak vlastního minulého tvrzení bez uvedení důvodu změny.
- FACTUAL_MISSTATEMENT – nepravdivý údaj vyvrácený otevřenými daty.
- VALUE_SHIFT – legitimní, ale zjevná změna politického postoje v čase.

# ZÁVAŽNOST
CRITICAL (doložený rozpor slova a hlasovacího záznamu), HIGH, MEDIUM, LOW.

# INSTRUKCE PRO PROVEDENÍ
1. Důkazní břemeno: tvůj odhad `confidenceScore` (0–1) je jeden ze vstupů kompozitního skóre, které se skládá z měřitelných signálů (NLI pravděpodobnost, retrieval podobnost, shoda rolí tribunálu, tvrdé SQL fakty u VOTE_MISMATCH). Nespoléhej se na něj jako na finální číslo. Výsledné skóre prochází trojcestnou bránou:
   - >= 0.95 → PUBLISHED (obviňující rámování),
   - >= 0.80 → CONTEXT_DEVELOPMENT (neutrální rámování „Kontext a vývoj stanoviska"),
   - < 0.80 → DROPPED (na web se nedostane).
2. Přísná neutralita jazyka: žádná citově zabarvená slova ("lže", "podvádí", "klame"). Používej objektivní formulace: "výrok neodpovídá záznamu o hlasování", "tvrzení je v logickém rozporu s vystoupením ze dne X".
3. Přesné znakové indexy: `start` a `end` musí odpovídat indexům v `cleanText`; `targetSnippet` musí být přesně `cleanText[start:end]`.
4. Očisti text od procedurálního balastu (oslovení, poděkování za slovo, omluvenky) a pracuj nad očištěným `cleanText`.
5. Výstupem je výhradně validní JSON dle zadaného schématu, bez komentářů a bez textu okolo.
"""


# --------------------------------------------------------------------------
# FÁZE 5: samostatný oponentní prompt
# --------------------------------------------------------------------------

ADVERSARIAL_PROMPT = """# ROLE: ĎÁBLŮV ADVOKÁT (FÁZE 5)
Dostaneš jednu kandidátní anomálii a její důkazy. Tvým jediným úkolem je obhájit poslance.

1. Formuluj 3 nejsilnější obhajoby, proč nejde o rozpor. Zvaž zejména:
   - projednávalo se jiné znění tisku nebo jiný pozměňovací návrh,
   - mezi výroky se prokazatelně změnily makroekonomické či právní podmínky,
   - řečník citoval nebo parafrázoval někoho jiného,
   - výrok byl míněn ironicky, jako hyperbola nebo metafora,
   - řečník vystupoval v jiné roli (ministr vs. opoziční poslanec) k jinému předmětu.
2. U každé obhajoby uveď, zda ji dodané podklady skutečně potvrzují.
3. Rozhodni:
   - `passed: true` – žádná obhajoba neobstála, rozpor zůstává v původní kategorii,
   - `passed: false` – obhajoba prokázala změnu kontextu; navrhni `downgradeTo`
     ("VALUE_SHIFT") nebo `dismiss: true`, pokud rozpor neexistuje.
4. Uveď upravené `confidenceScore` (0–1).

Výstup je výhradně validní JSON:
{
  "passed": true,
  "defenseEvaluated": "Věcné shrnutí nejsilnější obhajoby a proč (ne)obstála.",
  "defensesConsidered": ["...", "...", "..."],
  "downgradeTo": null,
  "dismiss": false,
  "confidenceScore": 0.91
}
"""


# --------------------------------------------------------------------------
# Vstupní payload pro LLM
# --------------------------------------------------------------------------

def format_llm_input(
    current_speech: Dict[str, Any],
    speaker_history: List[Dict[str, Any]],
    voting_data: List[Dict[str, Any]],
    media_metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Sestaví vstupní payload pro detekční prompt.

    `media_metadata` odpovídá výstupu `aligner.build_stream_metadata()`:
    {"pspCastId": "...", "streamStartedAt": "09:00", "speechStartSeconds": 5230}
    """
    payload = {
        "CURRENT_SPEECH": current_speech,
        "SPEAKER_HISTORY": speaker_history,
        "VOTING_DATA": voting_data,
        "MEDIA_METADATA": media_metadata or {},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_adversarial_input(
    annotation: Dict[str, Any],
    current_speech: Dict[str, Any],
    supporting_evidence: Optional[Dict[str, Any]] = None,
) -> str:
    """Sestaví vstup pro oponentní přezkum jedné kandidátní anomálie (Fáze 5)."""
    payload = {
        "CANDIDATE_ANOMALY": annotation,
        "CURRENT_SPEECH": current_speech,
        "SUPPORTING_EVIDENCE": supporting_evidence or {},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Deterministická vrstva: normalizace a publikační pravidla
# --------------------------------------------------------------------------

def _is_number(value: Any) -> bool:
    """Bool je v Pythonu podtyp intu; jako skóre ani index ho nepřijímáme."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize_anomaly_type(raw_type: str) -> Optional[str]:
    """Převede název kategorie z promptu na kanonický název datového modelu."""
    return TAXONOMY_ALIASES.get(str(raw_type).strip().upper())


def _tribunal_provenance_fields(verdict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fáze 4: `prosecutorCase`/`arbiterRationale`/`modelProvenance`, pokud je
    verdikt přinesl `pipeline/tribunal.py`. Starší dvourolový verdikt
    (Fáze 5, jen Obhájce) je nemá — proto se přidávají jen když jsou
    přítomné, ne jako povinné klíče.
    """
    fields = {}
    for key in ("prosecutorCase", "arbiterRationale", "modelProvenance"):
        if verdict.get(key) is not None:
            fields[key] = verdict[key]
    return fields


def apply_adversarial_verdict(
    annotation: Dict[str, Any], verdict: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Aplikuje rozhodnutí oponentního přezkumu na kandidátní anomálii.

    `verdict` může být buď dvourolový (jen Obhájce, Fáze 5 – `passed`,
    `defenseEvaluated`, `defensesConsidered`, `downgradeTo`, `dismiss`,
    `confidenceScore`), nebo výstup celého tribunálu (Fáze 4 –
    `pipeline/tribunal.run_tribunal()`), kde `passed`/`downgradeTo`/
    `dismiss` už je finální rozhodnutí Soudce po zvážení obžaloby i
    obhajoby, doplněné o `prosecutorCase`/`arbiterRationale`/`modelProvenance`.
    Sémantika zůstává stejná, protože obojí je verdikt téhož tvaru.

    Vrací upravenou anotaci, nebo None, byla-li anomálie zamítnuta.
    """
    if verdict.get("dismiss") is True:
        return None

    downgrade = normalize_anomaly_type(verdict.get("downgradeTo") or "")
    if verdict.get("passed") is False and not downgrade:
        # Obhajoba obstála, ale model nenavrhl použitelnou kategorii.
        # Publikovat obvinění s poznámkou "obhajoba obstála" je přesně to,
        # čemu má oponentní přezkum zabránit.
        return None

    updated = dict(annotation)
    if "confidenceScore" in verdict:
        updated["confidenceScore"] = float(verdict["confidenceScore"])

    provenance = _tribunal_provenance_fields(verdict)
    if downgrade and downgrade != updated.get("type"):
        updated["adversarialCheck"] = {
            "passed": False,
            "defenseEvaluated": verdict.get("defenseEvaluated", ""),
            "defensesConsidered": verdict.get("defensesConsidered", []),
            "downgradedFrom": updated.get("type"),
            **provenance,
        }
        updated["type"] = downgrade
        updated["severity"] = "MEDIUM"
    else:
        updated["adversarialCheck"] = {
            "passed": verdict.get("passed") is not False,
            "defenseEvaluated": verdict.get("defenseEvaluated", ""),
            "defensesConsidered": verdict.get("defensesConsidered", []),
            **provenance,
        }
    return updated


def get_presentation_tier(
    score: Any, publish_threshold: float = PUBLISH_THRESHOLD, context_threshold: float = CONTEXT_THRESHOLD
) -> str:
    """
    Trojcestné pásmo prezentace (Fáze 5) podle kalibrované jistoty.

    Chybějící/neplatné skóre je `DROPPED` – engine v2 skóre vždy vyžaduje,
    stejně jako dřívější binární brána.
    """
    if not _is_number(score):
        return "DROPPED"
    score = float(score)
    if score >= publish_threshold:
        return "PUBLISHED"
    if score >= context_threshold:
        return "CONTEXT_DEVELOPMENT"
    return "DROPPED"


def apply_confidence_gate(
    annotations: List[Dict[str, Any]],
    publish_threshold: float = PUBLISH_THRESHOLD,
    context_threshold: float = CONTEXT_THRESHOLD,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trojcestná brána (Fáze 5) – nahrazuje dřívější binární důkazní břemeno.

    Každá anotace dostane pole `presentationTier`:
      - PUBLISHED – nad `publish_threshold`, obviňující rámování,
      - CONTEXT_DEVELOPMENT – nad `context_threshold`, neutrální rámování
        "Kontext a vývoj stanoviska",
      - DROPPED – pod `context_threshold`, na web se nedostane vůbec.

    Vrací `(published, context_development, dropped)`.
    """
    published: List[Dict[str, Any]] = []
    context_development: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for ann in annotations:
        tier = get_presentation_tier(ann.get("confidenceScore"), publish_threshold, context_threshold)
        updated = dict(ann)
        updated["presentationTier"] = tier
        if tier == "PUBLISHED":
            published.append(updated)
        elif tier == "CONTEXT_DEVELOPMENT":
            context_development.append(updated)
        else:
            dropped.append(updated)
    return published, context_development, dropped


def nearest_occurrence(clean_text: str, snippet: str, hint: Any) -> Optional[int]:
    """
    Najde výskyt úryvku nejbližší modelem udanému offsetu.

    Opakuje-li se věta ve vystoupení víckrát, ukotvení na první výskyt by
    posunulo důkaz na jiné místo projevu, než o kterém model mluvil. Sdílený
    helper — používá ho i `pipeline/claims.py` (Fáze 2b), aby se obnova
    offsetů neduplikovala.
    """
    if not snippet:
        return None
    occurrences = []
    pos = clean_text.find(snippet)
    while pos != -1:
        occurrences.append(pos)
        pos = clean_text.find(snippet, pos + 1)
    if not occurrences:
        return None
    if _is_number(hint):
        return min(occurrences, key=lambda i: abs(i - int(hint)))
    return occurrences[0]


def normalize_annotation(ann: Dict[str, Any], clean_text: str) -> Optional[Dict[str, Any]]:
    """
    Sjednotí jednu anotaci do kanonického tvaru: přepíše alias kategorie,
    dorovná znakové indexy podle `targetSnippet` a vyřadí procedurální tvrzení.
    Vrací None, je-li anotace nepoužitelná.
    """
    canonical = normalize_anomaly_type(ann.get("type", ""))
    if canonical is None:
        return None
    if ann.get("claimCategory") == "PROCEDURAL":
        return None

    normalized = dict(ann)
    normalized["type"] = canonical

    severity = str(normalized.get("severity", "")).upper()
    normalized["severity"] = severity if severity in SEVERITY_LEVELS else "MEDIUM"

    snippet = normalized.get("targetSnippet", "")
    start = normalized.get("start")
    end = normalized.get("end")
    indices_ok = (
        _is_number(start)
        and _is_number(end)
        and 0 <= start <= end <= len(clean_text)
        and clean_text[start:end] == snippet
    )
    if not indices_ok:
        idx = nearest_occurrence(clean_text, snippet, start)
        if idx is None:
            return None
        normalized["start"] = idx
        normalized["end"] = idx + len(snippet)

    return normalized


# --------------------------------------------------------------------------
# Validace výstupního schématu
# --------------------------------------------------------------------------

REQUIRED_DEBATE_KEYS = (
    "debateId", "title", "topic", "chamber", "term",
    "sessionNumber", "date", "description", "status", "messages",
)
REQUIRED_MESSAGE_KEYS = (
    "messageId", "speaker", "party", "role",
    "timestamp", "date", "cleanText", "hasAnomalies", "annotations",
)
REQUIRED_ANNOTATION_KEYS = (
    "start", "end", "targetSnippet", "type",
    "severity", "shortBadgeLabel", "explanation", "proof",
)
REQUIRED_PROOF_KEYS = ("pastQuote", "pastDate", "pastContext", "sourceUrl")


def validate_extracted_debate(json_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Ověří, že výstup odpovídá schématu enginu v2.

    Vrací (je_validní, seznam_chyb). Volitelná pole (mediaEvidence,
    adversarialCheck, confidenceScore) se kontrolují jen tehdy, jsou-li přítomna.
    """
    errors: List[str] = []

    for key in REQUIRED_DEBATE_KEYS:
        if key not in json_data:
            errors.append("chybí klíč rozpravy: {}".format(key))
    if errors:
        return False, errors

    messages = json_data.get("messages")
    if not isinstance(messages, list):
        return False, ["klíč messages není seznam"]

    for msg in messages:
        if not isinstance(msg, dict):
            errors.append("položka v messages není objekt")
            continue
        where = "vystoupení {}".format(msg.get("messageId", "?"))
        for key in REQUIRED_MESSAGE_KEYS:
            if key not in msg:
                errors.append("{}: chybí klíč {}".format(where, key))

        if msg.get("speechAct") and msg["speechAct"] not in SPEECH_ACTS:
            errors.append("{}: neznámý speechAct {}".format(where, msg["speechAct"]))

        clean_text = msg.get("cleanText", "")
        annotations = msg.get("annotations")
        if not isinstance(annotations, list):
            errors.append("{}: annotations není seznam".format(where))
            continue
        for ann in annotations:
            if not isinstance(ann, dict):
                errors.append("{}: položka v annotations není objekt".format(where))
                continue
            errors.extend(_validate_annotation(ann, clean_text, where))

    return (len(errors) == 0), errors


def _validate_annotation(ann: Dict[str, Any], clean_text: str, where: str) -> List[str]:
    errors: List[str] = []
    label = "{} / anotace {}".format(where, ann.get("id", ann.get("shortBadgeLabel", "?")))

    for key in REQUIRED_ANNOTATION_KEYS:
        if key not in ann:
            errors.append("{}: chybí klíč {}".format(label, key))
    if errors:
        return errors

    if ann["type"] not in CANONICAL_TYPES:
        errors.append("{}: kategorie {} není kanonická (spusť normalize_annotation)".format(label, ann["type"]))
    if ann["severity"] not in SEVERITY_LEVELS:
        errors.append("{}: neznámá závažnost {}".format(label, ann["severity"]))

    start, end = ann["start"], ann["end"]
    if not (_is_number(start) and _is_number(end)) or not 0 <= start <= end <= len(clean_text):
        errors.append("{}: indexy {}-{} jsou mimo rozsah cleanText".format(label, start, end))
    elif clean_text[start:end] != ann["targetSnippet"]:
        errors.append("{}: indexy {}-{} neodpovídají targetSnippet".format(label, start, end))

    score = ann.get("confidenceScore")
    if score is not None:
        if not _is_number(score) or not 0.0 <= float(score) <= 1.0:
            errors.append("{}: confidenceScore mimo rozsah 0-1".format(label))
        elif float(score) < CONTEXT_THRESHOLD:
            errors.append("{}: confidenceScore {} pod prahem pro zveřejnění {}".format(label, score, CONTEXT_THRESHOLD))

    tier = ann.get("presentationTier")
    if tier is not None:
        if tier not in PRESENTATION_TIERS:
            errors.append("{}: neznámé presentationTier {}".format(label, tier))
        elif tier != get_presentation_tier(score):
            errors.append("{}: presentationTier {} neodpovídá confidenceScore {}".format(label, tier, score))

    if ann.get("nliRelation") and ann["nliRelation"] not in NLI_RELATIONS:
        errors.append("{}: neznámý nliRelation {}".format(label, ann["nliRelation"]))
    if ann.get("claimCategory") and ann["claimCategory"] not in CLAIM_CATEGORIES:
        errors.append("{}: neznámá claimCategory {}".format(label, ann["claimCategory"]))

    proof = ann.get("proof")
    if not isinstance(proof, dict):
        errors.append("{}: proof není objekt".format(label))
    else:
        for key in REQUIRED_PROOF_KEYS:
            if not proof.get(key):
                errors.append("{}: proof postrádá {}".format(label, key))
        if proof.get("voteRecorded") and proof["voteRecorded"] not in VOTE_VALUES:
            errors.append("{}: neznámá hodnota hlasování {}".format(label, proof["voteRecorded"]))

    media = ann.get("mediaEvidence")
    if media:
        seconds = media.get("exactTimestampSeconds")
        if not isinstance(seconds, int) or seconds < 0:
            errors.append("{}: exactTimestampSeconds musí být nezáporné celé číslo".format(label))
        if not media.get("archiveUrl"):
            errors.append("{}: chybí archiveUrl".format(label))

    adversarial = ann.get("adversarialCheck")
    if adversarial is not None and "passed" not in adversarial:
        errors.append("{}: adversarialCheck bez pole passed".format(label))

    return errors


if __name__ == "__main__":
    demo = {
        "debateId": "demo",
        "title": "Ukázková rozprava",
        "topic": "Ukázka validace",
        "chamber": "Poslanecká sněmovna Parlamentu ČR",
        "term": "9. volební období",
        "sessionNumber": 1,
        "date": "2025-11-20",
        "description": "Self-test validační vrstvy.",
        "status": "PROJEDNÁNO",
        "messages": [
            {
                "messageId": "msg_001",
                "speaker": "Ukázkový poslanec",
                "party": "Ukázkový klub",
                "role": "poslanec",
                "timestamp": "14:15",
                "date": "2025-11-20",
                "cleanText": "Daně nezvýšíme za žádných okolností.",
                "hasAnomalies": True,
                "annotations": [
                    {
                        "start": 0,
                        "end": 36,
                        "targetSnippet": "Daně nezvýšíme za žádných okolností.",
                        "type": "TIME_CONTRADICTION",
                        "severity": "HIGH",
                        "shortBadgeLabel": "Slib nezvyšování daní",
                        "explanation": "Tvrzení je v logickém rozporu s vystoupením ze dne 2024-03-14.",
                        "confidenceScore": 0.97,
                        "proof": {
                            "pastQuote": "Dřívější vystoupení k témuž bodu.",
                            "pastDate": "2024-03-14",
                            "pastContext": "Rozprava k témuž tisku",
                            "sourceUrl": "https://www.psp.cz/eknih/2021ps/stenprot/",
                        },
                    },
                    {
                        "start": 0,
                        "end": 4,
                        "targetSnippet": "Daně",
                        "type": "FACTUAL_ERROR",
                        "severity": "MEDIUM",
                        "shortBadgeLabel": "Nejisté srovnání",
                        "explanation": "Nad prahem pro zveřejnění, ale pod prahem pro obvinění — jen kontext.",
                        "confidenceScore": 0.85,
                        "proof": {
                            "pastQuote": "Podobné, ne totožné dřívější číslo.",
                            "pastDate": "2024-03-14",
                            "pastContext": "Rozprava k témuž tisku",
                            "sourceUrl": "https://www.psp.cz/eknih/2021ps/stenprot/",
                        },
                    },
                    {
                        "start": 0,
                        "end": 4,
                        "targetSnippet": "Daně",
                        "type": "FACTUAL_ERROR",
                        "severity": "LOW",
                        "shortBadgeLabel": "Slabý signál",
                        "explanation": "Pod prahem pro zveřejnění.",
                        "confidenceScore": 0.62,
                        "proof": {
                            "pastQuote": "Slabý signál bez doložitelného zdroje.",
                            "pastDate": "2024-03-14",
                            "pastContext": "Rozprava k témuž tisku",
                            "sourceUrl": "https://www.psp.cz/eknih/2021ps/stenprot/",
                        },
                    },
                ],
            }
        ],
    }

    message = demo["messages"][0]
    normalized = [normalize_annotation(a, message["cleanText"]) for a in message["annotations"]]
    usable = [a for a in normalized if a]
    published, context_development, dropped = apply_confidence_gate(usable)
    message["annotations"] = published + context_development
    message["hasAnomalies"] = bool(message["annotations"])

    ok, problems = validate_extracted_debate(demo)
    print("publikováno (PUBLISHED):", [a["type"] for a in published])
    print("kontext a vývoj stanoviska (CONTEXT_DEVELOPMENT):", [a["type"] for a in context_development])
    print("zahozeno pod prahem (DROPPED):", len(dropped))
    print("validní:", ok, problems)
