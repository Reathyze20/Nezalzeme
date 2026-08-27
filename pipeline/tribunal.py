"""
Adversariální tribunál (Fáze 4).

`ADVERSARIAL_PROMPT` v `detector.py` řešil obhajobu i verdikt jedním
promptem. Tribunál ho rozpadá na tři nezávisle volané role:

  - **Žalobce** staví obžalobu z kandidátní anomálie a doložených faktů
    (`pipeline/psp/facts.py`).
  - **Obhájce** dostane navíc legislativní kontext téhož dne (ostatní
    vystoupení stejné rozpravy kolem časové značky) a hledá věcný důvod,
    proč o rozpor nejde.
  - **Soudce** váží obojí a teprve on rozhoduje o finálním `passed`/
    `downgradeTo`/`dismiss` — ne Obhájce sám, jak tomu bylo ve Fázi 5.

Všechny tři role jdou přes jednoho providera (Anthropic) za společným
rozhraním `run_tribunal_role(role, payload)` — přechod na víc providerů
je pak jen změna konfigurace, ne přepis. Běží dávkově v pipeline a
zapéká se do `dataset.json` přes `export_web.py`; ne přes živou API
route, žádná v projektu není a živá inference by rozbila nákladový model
statického webu.

Výstup `run_tribunal()` je verdikt ve tvaru, který `detector.
apply_adversarial_verdict()` už umí zpracovat — tribunál jen doplňuje
`prosecutorCase`/`arbiterRationale`/`modelProvenance`.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detector import normalize_anomaly_type  # noqa: E402

TRIBUNAL_MODEL = "claude-sonnet-5"
TRIBUNAL_VERSION = "tribunal-v1"

# -------------------------------------------------------------------------- #
# Role 1: Žalobce
# -------------------------------------------------------------------------- #

PROSECUTOR_PROMPT = """# ROLE: ŽALOBCE (FÁZE 4)
Dostaneš kandidátní anomálii (podezření na rozpor) a doložené podklady:
aktuální výrok, historický výrok a případně fakta z hlasovací knihy
(`FACTS` — může být prázdné pole).

Tvým úkolem je sestavit **formální obžalobu** — nejsilnější věcný
argument, proč jde o skutečný rozpor. Nehodnoť obhajobu, tu nezvažuješ;
tvým jediným úkolem je postavit případ tak silně, jak to podklady dovolí.

Výstup je výhradně validní JSON:
{
  "case": "Věcný, neutrálně formulovaný popis rozporu — bez emočně zabarvených slov.",
  "keyEvidence": ["nejsilnější důkaz 1", "nejsilnější důkaz 2"]
}
"""


def build_prosecutor_payload(candidate: Dict[str, Any], facts: List[Dict[str, Any]]) -> str:
    payload = {
        "CANDIDATE_ANOMALY": {
            "type": candidate.get("type"),
            "explanation": candidate.get("explanation"),
            "targetSnippet": candidate.get("targetSnippet"),
            "proof": candidate.get("proof"),
        },
        "FACTS": facts,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_prosecutor_response(raw_json: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return {"case": "", "keyEvidence": []}
    if not isinstance(parsed, dict):
        return {"case": "", "keyEvidence": []}
    return {"case": str(parsed.get("case", "")), "keyEvidence": list(parsed.get("keyEvidence") or [])}


# -------------------------------------------------------------------------- #
# Role 2: Obhájce (Ďáblův advokát)
# -------------------------------------------------------------------------- #

DEFENSE_PROMPT = """# ROLE: OBHÁJCE / ĎÁBLŮV ADVOKÁT (FÁZE 4)
Dostaneš jednu kandidátní anomálii, její důkazy a `SAME_DAY_CONTEXT` —
ostatní vystoupení téže rozpravy kolem časové značky. Tvým jediným
úkolem je obhájit poslance.

1. Formuluj 3 nejsilnější obhajoby, proč nejde o rozpor. Zvaž zejména:
   - projednávalo se jiné znění tisku nebo jiný pozměňovací návrh,
   - mezi výroky se prokazatelně změnily makroekonomické či právní podmínky,
   - řečník reaguje na něco, co zaznělo ve `SAME_DAY_CONTEXT` (jiný
     řečník, procedurální bod, mimořádná událost dne),
   - řečník citoval nebo parafrázoval někoho jiného,
   - výrok byl míněn ironicky, jako hyperbola nebo metafora,
   - řečník vystupoval v jiné roli (ministr vs. opoziční poslanec) k jinému předmětu.
2. U každé obhajoby uveď, zda ji dodané podklady (včetně `SAME_DAY_CONTEXT`)
   skutečně potvrzují. Nevymýšlej si kontext, který v podkladech není.
3. Doporuč (rozhodnutí je na Soudci, ne na tobě):
   - `passed: true` – žádná obhajoba neobstála, rozpor by měl zůstat,
   - `passed: false` – obhajoba prokázala změnu kontextu; navrhni
     `downgradeTo` ("VALUE_SHIFT") nebo `dismiss: true`, pokud rozpor podle
     tebe neexistuje.
4. Uveď svůj odhad `confidenceScore` (0–1).

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


def build_same_day_context(
    message: Dict[str, Any], debate: Dict[str, Any], window_minutes: int = 60
) -> List[Dict[str, Any]]:
    """
    Ostatní vystoupení stejné rozpravy v okně kolem časové značky —
    podklad, na jehož základě může Obhájce hledat skutečnou reakci na
    jiného řečníka nebo na změnu bodu jednání, ne se ohlížet jen po
    samotném výroku.

    Bez rozpoznatelného času (`timestamp`) se vrátí prázdný kontext —
    lepší žádný kontext než domýšlený.
    """
    target_minutes = _clock_to_minutes(message.get("timestamp", ""))
    if target_minutes is None:
        return []

    context = []
    for other in debate.get("messages", []):
        if other.get("messageId") == message.get("messageId"):
            continue
        other_minutes = _clock_to_minutes(other.get("timestamp", ""))
        if other_minutes is None:
            continue
        if abs(other_minutes - target_minutes) <= window_minutes:
            context.append({
                "speaker": other.get("speaker"),
                "timestamp": other.get("timestamp"),
                "cleanText": (other.get("cleanText") or "")[:500],
            })
    return context


def _clock_to_minutes(clock: str) -> Optional[int]:
    try:
        hh, mm = str(clock).split(":")[:2]
        return int(hh) * 60 + int(mm)
    except (ValueError, AttributeError, IndexError):
        return None


def build_defense_payload(
    candidate: Dict[str, Any], same_day_context: List[Dict[str, Any]]
) -> str:
    payload = {
        "CANDIDATE_ANOMALY": candidate,
        "SAME_DAY_CONTEXT": same_day_context,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_defense_response(raw_json: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {
        "passed": parsed.get("passed", True),
        "defenseEvaluated": str(parsed.get("defenseEvaluated", "")),
        "defensesConsidered": list(parsed.get("defensesConsidered") or []),
        "downgradeTo": parsed.get("downgradeTo"),
        "dismiss": bool(parsed.get("dismiss", False)),
        "confidenceScore": parsed.get("confidenceScore"),
    }


# -------------------------------------------------------------------------- #
# Role 3: Soudce (Arbiter)
# -------------------------------------------------------------------------- #

ARBITER_PROMPT = """# ROLE: SOUDCE / ARBITR (FÁZE 4)
Dostaneš tři věci: kandidátní anomálii, obžalobu Žalobce (`PROSECUTOR_CASE`)
a doporučení Obhájce (`DEFENSE_RECOMMENDATION`). Obhájcovo doporučení NENÍ
závazné — je to jen jeden ze dvou hlasů, které vážíš.

1. Zvaž, jestli obhajoba skutečně prokazuje změnu kontextu, nebo jen
   formálně namítá, aniž by cokoliv doložila (formální obhajoba bez
   opory v podkladech obstát nemá).
2. Rozhodni finální verdikt:
   - `passed: true` – rozpor zůstává v původní kategorii,
   - `passed: false` s `downgradeTo: "VALUE_SHIFT"` – obhajoba prokázala
     legitimní posun kontextu,
   - `dismiss: true` – obhajoba prokázala, že o rozpor vůbec nejde.
3. `arbiterRationale` musí být tvoje VLASTNÍ zdůvodnění, proč jsi obžalobu
   a obhajobu takhle zvážil — ne přepis `defenseEvaluated`.
4. Uveď finální `confidenceScore` (0–1).

Výstup je výhradně validní JSON:
{
  "passed": true,
  "downgradeTo": null,
  "dismiss": false,
  "confidenceScore": 0.9,
  "arbiterRationale": "Vlastní zdůvodnění vážení obžaloby a obhajoby."
}
"""


def build_arbiter_payload(
    candidate: Dict[str, Any], prosecutor_case: Dict[str, Any], defense_verdict: Dict[str, Any]
) -> str:
    payload = {
        "CANDIDATE_ANOMALY": {
            "type": candidate.get("type"),
            "explanation": candidate.get("explanation"),
        },
        "PROSECUTOR_CASE": prosecutor_case,
        "DEFENSE_RECOMMENDATION": defense_verdict,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_arbiter_response(raw_json: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {
        "passed": parsed.get("passed", True),
        "downgradeTo": parsed.get("downgradeTo"),
        "dismiss": bool(parsed.get("dismiss", False)),
        "confidenceScore": parsed.get("confidenceScore"),
        "arbiterRationale": str(parsed.get("arbiterRationale", "")),
    }


# -------------------------------------------------------------------------- #
# Jediné místo, které skutečně volá LLM
# -------------------------------------------------------------------------- #

_SYSTEM_PROMPTS = {"PROSECUTOR": PROSECUTOR_PROMPT, "DEFENSE": DEFENSE_PROMPT, "ARBITER": ARBITER_PROMPT}


def run_tribunal_role(role: str, payload: str, model: str = TRIBUNAL_MODEL) -> str:
    """
    Volá LLM pro jednu roli tribunálu. `role` je "PROSECUTOR" | "DEFENSE" |
    "ARBITER" a vybírá systémový prompt. Jediné místo v modulu se skutečným
    síťovým voláním — zbytek (`build_*_payload`, `parse_*_response`) jsou
    čisté funkce testovatelné bez API klíče.
    """
    import anthropic

    if role not in _SYSTEM_PROMPTS:
        raise ValueError("neznámá role tribunálu: {}".format(role))

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPTS[role],
        messages=[{"role": "user", "content": payload}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


# -------------------------------------------------------------------------- #
# Korelovaná shoda: signál pro cross-provider
# -------------------------------------------------------------------------- #

def check_divergence(prosecutor_case: Dict[str, Any], defense_verdict: Dict[str, Any]) -> Optional[str]:
    """
    Varování, když Žalobce a Obhájce vycházejí podezřele konvergentně —
    typicky Obhájce, který nenamítá nic věcného, nebo texty obou rolí
    téměř totožné. Jeden LLM může za dvě "nezávislé" role jen předstírat
    hlas, který ve skutečnosti nekontroluje sám sebe; tohle je signál, že
    stojí za to zvážit cross-provider (rozhodnutí bylo ve schváleném
    plánu odloženo přesně na tenhle moment).
    """
    defenses = defense_verdict.get("defensesConsidered") or []
    if defense_verdict.get("passed") is True and len(defenses) < 2:
        return "Obhájce nenamítl žádnou reálnou obhajobu (méně než 2 zvážené obhajoby)."

    prosecutor_text = (prosecutor_case.get("case") or "").strip().lower()
    defense_text = (defense_verdict.get("defenseEvaluated") or "").strip().lower()
    if prosecutor_text and defense_text and prosecutor_text == defense_text:
        return "Žalobce a Obhájce vrátili identický text — podezřele konvergentní."

    return None


# -------------------------------------------------------------------------- #
# Sešití všech tří rolí
# -------------------------------------------------------------------------- #

def run_tribunal(
    candidate: Dict[str, Any],
    message: Dict[str, Any],
    debate: Dict[str, Any],
    facts: Optional[List[Dict[str, Any]]] = None,
    model: str = TRIBUNAL_MODEL,
) -> Dict[str, Any]:
    """
    Spustí všechny tři role a vrátí verdikt ve tvaru, který rovnou přijme
    `detector.apply_adversarial_verdict()`. Finální `passed`/`downgradeTo`/
    `dismiss`/`confidenceScore` je rozhodnutí Soudce, ne Obhájce.
    """
    same_day_context = build_same_day_context(message, debate)

    prosecutor_raw = run_tribunal_role("PROSECUTOR", build_prosecutor_payload(candidate, facts or []), model)
    prosecutor_case = parse_prosecutor_response(prosecutor_raw)

    defense_raw = run_tribunal_role("DEFENSE", build_defense_payload(candidate, same_day_context), model)
    defense_verdict = parse_defense_response(defense_raw)

    arbiter_raw = run_tribunal_role("ARBITER", build_arbiter_payload(candidate, prosecutor_case, defense_verdict), model)
    arbiter_verdict = parse_arbiter_response(arbiter_raw)

    divergence_warning = check_divergence(prosecutor_case, defense_verdict)

    return {
        "passed": arbiter_verdict["passed"],
        "downgradeTo": arbiter_verdict.get("downgradeTo"),
        "dismiss": arbiter_verdict.get("dismiss", False),
        "confidenceScore": arbiter_verdict.get("confidenceScore"),
        "defenseEvaluated": defense_verdict.get("defenseEvaluated", ""),
        "defensesConsidered": defense_verdict.get("defensesConsidered", []),
        "prosecutorCase": prosecutor_case.get("case", ""),
        "arbiterRationale": arbiter_verdict.get("arbiterRationale", ""),
        "modelProvenance": "{}:{}".format(TRIBUNAL_VERSION, model),
        "divergenceWarning": divergence_warning,
    }


if __name__ == "__main__":
    # Self-test bez sítě a bez API klíče: ověřuje jen skládání payloadů,
    # parsování a `check_divergence` (deterministická část modulu).
    # `run_tribunal_role` se tady záměrně nevolá — živé volání LLM
    # vyžaduje ANTHROPIC_API_KEY, který tenhle self-test nemá k dispozici.
    from detector import apply_adversarial_verdict

    candidate = {
        "type": "CONTRADICTION_TIME",
        "explanation": "Ukázkový kandidát rozporu.",
        "targetSnippet": "Nezvýšíme daně.",
        "confidenceScore": 0.9,
        "proof": {"pastQuote": "Zvážíme navýšení daní.", "pastDate": "2025-01-01",
                   "pastContext": "Ukázka", "sourceUrl": "https://example.test/"},
    }
    message = {"messageId": "m2", "timestamp": "14:20", "cleanText": "Nezvýšíme daně."}
    debate = {"messages": [
        message,
        {"messageId": "m1", "timestamp": "14:05", "speaker": "Jiný poslanec", "cleanText": "Předchozí bod pořadu skončil."},
        {"messageId": "m3", "timestamp": "16:00", "speaker": "Jiný poslanec", "cleanText": "Mimo okno, nemělo by se objevit."},
    ]}

    context = build_same_day_context(message, debate, window_minutes=60)
    print("same-day context ({} vystoupení):".format(len(context)))
    for c in context:
        print("  ", c["timestamp"], c["speaker"])
    assert len(context) == 1 and context[0]["speaker"] == "Jiný poslanec", "okno 60 min mělo najít jen m1, ne m3"

    prosecutor_case = parse_prosecutor_response(json.dumps({
        "case": "Výrok popírá dřívější ochotu daně zvýšit.", "keyEvidence": ["citace z 2025-01-01"],
    }))

    weak_defense = parse_defense_response(json.dumps({
        "passed": True, "defenseEvaluated": "Nic nenamítám.", "defensesConsidered": [], "confidenceScore": 0.9,
    }))
    print("check_divergence (slabá obhajoba):", check_divergence(prosecutor_case, weak_defense))
    assert check_divergence(prosecutor_case, weak_defense) is not None

    real_defense = parse_defense_response(json.dumps({
        "passed": False, "downgradeTo": "VALUE_SHIFT", "dismiss": False, "confidenceScore": 0.8,
        "defenseEvaluated": "Mezi výroky se změnil rozpočtový rámec.",
        "defensesConsidered": ["změna rámce", "jiný pozměňovací návrh", "reakce na SAME_DAY_CONTEXT"],
    }))
    print("check_divergence (reálná obhajoba):", check_divergence(prosecutor_case, real_defense))
    assert check_divergence(prosecutor_case, real_defense) is None

    arbiter_verdict = parse_arbiter_response(json.dumps({
        "passed": False, "downgradeTo": "VALUE_SHIFT", "dismiss": False, "confidenceScore": 0.82,
        "arbiterRationale": "Obhajoba doložila změnu rozpočtového rámce mezi oběma výroky.",
    }))

    tribunal_verdict = {
        "passed": arbiter_verdict["passed"], "downgradeTo": arbiter_verdict["downgradeTo"],
        "dismiss": arbiter_verdict["dismiss"], "confidenceScore": arbiter_verdict["confidenceScore"],
        "defenseEvaluated": real_defense["defenseEvaluated"], "defensesConsidered": real_defense["defensesConsidered"],
        "prosecutorCase": prosecutor_case["case"], "arbiterRationale": arbiter_verdict["arbiterRationale"],
        "modelProvenance": "{}:{}".format(TRIBUNAL_VERSION, "self-test"),
    }
    result = apply_adversarial_verdict(candidate, tribunal_verdict)
    print("\napply_adversarial_verdict výsledek:")
    print("  type:", result["type"], " severity:", result["severity"])
    print("  adversarialCheck:", json.dumps(result["adversarialCheck"], ensure_ascii=False, indent=2))
    assert result["type"] == "VALUE_SHIFT"
    assert result["adversarialCheck"]["prosecutorCase"] == prosecutor_case["case"]
    assert result["adversarialCheck"]["arbiterRationale"] == arbiter_verdict["arbiterRationale"]
    print("\nself-test OK")
