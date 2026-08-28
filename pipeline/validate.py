"""
Regresní kontrola skutečného korpusu proti schématu enginu v2.

Přesměrováno z ukázkové fixtury na skutečný korpus (`pipeline/data/psp/*.json`),
aby pojistka mohla spadnout tam, kde na tom záleží — na skutečných datech.

    normalize_annotation  ->  apply_confidence_gate  ->  validate_extracted_debate

Spuštění:  python pipeline/validate.py
"""

import glob
import io
import json
import os
import sys

from detector import (
    CONTEXT_THRESHOLD,
    PUBLISH_THRESHOLD,
    VOTE_VALUES,
    apply_confidence_gate,
    normalize_annotation,
    validate_extracted_debate,
)

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(PIPELINE_DIR, "data", "psp")
FIXTURE_FALLBACK = os.path.join(PIPELINE_DIR, "data", "sample_debates.json")

# Fáze 0 pojistka: pokud analyzedMessageCount == messageCount ale počet
# anotací je pod tímhle podílem z celku, pipeline lže o stavu analýzy.
_ANALYZED_ANNOTATION_RATIO_MIN = 0.01  # alespoň 1 anotace na 100 vystoupení


def load_debates():
    """Načte skutečný korpus; padá-li zpět na fixturu, varuje."""
    corpus_files = sorted(glob.glob(os.path.join(CORPUS_DIR, "*.json")))
    debates = []

    if corpus_files:
        for fpath in corpus_files:
            with io.open(fpath, encoding="utf-8") as handle:
                debates.extend(json.load(handle))
        print("Načteno {} rozprav ze skutečného korpusu ({} souborů).".format(
            len(debates), len(corpus_files)))
    elif os.path.exists(FIXTURE_FALLBACK):
        print("VAROVÁNÍ: skutečný korpus nenalezen v {}, padám zpět na fixturu.".format(CORPUS_DIR))
        with io.open(FIXTURE_FALLBACK, encoding="utf-8") as handle:
            debates = json.load(handle)
    else:
        print("CHYBA: žádná data v {} ani {}.".format(CORPUS_DIR, FIXTURE_FALLBACK))

    return debates


def main() -> int:
    debates = load_debates()
    if not debates:
        return 1

    problems = []
    published_total = 0
    context_total = 0
    dropped_total = 0

    for debate in debates:
        for message in debate["messages"]:
            clean_text = message["cleanText"]

            # Znakové indexy musí sedět ještě před normalizací
            for ann in message.get("annotations", []):
                actual = clean_text[ann["start"]:ann["end"]]
                if actual != ann["targetSnippet"]:
                    problems.append(
                        "{}/{}: indexy {}-{} vracejí {!r}, očekáváno {!r}".format(
                            message["messageId"], ann.get("id", "?"),
                            ann["start"], ann["end"], actual, ann["targetSnippet"],
                        )
                    )

            # Kontrola source.ballots — voteOfSpeaker musí být platná hodnota
            ballots = (message.get("source") or {}).get("ballots", [])
            for ballot in ballots:
                vote = ballot.get("voteOfSpeaker")
                if vote is not None and vote not in VOTE_VALUES:
                    problems.append(
                        "{}: neplatná voteOfSpeaker {!r} v ballot {}".format(
                            message["messageId"], vote, ballot.get("ballotId", "?"),
                        )
                    )

            # Normalizace a confidence gate (pokud jsou anotace)
            annotations = message.get("annotations", [])
            if annotations:
                normalized = [normalize_annotation(a, clean_text) for a in annotations]
                usable = [a for a in normalized if a]
                if len(usable) != len(annotations):
                    problems.append(
                        "{}: {} anotací neprošlo normalizací".format(
                            message["messageId"], len(annotations) - len(usable)
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
        for problem in problems[:20]:
            print("  - {}".format(problem))
        if len(problems) > 20:
            print("  ... a dalších {}".format(len(problems) - 20))
        return 1

    # Fáze 0 regresní pojistka
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
        "({} rozprav, {} vystoupení)".format(len(debates), total_messages)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
