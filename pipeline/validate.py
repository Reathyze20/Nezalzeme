"""
Regresní kontrola ukázkové fixtury proti schématu enginu v2.

Nahrazuje dřívější skripty `fix_indices.py`, `verify_indices.py` a `verify_all.py`
v kořeni repozitáře. Ty držely vlastní kopii datasetu a musely se udržovat ručně;
tady se dataset načítá z jednoho místa a kontroluje celým řetězcem pipeline:

    normalize_annotation  ->  apply_confidence_gate  ->  validate_extracted_debate

Spuštění:  python pipeline/validate.py
"""

import json
import os
import sys

from detector import (
    CONTEXT_THRESHOLD,
    PUBLISH_THRESHOLD,
    apply_confidence_gate,
    normalize_annotation,
    validate_extracted_debate,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "data", "sample_debates.json")

# Fáze 0 pojistka: pokud analyzedMessageCount == messageCount ale počet
# anotací je pod tímhle podílem z celku, pipeline lže o stavu analýzy.
_ANALYZED_ANNOTATION_RATIO_MIN = 0.01  # alespoň 1 anotace na 100 vystoupení


def main() -> int:
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        debates = json.load(handle)

    problems = []
    published_total = 0
    context_total = 0
    dropped_total = 0

    for debate in debates:
        for message in debate["messages"]:
            clean_text = message["cleanText"]

            # Znakové indexy musí sedět ještě před normalizací — kontrola,
            # kterou dřív dělal verify_all.py.
            for ann in message["annotations"]:
                actual = clean_text[ann["start"]:ann["end"]]
                if actual != ann["targetSnippet"]:
                    problems.append(
                        "{}/{}: indexy {}-{} vracejí {!r}, očekáváno {!r}".format(
                            message["messageId"], ann.get("id", "?"),
                            ann["start"], ann["end"], actual, ann["targetSnippet"],
                        )
                    )

            normalized = [normalize_annotation(a, clean_text) for a in message["annotations"]]
            usable = [a for a in normalized if a]
            if len(usable) != len(message["annotations"]):
                problems.append(
                    "{}: {} anotací neprošlo normalizací".format(
                        message["messageId"], len(message["annotations"]) - len(usable)
                    )
                )

            published, context_development, dropped = apply_confidence_gate(usable)
            published_total += len(published)
            context_total += len(context_development)
            dropped_total += len(dropped)

            message["annotations"] = published + context_development
            message["hasAnomalies"] = bool(message["annotations"])

        ok, errors = validate_extracted_debate(debate)
        if not ok:
            problems.extend(errors)

    print("publikováno jako obvinění (PUBLISHED, >= {}): {} anotací".format(PUBLISH_THRESHOLD, published_total))
    print("kontext a vývoj stanoviska (CONTEXT_DEVELOPMENT, >= {}): {} anotací".format(CONTEXT_THRESHOLD, context_total))
    print("zahozeno pod prahem {} (DROPPED): {} anotací".format(CONTEXT_THRESHOLD, dropped_total))

    if problems:
        print("\nNALEZENÉ PROBLÉMY:")
        for problem in problems:
            print("  - {}".format(problem))
        return 1

    # Fáze 0 regresní pojistka: analyzedAt smí mít jen vystoupení se skutečným
    # nálezem. Pokud jsou analyzedAt == messageCount ale anotací je hrstka,
    # pipeline opět razítkuje bezpodmínečně.
    total_messages = sum(len(d["messages"]) for d in debates)
    analyzed_messages = sum(
        1 for d in debates for m in d["messages"] if m.get("analyzedAt")
    )
    annotation_count = sum(
        len(m.get("annotations", [])) for d in debates for m in d["messages"]
    )
    if (
        analyzed_messages == total_messages
        and total_messages > 0
        and annotation_count < total_messages * _ANALYZED_ANNOTATION_RATIO_MIN
    ):
        print(
            "\nREGRESE (Fáze 0): analyzedAt nastaveno pro všechna vystoupení ({}) "
            "ale anotací je jen {} — pipeline zřejmě opět razítkuje bezpodmínečně.".format(
                total_messages, annotation_count
            )
        )
        return 1

    print(
        "schéma i znakové indexy v pořádku "
        "(fixtura je výřez datasetu: {} rozprav, {} vystoupení)".format(
            len(debates), total_messages
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
