"""
Orchestrátor pipeline Nezalžeme.cz — jediný vstupní bod.

Pořadí fází pro každé substantivní vystoupení (cleanText >= 200 znaků):

    scrape  →  claims  →  retrieval  →  nli  →  tribunal  →  verify_proof
                                                              ↓
                                                        engine.sqlite
                                                              ↓
                                                       export_web.py

Přepínače:
    --schuze N      Zpracuje pouze schůzi číslo N (lze kombinovat s --faze).
    --faze JMENO    Spustí pouze jednu fázi: claims | retrieval | nli |
                    tribunal | verify | export.  Výchozí: vse.
    --pokracovat    Přeskočí vystoupení a páry, které jsou v engine.sqlite.
    --backend api   Volá Anthropic API (výchozí).
    --backend jsonl Nulové náklady — front zapíše do llm_queue.jsonl.

Příklady:
    python pipeline/run_pipeline.py --schuze 10 --faze vse
    python pipeline/run_pipeline.py --backend jsonl --pokracovat
    python pipeline/run_pipeline.py --faze export
"""

import argparse
import glob
import io
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claims import (  # noqa: E402
    CLAIM_EXTRACTION_MODEL,
    CLAIM_EXTRACTION_PROMPT,
    build_claim_extraction_prompt,
    parse_claims_response,
)
from db import (  # noqa: E402
    analyzed_message_ids,
    load_claims_for_speaker,
    mark_verdict_verified,
    message_already_processed,
    open_engine_db,
    pair_already_nli,
    store_candidate_pair,
    store_claims,
    store_nli_result,
    store_verdict,
)
from detector import (  # noqa: E402
    apply_adversarial_verdict,
    apply_confidence_gate,
    get_presentation_tier,
    normalize_annotation,
)
from model_backend import ApiBackend, JsonlBackend, PendingCallsError, _PendingCall  # noqa: E402
from tribunal import (  # noqa: E402
    ARBITER_PROMPT,
    DEFENSE_PROMPT,
    PROSECUTOR_PROMPT,
    TRIBUNAL_MODEL,
    build_arbiter_payload,
    build_defense_payload,
    build_prosecutor_payload,
    build_same_day_context,
    parse_arbiter_response,
    parse_defense_response,
    parse_prosecutor_response,
)
from verify_proof import verify_annotation  # noqa: E402
from psp.client import PspClient  # noqa: E402

ENGINE_VERSION = "run-pipeline-v1"
MIN_SUBSTANTIVE_CHARS = 200   # vystoupení kratší než toto se přeskočí
NLI_CONTRADICTION_THRESHOLD = 0.40   # minimum pro předání tribunálu
TOP_K_RETRIEVAL = 5           # kolik kandidátů retrieval vrátí na jeden Claim

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PIPELINE_DIR, "data", "psp")


# ---------------------------------------------------------------------------
# Načtení korpusu
# ---------------------------------------------------------------------------

def load_corpus(schuze: Optional[int] = None) -> List[Tuple[Dict, Dict]]:
    """
    Vrátí list dvojic (debate, message) pro všechna substantivní vystoupení.

    Pokud je zadán `schuze`, filtruje na danou schůzi. Procedurální
    vystoupení (cleanText < MIN_SUBSTANTIVE_CHARS) se přeskakují — jsou to
    pozdravy a řízení schůze, nikoli věcné výroky.
    """
    pairs = []
    pattern = os.path.join(DATA_DIR, "*.json")
    for fpath in sorted(glob.glob(pattern)):
        with io.open(fpath, encoding="utf-8") as handle:
            debates = json.load(handle)
        for debate in debates:
            if schuze is not None and debate.get("sessionNumber") != schuze:
                continue
            for msg in debate.get("messages", []):
                clean = msg.get("cleanText", "")
                if len(clean) < MIN_SUBSTANTIVE_CHARS:
                    continue
                pairs.append((debate, msg))
    return pairs


# ---------------------------------------------------------------------------
# Fáze 2b: extrakce tvrzení
# ---------------------------------------------------------------------------

def phase_claims(pairs, conn, backend, pokracovat: bool) -> int:
    total = done = skipped = 0
    for debate, msg in pairs:
        total += 1
        mid = msg["messageId"]
        if pokracovat and message_already_processed(conn, mid):
            skipped += 1
            continue
        try:
            payload = build_claim_extraction_prompt(msg)
            raw = backend.call(
                "CLAIMS", CLAIM_EXTRACTION_PROMPT, payload, CLAIM_EXTRACTION_MODEL
            )
        except _PendingCall:
            continue
        claims = parse_claims_response(raw, msg)
        speaker_id = (msg.get("source") or {}).get("idOsoba", "")
        store_claims(conn, mid, speaker_id, claims, CLAIM_EXTRACTION_MODEL)
        done += 1
        print("  [claims] {} → {} tvrzení".format(mid, len(claims)))
    print("claims: {}/{} zpracováno, {} přeskočeno".format(done, total, skipped))
    return done


# ---------------------------------------------------------------------------
# Fáze 3a: bi-encoder retrieval
# ---------------------------------------------------------------------------

def phase_retrieval(pairs, conn) -> int:
    """
    Pro každé tvrzení najde top-K kandidátů ze stejného řečníka.
    Retrieval je lokální (sentence-transformers) — žádné LLM volání.
    """
    try:
        from retrieval import BiEncoder, retrieve_candidates
    except ImportError:
        print("[retrieval] sentence-transformers není nainstalováno, fáze přeskočena.")
        return 0

    encoder = BiEncoder()
    speaker_ids = {
        (msg.get("source") or {}).get("idOsoba", "")
        for _, msg in pairs
        if (msg.get("source") or {}).get("idOsoba")
    }

    pair_count = 0
    for speaker_id in sorted(speaker_ids):
        claims = load_claims_for_speaker(conn, speaker_id)
        if len(claims) < 2:
            continue
        candidates = retrieve_candidates(claims, claims, encoder, top_k=TOP_K_RETRIEVAL)
        for pair in candidates:
            store_candidate_pair(
                conn,
                pair.claim_id + "::" + pair.candidate_claim_id,
                pair.claim_id,
                pair.candidate_claim_id,
                pair.bi_encoder_score,
            )
            pair_count += 1
    print("retrieval: {} kandidátních párů".format(pair_count))
    return pair_count


# ---------------------------------------------------------------------------
# Fáze 3b: NLI
# ---------------------------------------------------------------------------

def phase_nli(conn) -> int:
    """Cross-encoder NLI na kandidátních párech — lokální model, bez LLM."""
    try:
        from nli import CrossEncoderNli
        from retrieval import claim_text
    except ImportError:
        print("[nli] transformers není nainstalováno, fáze přeskočena.")
        return 0

    rows = conn.execute(
        "SELECT pair_id, claim_id_a, claim_id_b FROM candidate_pairs"
    ).fetchall()
    if not rows:
        print("nli: žádné páry ke zpracování")
        return 0

    nli_model = CrossEncoderNli()
    done = 0
    for row in rows:
        pid = row["pair_id"]
        if pair_already_nli(conn, pid):
            continue
        row_a = conn.execute(
            "SELECT claim_json FROM claims WHERE claim_id = ?", (row["claim_id_a"],)
        ).fetchone()
        row_b = conn.execute(
            "SELECT claim_json FROM claims WHERE claim_id = ?", (row["claim_id_b"],)
        ).fetchone()
        if not row_a or not row_b:
            continue
        claim_a = json.loads(row_a["claim_json"])
        claim_b = json.loads(row_b["claim_json"])
        result = nli_model.classify(claim_text(claim_a), claim_text(claim_b))
        store_nli_result(conn, pid, result["scores"], result["nliRelation"])
        done += 1

    print("nli: {} párů ohodnoceno".format(done))
    return done


# ---------------------------------------------------------------------------
# Fáze 4: tribunál
# ---------------------------------------------------------------------------

def _build_candidate_annotation(claim_a, claim_b, nli_result) -> Dict[str, Any]:
    """Sestaví hrubý kandidát ve tvaru, který tribunál dostane jako vstup."""
    return {
        "type": "CONTRADICTION_TIME",
        "severity": "MEDIUM",
        "shortBadgeLabel": "{} vs {}".format(
            claim_a.get("rawSpan", "")[:40], claim_b.get("rawSpan", "")[:40]
        ),
        "explanation": (
            "Potenciální rozpor: [{subject}] {predicate} [{object}] "
            "({timeFrame}) vs starší tvrzení téhož řečníka."
        ).format(**claim_a),
        "targetSnippet": claim_a.get("rawSpan", ""),
        "start": claim_a.get("sourceCharStart", 0),
        "end": claim_a.get("sourceCharEnd", 0),
        "confidenceScore": float(nli_result.get("contradiction", 0.5)),
        "nliRelation": "CONTRADICTION",
        "claimCategory": claim_a.get("claimCategory", "FACTUAL_CLAIM"),
        "proof": {
            "pastQuote": claim_b.get("rawSpan", ""),
            "pastDate": claim_b.get("timeFrame", "NEURČENO"),
            "pastContext": "Dřívější vystoupení téhož řečníka",
            "sourceUrl": "",
        },
        "producedBy": "engine",
        "engineVersion": ENGINE_VERSION,
    }


def phase_tribunal(pairs, conn, backend, pokracovat: bool) -> int:
    """
    Spustí tribunál (Žalobce → Obhájce → Soudce) pro páry
    s NLI CONTRADICTION skóre >= NLI_CONTRADICTION_THRESHOLD.
    """
    debate_map = {msg["messageId"]: debate for debate, msg in pairs}
    msg_map = {msg["messageId"]: msg for _, msg in pairs}

    rows = conn.execute(
        "SELECT n.pair_id, n.contradiction, n.nli_relation, "
        "       p.claim_id_a, p.claim_id_b "
        "FROM nli_results n JOIN candidate_pairs p ON n.pair_id = p.pair_id "
        "WHERE n.contradiction >= ? AND n.nli_relation = 'CONTRADICTION'",
        (NLI_CONTRADICTION_THRESHOLD,),
    ).fetchall()

    if not rows:
        print("tribunal: žádné páry s dostatečným CONTRADICTION skóre")
        return 0

    done = 0
    for row in rows:
        pid = row["pair_id"]
        # Přeskočit, pokud verdikt pro tento pár již existuje
        if pokracovat and conn.execute(
            "SELECT 1 FROM verdicts WHERE verdict_id = ?", (pid,)
        ).fetchone():
            continue

        row_a = conn.execute(
            "SELECT claim_json, message_id FROM claims WHERE claim_id = ?",
            (row["claim_id_a"],),
        ).fetchone()
        row_b = conn.execute(
            "SELECT claim_json FROM claims WHERE claim_id = ?",
            (row["claim_id_b"],),
        ).fetchone()
        if not row_a or not row_b:
            continue

        claim_a = json.loads(row_a["claim_json"])
        claim_b = json.loads(row_b["claim_json"])
        message_id = row_a["message_id"]
        msg = msg_map.get(message_id)
        debate = debate_map.get(message_id)
        if not msg or not debate:
            continue

        nli_scores = {"contradiction": float(row["contradiction"])}
        candidate = _build_candidate_annotation(claim_a, claim_b, nli_scores)

        try:
            # Žalobce
            prosecutor_payload = build_prosecutor_payload(candidate, [])
            prosecutor_raw = backend.call(
                "PROSECUTOR", PROSECUTOR_PROMPT, prosecutor_payload, TRIBUNAL_MODEL
            )
            prosecutor_case = parse_prosecutor_response(prosecutor_raw)

            # Obhájce
            context = build_same_day_context(msg, debate)
            defense_payload = build_defense_payload(candidate, context)
            defense_raw = backend.call(
                "DEFENSE", DEFENSE_PROMPT, defense_payload, TRIBUNAL_MODEL
            )
            defense_verdict = parse_defense_response(defense_raw)

            # Soudce
            arbiter_payload = build_arbiter_payload(candidate, prosecutor_case, defense_verdict)
            arbiter_raw = backend.call(
                "ARBITER", ARBITER_PROMPT, arbiter_payload, TRIBUNAL_MODEL
            )
            arbiter_verdict = parse_arbiter_response(arbiter_raw)

        except _PendingCall:
            continue

        # Složit AdversarialCheck z výstupů tří rolí
        adversarial_check = {
            "passed": bool(arbiter_verdict.get("passed", True)),
            "defenseEvaluated": defense_verdict.get("defenseEvaluated", ""),
            "defensesConsidered": defense_verdict.get("defensesConsidered", []),
            "prosecutorCase": prosecutor_case.get("case", ""),
            "arbiterRationale": arbiter_verdict.get("arbiterRationale", ""),
            "modelProvenance": "{}/{}".format(TRIBUNAL_MODEL, ENGINE_VERSION),
        }
        if defense_verdict.get("downgradeTo"):
            adversarial_check["downgradeTo"] = defense_verdict["downgradeTo"]

        candidate["adversarialCheck"] = adversarial_check

        final_annotation = apply_adversarial_verdict(candidate, adversarial_check)
        if final_annotation is None:
            continue

        # Doplnit confidenceScore z arbitra
        if arbiter_verdict.get("confidenceScore") is not None:
            final_annotation["confidenceScore"] = float(arbiter_verdict["confidenceScore"])

        tier = get_presentation_tier(final_annotation.get("confidenceScore", 0))
        final_annotation["presentationTier"] = tier

        store_verdict(
            conn, pid, message_id, final_annotation,
            tier, final_annotation.get("confidenceScore", 0),
            TRIBUNAL_MODEL, ENGINE_VERSION,
        )
        done += 1
        print("  [tribunal] {} → {} ({:.2f})".format(
            message_id, tier, final_annotation.get("confidenceScore", 0)
        ))

    print("tribunal: {} verdiktů uloženo".format(done))
    return done


# ---------------------------------------------------------------------------
# Fáze B: verify_proof na čekajících verdiktech
# ---------------------------------------------------------------------------

def phase_verify(conn) -> Tuple[int, int]:
    """
    Spustí verify_proof.py na všech verdiktech, které ještě neprošly
    (proof_verified = 0). Úspěšné označí 1, neúspěšné -1.
    """
    rows = conn.execute(
        "SELECT verdict_id, annotation_json FROM verdicts WHERE proof_verified = 0"
    ).fetchall()
    if not rows:
        print("verify: žádné nevyřízené verdikty")
        return 0, 0

    client = PspClient()
    ok = fail = 0
    for row in rows:
        ann = json.loads(row["annotation_json"])
        err = verify_annotation(ann, client)
        passed = err is None
        mark_verdict_verified(conn, row["verdict_id"], passed)
        if passed:
            ok += 1
        else:
            fail += 1
            print("  [verify] ZAMÍTNUTO {}: {}".format(row["verdict_id"][:20], err))

    print("verify: {} prošlo, {} zamítnuto".format(ok, fail))
    return ok, fail


# ---------------------------------------------------------------------------
# Fáze export
# ---------------------------------------------------------------------------

def phase_export() -> int:
    import subprocess
    result = subprocess.run(
        [sys.executable, os.path.join(PIPELINE_DIR, "export_web.py")],
        capture_output=False,
    )
    return result.returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Pipeline Nezalžeme.cz — orchestrátor."
    )
    parser.add_argument(
        "--schuze", type=int, default=None,
        help="Zpracovat pouze tuto schůzi (číslo).",
    )
    parser.add_argument(
        "--faze",
        choices=["claims", "retrieval", "nli", "tribunal", "verify", "export", "vse"],
        default="vse",
        help="Spustit pouze tuto fázi (výchozí: vse).",
    )
    parser.add_argument(
        "--pokracovat", action="store_true",
        help="Přeskočit práci, která je již v engine.sqlite.",
    )
    parser.add_argument(
        "--backend", choices=["api", "jsonl"], default="api",
        help="Model backend: api (Anthropic) nebo jsonl (nulové náklady).",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    conn = open_engine_db()
    if args.backend == "jsonl":
        backend = JsonlBackend(conn)
    else:
        backend = ApiBackend(conn)

    faze = args.faze
    run_all = faze == "vse"

    print("=== Pipeline Nezalžeme.cz (backend={}, faze={}, schuze={}) ===".format(
        args.backend, faze, args.schuze or "vše"
    ))

    if faze == "export":
        return phase_export()

    pairs = load_corpus(schuze=args.schuze)
    if not pairs and faze != "export":
        print("Žádná substantivní vystoupení pro schuze={}.".format(args.schuze))
        return 1
    print("Načteno {} substantivních vystoupení.".format(len(pairs)))

    try:
        if run_all or faze == "claims":
            phase_claims(pairs, conn, backend, args.pokracovat)

        if run_all or faze == "retrieval":
            phase_retrieval(pairs, conn)

        if run_all or faze == "nli":
            phase_nli(conn)

        if run_all or faze == "tribunal":
            phase_tribunal(pairs, conn, backend, args.pokracovat)

        if run_all or faze == "verify":
            phase_verify(conn)

        backend.finalize()

    except PendingCallsError as exc:
        print()
        print("=== JSONL FRONTA ===")
        print("{} volání čeká. Zpracuj {} v Claude Code:".format(exc.count, exc.queue_path))
        print("  Přečti každý řádek fronty → zavolej model → zapiš odpovědi do")
        print("  {}".format(
            os.path.join(PIPELINE_DIR, "data", "llm_responses.jsonl")
        ))
        print("  Formát řádku: {{\"cache_key\":\"…\",\"response_text\":\"…\"}}")
        print("  Pak spusť znovu s --pokracovat.")
        return 2

    if run_all or faze == "export":
        return phase_export()

    # Souhrn
    analyzed = analyzed_message_ids(conn)
    total_verdicts = conn.execute("SELECT COUNT(*) AS n FROM verdicts WHERE proof_verified = 1").fetchone()["n"]
    print()
    print("=== Hotovo ===")
    print("  Analyzováno vystoupení: {}".format(len(analyzed)))
    print("  Ověřených verdiktů: {}".format(total_verdicts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
