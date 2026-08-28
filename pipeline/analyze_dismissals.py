"""
Diagnostický nástroj pro triáž a analýzu zamítnutých případů v Tribunálu.

Prochází tabulku `verdicts` v `pipeline/data/engine.sqlite` a kategorizuje
důvody zamítnutí Obhájcem / Arbitrem:
  (a) Není rozpor / špatný kandidát (procedurální výrok, rolové konstatování vs. postoj)
  (b) Obhajoba přestřelila (potenciálně přehlédnutý rozpor)
  (c) Vadné tvrzení na vstupu (chyba extrakce)
"""

import json
import os
import sqlite3
from typing import Any, Dict, List, Tuple


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "engine.sqlite")


def classify_dismissal(
    ann: Dict[str, Any],
    claim_a: Dict[str, Any],
    claim_b: Dict[str, Any],
) -> Tuple[str, str]:
    """
    Roztřídí zamítnutí do diagnostické třídy a vrátí stručný důvod.
    """
    adv = ann.get("adversarialCheck", {})
    defense = (adv.get("defenseEvaluated") or "").lower()
    arbiter = (adv.get("arbiterRationale") or "").lower()
    full_text = f"{defense} {arbiter}"

    cat_a = claim_a.get("claim_category", "")
    cat_b = claim_b.get("claim_category", "")

    # 1. Procedurální řízení schůze / předsedající
    if any(kw in full_text for kw in ("procedurál", "předsedajíc", "řízení schůze", "udílení slova", "časový limit")):
        return "PROCEDURAL_CHAIR", "Procedurální formule / řízení schůze předsedajícím"

    # 2. Různá témata / nesouvisející věci
    if any(kw in full_text for kw in ("nesouvisí", "rozdílná témata", "jiné téma", "odlišný kontext", "dva různé")):
        return "TOPIC_MISMATCH", "Nesouvisející témata / odlišný věcný kontext"

    # 3. Rolové nebo identitní tvrzení vs politický postoj
    if any(kw in full_text for kw in ("funkce", "členství", "konstatování", "pouhý popis", "není postoj")):
        return "ROLE_VS_STANCE", "Rolový/popisný výrok postavený proti politickému postoji"

    # 4. Konzistentní obhajoba (stejný názor / žádný logický rozpor)
    if any(kw in full_text for kw in ("žádný rozpor", "neodporuje", "hájí stejný", "v souladu", "shodný")):
        return "CONSISTENT_STANCE", "Žádný logický rozpor — konzistentní argumentace"

    # 5. Potenciálně sporné / přísná obhajoba
    return "BORDERLINE_DEFENSE", "Hraniční posouzení / možný slabý posun postoje"


def main():
    if not os.path.exists(DB_PATH):
        print(f"Chyba: Databáze {DB_PATH} neexistuje.")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT v.verdict_id, v.message_id, v.annotation_json, v.presentation_tier, v.confidence_score,
               cp.similarity_score, n.contradiction, cp.claim_id_a, cp.claim_id_b
        FROM verdicts v
        LEFT JOIN candidate_pairs cp ON v.verdict_id = cp.pair_id
        LEFT JOIN nli_results n ON v.verdict_id = n.pair_id
        ORDER BY v.rowid ASC
    """).fetchall()

    if not rows:
        print("V tabulce verdicts nejsou žádné záznamy.")
        return 0

    print(f"=== Analýza verdiktů v engine.sqlite (celkem {len(rows)}) ===")

    tiers = {}
    classes = {}
    class_examples = {}

    for r in rows:
        tier = r["presentation_tier"]
        tiers[tier] = tiers.get(tier, 0) + 1

        ann = json.loads(r["annotation_json"])
        ca_row = conn.execute("SELECT claim_json FROM claims WHERE claim_id = ?", (r["claim_id_a"],)).fetchone()
        cb_row = conn.execute("SELECT claim_json FROM claims WHERE claim_id = ?", (r["claim_id_b"],)).fetchone()

        claim_a = json.loads(ca_row["claim_json"]) if ca_row else {}
        claim_b = json.loads(cb_row["claim_json"]) if cb_row else {}

        cls_key, cls_label = classify_dismissal(ann, claim_a, claim_b)
        classes[cls_key] = classes.get(cls_key, 0) + 1

        if cls_key not in class_examples:
            class_examples[cls_key] = {
                "label": cls_label,
                "verdict_id": r["verdict_id"],
                "similarity": r["similarity_score"],
                "contradiction": r["contradiction"],
                "quote_a": claim_a.get("extracted_claim", ""),
                "quote_b": claim_b.get("extracted_claim", ""),
                "defense": ann.get("adversarialCheck", {}).get("defenseEvaluated", ""),
                "arbiter": ann.get("adversarialCheck", {}).get("arbiterRationale", ""),
            }

    print("\n--- Rozdělení podle prezentačních pásem ---")
    for t, count in sorted(tiers.items(), key=lambda x: -x[1]):
        pct = (count / len(rows)) * 100
        print(f"  {t:20} : {count:4d} ({pct:5.1f} %)")

    print("\n--- Rozdělení důvodů zamítnutí v Tribunálu ---")
    for k, count in sorted(classes.items(), key=lambda x: -x[1]):
        pct = (count / len(rows)) * 100
        lbl = class_examples[k]["label"]
        print(f"  {k:20} : {count:4d} ({pct:5.1f} %) — {lbl}")

    print("\n--- Reprezentativní ukázky z jednotlivých tříd ---")
    for k, ex in class_examples.items():
        print(f"\n[Třída: {k} ({ex['label']})]")
        print(f"  Pár: {ex['verdict_id']} | Sim: {ex['similarity']} | Contradiction: {ex['contradiction']}")
        print(f"  Výrok A: {ex['quote_a'][:100]}...")
        print(f"  Výrok B: {ex['quote_b'][:100]}...")
        print(f"  Obhajoba: {ex['defense'][:140]}...")
        print(f"  Arbitr:   {ex['arbiter'][:140]}...")

    conn.close()
    return 0


if __name__ == "__main__":
    exit(main())
