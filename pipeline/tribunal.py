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

# Makroekonomický kontext (ČSÚ + ČNB) — lazy import, aby modul šel importovat
# i bez sítě (testy, offline prostředí).
try:
    from macro_context import format_for_defense, get_macro_context  # noqa: E402
    _MACRO_AVAILABLE = True
except ImportError:
    _MACRO_AVAILABLE = False
    def format_for_defense(macro):  # type: ignore
        return ""
    def get_macro_context(month, **kw):  # type: ignore
        return {}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import dotenv
    _root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _env_file = os.path.join(_root_dir, ".env")
    if os.path.exists(_env_file):
        dotenv.load_dotenv(_env_file)
    else:
        dotenv.load_dotenv()
except Exception:
    pass

from model_backend import clean_json_markdown  # noqa: E402
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
    cleaned = clean_json_markdown(raw_json)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"case": "", "keyEvidence": []}
    if not isinstance(parsed, dict):
        return {"case": "", "keyEvidence": []}
    return {"case": str(parsed.get("case", "")), "keyEvidence": list(parsed.get("keyEvidence") or [])}


# -------------------------------------------------------------------------- #
# Role 2: Obhájce (Ďáblův advokát)
# -------------------------------------------------------------------------- #

DEFENSE_PROMPT = """# ROLE: OBHÁJCE / ĎÁBLŮV ADVOKÁT (FÁZE 4)
Dostaneš jednu kandidátní anomálii, její důkazy, `SAME_DAY_CONTEXT` (ostatní
vystoupení téže rozpravy kolem časové značky), volitelně `MACRO_CONTEXT`
(ověřené makroekonomické ukazatele z doby výroků — ČSÚ, ČNB) a volitelně
`ROLE_CONTEXT` (politická role řečníka v době výroků — člen vlády vs. opozice).
Tvým jediným úkolem je obhájit poslance.

1. Formuluj 3 nejsilnější obhajoby, proč nejde o rozpor. Zvaž zejména:
   - projednávalo se jiné znění tisku nebo jiný pozměňovací návrh,
   - mezi výroky se prokazatelně změnily makroekonomické či právní podmínky
     (pokud `MACRO_CONTEXT` toto objektivně potvrzuje — např. prudký skok
     inflace, hospodářská recese, změna základní sazby ČNB),
   - řečník reaguje na něco, co zaznělo ve `SAME_DAY_CONTEXT` (jiný
     řečník, procedurální bod, mimořádná událost dne),
   - řečník citoval nebo parafrázoval někoho jiného,
   - výrok byl míněn ironicky, jako hyperbola nebo metafora,
   - řečník vystupoval v jiné roli (pokud `ROLE_CONTEXT` indikuje posun mezi
     vládou a opozicí — např. ministr hájící vládní kompromis vs. dřívější
     osobní opoziční postoj).
2. U každé obhajoby uveď, zda ji dodané podklady (včetně `SAME_DAY_CONTEXT`,
   `MACRO_CONTEXT` a `ROLE_CONTEXT`) skutečně potvrzují. Nevymýšlej si kontext,
   který v podkladech není. Pokud `MACRO_CONTEXT` tvrzení o "ekonomické krizi" nebo
   "změně reality" NEVYVRACÍ ani NEPOTVRZUJE, přiznej tuto mezeru výslovně.
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
    candidate: Dict[str, Any],
    same_day_context: List[Dict[str, Any]],
    macro_context: Optional[Dict[str, Any]] = None,
    role_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Sestaví payload pro Obhájce.

    `macro_context` je slovník z `macro_context.get_macro_context()` pro měsíc
    aktuálního výroku a srovnávací měsíc. Pokud je None nebo prázdný, klíč
    MACRO_CONTEXT se do payloadu nepřidá.

    `role_context` nese informace o politické roli mluvčího k datu obou výroků
    (např. ministr vs. opoziční poslanec po volbách / výměně vlády).
    """
    payload: Dict[str, Any] = {
        "CANDIDATE_ANOMALY": candidate,
        "SAME_DAY_CONTEXT": same_day_context,
    }
    if macro_context and macro_context.get("data_sources"):
        formatted = format_for_defense(macro_context)
        if formatted:
            payload["MACRO_CONTEXT"] = formatted
    if role_context:
        payload["ROLE_CONTEXT"] = role_context
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_defense_response(raw_json: str) -> Dict[str, Any]:
    cleaned = clean_json_markdown(raw_json)
    try:
        parsed = json.loads(cleaned)
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
Dostaneš kandidátní anomálii (včetně doslovných citací `targetSnippet` a `proof`),
obžalobu Žalobce (`PROSECUTOR_CASE`) a doporučení Obhájce (`DEFENSE_RECOMMENDATION`).

Tvým úkolem je nestranně a věcně posoudit, zda jde o:
A) ZÁVAŽNÝ ROZPOR (`passed: true`),
B) DOLOŽENOU ZMĚNU POSTOJE / VÝVOJ V ČASE (`passed: false` s `downgradeTo: "VALUE_SHIFT"`),
C) FALEŠNÝ NÁLEZ / PROCEDURÁLNÍ ŠUM (`dismiss: true`).

PRAVIDLA PRO ROZHODNUTÍ:
1. `passed: true` (ZÁVAŽNÝ ROZPOR):
   - Použij, pokud řečník prokazatelně a přímo popírá své dřívější jednoznačné tvrzení,
     závazek či postoj bez objektivní změny reality (např. slib "daně nezvýšíme" vs.
     "zvyšujeme daně", popření dřívějšího vyjádření, tvrzení o opaku téhož faktu).
   - Formální politické výmluvy ("to bylo v opozici", "dnes je jiná situace") NESTAČÍ
     na smazání rozporu.

2. `passed: false` s `downgradeTo: "VALUE_SHIFT"` (DOLOŽENÁ ZMĚNA POSTOJE):
   - Použij VŽDY, pokud politik v čase změnil svůj věcný postoj, názor či prioritu,
     ale obhajoba doložila legitimní důvody posunu (např. koaliční kompromis,
     převzetí vládní odpovědnosti, reakce na vnější ekonomický vývoj, inflaci, válku).
   - TOTO JE JÁDRO PLATFORMY: Změna postoje v čase NENÍ lež, ale doložený fakt,
     který má veřejnost vidět spolu s vyhodnocením obhajoby!
   - Tyto případy NEZAMÍTEJ jako `dismiss: true`! Pokud došlo k názorovému posunu,
     patří do `downgradeTo: "VALUE_SHIFT"`. Nastav odpovídající `confidenceScore` (0.80–0.94).

3. `dismiss: true` (FALEŠNÝ NÁLEZ / PROCEDURÁLNÍ ŠUM):
   - Použij POUZE tehdy, pokud o žádný rozpor ani změnu postoje vůbec nejde:
     * Porovnání dvou různých hlasování či schůzí (např. hlasování č. 2 vs. č. 45),
     * Situační procedurální fráze, oslovení ("nepřítomný premiér"), omluvy za limit řeči,
     * Výrok a proti-výrok popisují dvě úplně nesouvisející věci nebo odlišné osoby,
     * Výrok byl v kontextu jednoznačně ironií, hyperbolou nebo citací oponenta.

Výstup je výhradně validní JSON:
{
  "passed": false,
  "downgradeTo": "VALUE_SHIFT",
  "dismiss": false,
  "confidenceScore": 0.88,
  "arbiterRationale": "Vlastní věcné zdůvodnění vážení obžaloby a obhajoby."
}
"""


def build_arbiter_payload(
    candidate: Dict[str, Any], prosecutor_case: Dict[str, Any], defense_verdict: Dict[str, Any]
) -> str:
    payload = {
        "CANDIDATE_ANOMALY": {
            "type": candidate.get("type"),
            "explanation": candidate.get("explanation"),
            "targetSnippet": candidate.get("targetSnippet"),
            "proof": candidate.get("proof"),
        },
        "PROSECUTOR_CASE": prosecutor_case,
        "DEFENSE_RECOMMENDATION": defense_verdict,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_arbiter_response(raw_json: str) -> Dict[str, Any]:
    cleaned = clean_json_markdown(raw_json)
    try:
        parsed = json.loads(cleaned)
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
    "ARBITER" a vybírá systémový prompt. Automaticky použije Gemini nebo Anthropic
    podle přítomných klíčů.
    """
    if role not in _SYSTEM_PROMPTS:
        raise ValueError("neznámá role tribunálu: {}".format(role))

    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if gemini_key:
        from google import genai
        from google.genai import types

        gemini_model = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
        client = genai.Client(api_key=gemini_key)
        thinking_cfg = None
        try:
            thinking_cfg = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            thinking_cfg = None

        response = client.models.generate_content(
            model=gemini_model,
            contents=payload,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPTS[role],
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=2048,
                thinking_config=thinking_cfg,
            ),
        )
        return clean_json_markdown(response.text or "")

    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPTS[role],
        messages=[{"role": "user", "content": payload}],
    )
    return clean_json_markdown(
        "".join(block.text for block in response.content if block.type == "text")
    )


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
