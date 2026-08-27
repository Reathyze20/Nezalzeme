"""
Generátor ukázkové fixtury `pipeline/data/sample_debates.json`.

Fixtura zrcadlí `src/data/debatesData.ts` ve tvaru, jaký produkuje pipeline,
a slouží k regresnímu ověření schématu (`pipeline/validate.py`). Znakové indexy
se dopočítávají zde, ne ručně — stejná pojistka jako `znacka()` na straně TS.

UKÁZKOVÁ DATA: jména, kluby i citace jsou smyšlené.
"""

import json
import os
from typing import Any, Dict, List

EKNIH = "https://www.psp.cz/eknih/2021ps/stenprot"

ROZ_01 = (
    "Předkládám návrh, který srovná rozpočtová pravidla napříč kapitolami. "
    "Nezvyšujeme celkovou daňovou zátěž, jen zpřesňujeme, kdo za co odpovídá."
)

ROZ_06 = (
    "Dnes jsem přesvědčená, že jednotná sazba DPH je pro rodiny výhodnější "
    "než dosavadní dvě sazby."
)

ROZ_07 = (
    "Na dotaz kolegyně Marešové: podle propočtu výboru jde o 43 obcí, seznam je "
    "přílohou usnesení číslo 118. Rozešlu ho všem klubům do konce dnešního jednání."
)


def znacka(clean_text: str, snippet: str, **rest: Any) -> Dict[str, Any]:
    """Sestaví anotaci a dopočte znakové indexy; chybný úryvek shodí generátor."""
    start = clean_text.find(snippet)
    if start == -1:
        raise ValueError("Značka nenalezena v textu vystoupení: {!r}".format(snippet))
    rest["start"] = start
    rest["end"] = start + len(snippet)
    rest["targetSnippet"] = snippet
    return rest


def build() -> List[Dict[str, Any]]:
    return [
        {
            "debateId": "psp-9-schuze-84-2024-rozpoctova-pravidla",
            "title": "Návrh zákona o úpravě rozpočtových pravidel",
            "topic": "Sněmovní tisk 488 · úprava pravidel hospodaření kapitol státního rozpočtu",
            "chamber": "Poslanecká sněmovna Parlamentu ČR",
            "term": "9. volební období",
            "sessionNumber": 84,
            "date": "2024-06-12",
            "tiskNumber": "ST 488",
            "status": "SCHVÁLENO",
            "description": "Druhé čtení návrhu, který upravuje rozpočtová pravidla napříč kapitolami.",
            "messages": [
                {
                    "messageId": "roz-01",
                    "speaker": "Jiří Vrána",
                    "party": "SDL",
                    "role": "ministr financí",
                    "timestamp": "14:15",
                    "date": "2024-06-12",
                    "cleanText": ROZ_01,
                    "speechAct": "OWN_STANCE",
                    "hasAnomalies": True,
                    "annotations": [
                        znacka(
                            ROZ_01,
                            "Nezvyšujeme celkovou daňovou zátěž",
                            id="roz-01-a1",
                            type="VOTE_MISMATCH",
                            severity="CRITICAL",
                            shortBadgeLabel="Rozpor s hlasováním",
                            explanation=(
                                "Řečník hlasoval pro tisk se zvýšením sazby DPPO ve stejný den, "
                                "kdy pronesl tento výrok."
                            ),
                            confidenceScore=0.96,
                            nliRelation="CONTRADICTION",
                            claimCategory="STANCE_COMMITMENT",
                            adversarialCheck={
                                "passed": True,
                                "defenseEvaluated": (
                                    "Zkoumáno, zda hlasoval o pozměněném znění bez daňové části; "
                                    "tisk 488 obsahoval zvýšení sazby i ve schváleném znění."
                                ),
                                "defensesConsidered": [
                                    "Hlasovalo se o jiném znění tisku, než ke kterému se výrok vztahoval.",
                                    "Zvýšení sazby DPPO nezvyšuje celkovou zátěž, protože jinde klesá.",
                                    "Výrok mířil na domácnosti, nikoli na právnické osoby.",
                                ],
                            },
                            proof={
                                "pastQuote": (
                                    "Hlasování č. 204 k tisku 488, 12. 6. 2024: Vrána J. — PRO. "
                                    "Tisk zvyšuje sazbu daně z příjmu právnických osob z 19 % na 21 %."
                                ),
                                "pastDate": "2024-06-12",
                                "pastContext": "Hlasování Poslanecké sněmovny o tisku 488",
                                "sourceUrl": "{}/084schuz/hl204.htm".format(EKNIH),
                                "voteRecorded": "PRO",
                                "votingBallotId": "Hlasování č. 204, 84. schůze (12. 6. 2024)",
                            },
                        )
                    ],
                },
                {
                    "messageId": "roz-06",
                    "speaker": "Alena Kovářová",
                    "party": "ODU",
                    "role": "místopředsedkyně vlády",
                    "timestamp": "14:47",
                    "date": "2024-06-12",
                    "cleanText": ROZ_06,
                    "speechAct": "OWN_STANCE",
                    "hasAnomalies": True,
                    "annotations": [
                        znacka(
                            ROZ_06,
                            "jednotná sazba DPH je pro rodiny výhodnější",
                            id="roz-06-a1",
                            type="VALUE_SHIFT",
                            severity="LOW",
                            shortBadgeLabel="Změna postoje",
                            explanation=(
                                "Oponentní přezkum uznal změnu výchozích podmínek, kategorie byla "
                                "zmírněna z časového rozporu na názorový posun."
                            ),
                            confidenceScore=0.84,
                            nliRelation="NEUTRAL",
                            claimCategory="STANCE_COMMITMENT",
                            adversarialCheck={
                                "passed": False,
                                "downgradedFrom": "CONTRADICTION_TIME",
                                "defenseEvaluated": (
                                    "Obhajoba obstála: mezi výroky vstoupila v účinnost novela "
                                    "sjednocující sníženou sazbu."
                                ),
                                "defensesConsidered": [
                                    "Mezi výroky se změnila právní úprava sazeb DPH.",
                                    "Řečnice změnu postoje výslovně uvádí slovem „dnes“.",
                                    "Dřívější výrok se týkal jiného rozsahu zboží ve snížené sazbě.",
                                ],
                            },
                            proof={
                                "pastQuote": (
                                    "Dvě sazby DPH chrání základní potraviny. Sjednocení by dopadlo "
                                    "na ty nejchudší."
                                ),
                                "pastDate": "2022-03-09",
                                "pastContext": "Rozprava k novele zákona o DPH, 61. schůze",
                                "sourceUrl": "{}/061schuz/s061077.htm".format(EKNIH),
                            },
                        )
                    ],
                },
                {
                    "messageId": "roz-07",
                    "speaker": "Věra Nedvědová",
                    "party": "SDL",
                    "role": "předsedkyně rozpočtového výboru",
                    "timestamp": "14:51",
                    "date": "2024-06-12",
                    "cleanText": ROZ_07,
                    "speechAct": "OWN_STANCE",
                    # Kandidát pod prahem 0,80 — publikační brána ho musí zahodit.
                    "hasAnomalies": True,
                    "annotations": [
                        znacka(
                            ROZ_07,
                            "podle propočtu výboru jde o 43 obcí",
                            id="roz-07-a1",
                            type="FACTUAL_ERROR",  # alias z promptu, normalizuje se
                            severity="LOW",
                            shortBadgeLabel="Neověřený počet obcí",
                            explanation=(
                                "Usnesení č. 118 nebylo v době analýzy zveřejněno, číslo tedy nelze "
                                "proti zdroji ověřit ani vyvrátit."
                            ),
                            confidenceScore=0.62,
                            nliRelation="NEUTRAL",
                            claimCategory="FACTUAL_CLAIM",
                            proof={
                                "pastQuote": "Usnesení rozpočtového výboru č. 118 nebylo k datu analýzy publikováno.",
                                "pastDate": "2024-06-12",
                                "pastContext": "Rejstřík usnesení rozpočtového výboru",
                                "sourceUrl": "{}/084schuz/s084043.htm".format(EKNIH),
                            },
                        )
                    ],
                },
            ],
        }
    ]


if __name__ == "__main__":
    target = os.path.join(os.path.dirname(__file__), "data", "sample_debates.json")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(build(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("zapsáno: {}".format(target))
