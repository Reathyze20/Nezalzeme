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
                    tribunal | slovocin | programovavernost | verify | export.
                    Výchozí: vse (programovavernost do "vse" nepatří — nad
                    stenokorpusem neběží, spouští se zvlášť).
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

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    now_iso,
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
from model_backend import (  # noqa: E402
    ApiBackend,
    GeminiBackend,
    JsonlBackend,
    PendingCallsError,
    _PendingCall,
)
from scoring import build_signals_from_pipeline, compute_composite_score  # noqa: E402
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
NLI_CONTRADICTION_THRESHOLD = 0.80   # minimum pro předání tribunálu (odfiltrování slabého šumu)
# journalist_tool.py duplikuje tuhle hodnotu jako NLI_BAND_MAX (nejde ji importovat
# bez zbytečného stržení torch/transformers) — změníš-li ji tady, uprav ji i tam.
MIN_SIMILARITY_THRESHOLD = 0.60      # minimální sémantická podobnost (odfiltrování nesouvisejících témat)
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
                # Přeskočit předsedající schůze — řídí jednání, nemají politické postoje
                src = msg.get("source") or {}
                if src.get("isChair"):
                    continue
                role = (msg.get("role") or "").lower()
                if "předsedající" in role:
                    continue

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
        model_used = backend.effective_model(CLAIM_EXTRACTION_MODEL)
        store_claims(conn, mid, speaker_id, claims, model_used)
        done += 1
        print("  [claims] {} -> {} tvrzení".format(mid, len(claims)))
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

    seen_pairs = set()
    pair_count = 0
    now = now_iso()
    for speaker_id in sorted(speaker_ids):
        claims = load_claims_for_speaker(conn, speaker_id)
        if len(claims) < 2:
            continue
        for query_claim in claims:
            candidates = retrieve_candidates(
                query_claim, claims, encoder, top_k=TOP_K_RETRIEVAL, retrieved_at=now
            )
            for pair in candidates:
                pair_tuple = tuple(sorted([pair.claim_id, pair.candidate_claim_id]))
                if pair_tuple in seen_pairs:
                    continue
                seen_pairs.add(pair_tuple)

                pair_id = pair.claim_id + "::" + pair.candidate_claim_id
                store_candidate_pair(
                    conn,
                    pair_id,
                    pair.claim_id,
                    pair.candidate_claim_id,
                    pair.bi_encoder_score,
                    timeframe_conflict=getattr(pair, "timeframe_conflict", False),
                )
                pair_count += 1
    print("retrieval: {} kandidátních párů nalezeno".format(pair_count))
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

def _build_candidate_annotation(
    claim_a, claim_b, nli_result, msg_b=None, debate_b=None
) -> Dict[str, Any]:
    """Sestaví hrubý kandidát ve tvaru, který tribunál dostane jako vstup."""
    past_date = (msg_b.get("date") if msg_b else None) or claim_b.get("timeFrame", "NEURČENO")
    past_url = ((msg_b.get("source") or {}).get("stenoUrl") if msg_b else "") or ""
    past_ctx = (debate_b.get("title") if debate_b else None) or "Dřívější vystoupení téhož řečníka"

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
            "pastDate": past_date,
            "pastContext": past_ctx,
            "sourceUrl": past_url,
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

    try:
        from psp.client import PspClient
        from psp.opendata import Registry, _parse_date
        registry = Registry.load(PspClient())
    except Exception:
        registry = None
        def _parse_date(s): return None

    rows = conn.execute(
        "SELECT n.pair_id, n.contradiction, n.nli_relation, "
        "       p.claim_id_a, p.claim_id_b, p.similarity_score "
        "FROM nli_results n JOIN candidate_pairs p ON n.pair_id = p.pair_id "
        "WHERE n.contradiction >= ? AND p.similarity_score >= ? AND n.nli_relation = 'CONTRADICTION' "
        "ORDER BY n.contradiction DESC",
        (NLI_CONTRADICTION_THRESHOLD, MIN_SIMILARITY_THRESHOLD),
    ).fetchall()

    if not rows:
        print("tribunal: žádné páry s dostatečným CONTRADICTION a SIMILARITY skóre")
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
            "SELECT claim_json, message_id FROM claims WHERE claim_id = ?",
            (row["claim_id_b"],),
        ).fetchone()
        if not row_a or not row_b:
            continue

        claim_a = json.loads(row_a["claim_json"])
        claim_b = json.loads(row_b["claim_json"])

        # 0. Vyřadit procedurální a čistě formální tvrzení ze vstupu do Tribunálu
        cat_a = claim_a.get("claimCategory") or claim_a.get("claim_category", "")
        cat_b = claim_b.get("claimCategory") or claim_b.get("claim_category", "")
        if cat_a == "PROCEDURAL" or cat_b == "PROCEDURAL":
            continue

        raw_a = (claim_a.get("rawSpan") or "").lower() + " " + (claim_a.get("subject") or "").lower()
        raw_b = (claim_b.get("rawSpan") or "").lower() + " " + (claim_b.get("subject") or "").lower()
        procedural_phrases = (
            "hlasování číslo", "hlasování č.", "návrh byl přijat", "návrh nebyl přijat",
            "návrh usnesení byl", "zahajuji hlasování", "končím hlasování",
            "stiskněte tlačítko", "předávám slovo", "omlouvám se za",
            "vejdu se do dvou minut", "děkuji za slovo", "přeji hezké",
        )
        if any(p in raw_a for p in procedural_phrases) or any(p in raw_b for p in procedural_phrases):
            continue

        message_id = row_a["message_id"]
        message_id_b = row_b["message_id"]

        # 1. Týž projev nemůže být rozpor v čase
        if message_id == message_id_b:
            continue

        msg = msg_map.get(message_id)
        debate = debate_map.get(message_id)
        msg_b = msg_map.get(message_id_b)
        debate_b = debate_map.get(message_id_b)

        if not msg or not debate:
            continue

        # 2. Stejná rozprava v týž den — mluvčí reaguje v rámci jedné diskuze,
        # skutečné rozpory v čase (CONTRADICTION_TIME) vznikají napříč schůzemi/dny.
        if debate_b and debate.get("debateId") == debate_b.get("debateId"):
            continue

        nli_scores = {"contradiction": float(row["contradiction"])}
        candidate = _build_candidate_annotation(
            claim_a, claim_b, nli_scores, msg_b=msg_b, debate_b=debate_b
        )

        try:
            # Žalobce
            prosecutor_payload = build_prosecutor_payload(candidate, [])
            prosecutor_raw = backend.call(
                "PROSECUTOR", PROSECUTOR_PROMPT, prosecutor_payload, TRIBUNAL_MODEL
            )
            prosecutor_case = parse_prosecutor_response(prosecutor_raw)

            # Obhájce — s makroekonomickým kontextem z ČSÚ/ČNB a politickou rolí
            context = build_same_day_context(msg, debate)
            debate_date = debate.get("date", "")
            macro_month = debate_date[:7] if len(debate_date) >= 7 else ""
            macro_ctx = None
            if macro_month:
                try:
                    from macro_context import get_macro_context  # noqa: E402
                    macro_ctx = get_macro_context(macro_month)
                except Exception:
                    macro_ctx = None

            role_ctx = None
            if registry:
                try:
                    dt_a = _parse_date(debate_date)
                    dt_b = _parse_date(debate_b.get("date", "")) if debate_b else None
                    spk_id = str((msg.get("source") or {}).get("idOsoba") or "")
                    if spk_id and dt_a:
                        ra = registry.political_role_at(spk_id, dt_a)
                        rb = registry.political_role_at(spk_id, dt_b) if dt_b else None
                        if rb and (ra["role"] != rb["role"] or ra["isGovernment"] != rb["isGovernment"]):
                            role_ctx = {
                                "currentSpeech": {"date": str(dt_a), "role": ra["role"], "club": ra["club"], "isGovernment": ra["isGovernment"]},
                                "pastSpeech": {"date": str(dt_b), "role": rb["role"], "club": rb["club"], "isGovernment": rb["isGovernment"]},
                                "roleShift": True,
                            }
                except Exception:
                    role_ctx = None

            defense_payload = build_defense_payload(candidate, context, macro_ctx, role_ctx)
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
        model_used = backend.effective_model(TRIBUNAL_MODEL)
        downgrade_choice = arbiter_verdict.get("downgradeTo") or defense_verdict.get("downgradeTo")
        is_dismissed = bool(arbiter_verdict.get("dismiss", False))
        arbiter_passed = bool(arbiter_verdict.get("passed", True)) and not is_dismissed

        adversarial_check = {
            "passed": arbiter_passed,
            "dismiss": is_dismissed,
            "defenseEvaluated": defense_verdict.get("defenseEvaluated", ""),
            "defensesConsidered": defense_verdict.get("defensesConsidered", []),
            "prosecutorCase": prosecutor_case.get("case", ""),
            "arbiterRationale": arbiter_verdict.get("arbiterRationale", ""),
            "modelProvenance": "{}/{}".format(model_used, ENGINE_VERSION),
        }
        if downgrade_choice:
            adversarial_check["downgradeTo"] = downgrade_choice
        if arbiter_verdict.get("confidenceScore") is not None:
            adversarial_check["confidenceScore"] = arbiter_verdict["confidenceScore"]

        candidate["adversarialCheck"] = adversarial_check

        final_annotation = apply_adversarial_verdict(candidate, adversarial_check)
        if final_annotation is None:
            store_verdict(
                conn, pid, message_id,
                {"dismissed": True, "adversarialCheck": adversarial_check},
                "DROPPED", 0.0,
                model_used, ENGINE_VERSION,
            )
            print("  [tribunal] {} -> ZAMÍTNUTO obhajobou".format(pid))
            continue

        # Kompozitní skóre místo přímého kopírování z arbitra (Fáze E)
        retrieval_sim = float(row["similarity_score"]) if row["similarity_score"] is not None else None
        tribunal_ok = arbiter_passed or bool(downgrade_choice)
        signals = build_signals_from_pipeline(
            nli_scores={"CONTRADICTION": float(row["contradiction"])},
            retrieval_score=retrieval_sim,
            tribunal_passed=tribunal_ok,
            arbiter_confidence=(
                float(arbiter_verdict["confidenceScore"])
                if arbiter_verdict.get("confidenceScore") is not None
                else None
            ),
        )
        composite = compute_composite_score(signals)
        final_annotation["confidenceScore"] = composite

        tier = get_presentation_tier(composite)
        final_annotation["presentationTier"] = tier

        store_verdict(
            conn, pid, message_id, final_annotation,
            tier, final_annotation.get("confidenceScore", 0),
            model_used, ENGINE_VERSION,
        )
        done += 1
        print("  [tribunal] {} -> {} ({:.2f})".format(
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

def phase_slovo_cin(conn, backend, pokracovat: bool = False, schuze=None) -> None:
    """
    Fáze 3 — Slovo vs. Čin: postoj z rozpravy vedle jmenovitého hlasování.

    Nahrazuje detekci rozporů mezi projevy jako zdroj publikovatelných
    nálezů. Veškerá logika i pojistky jsou v `slovo_cin.py`; tady se jen
    prochází kandidáti a volá model.
    """
    from psp.client import PspClient
    from psp.opendata import TERM_ORGAN_ID, Registry
    from slovo_cin import (
        ENGINE_VERSION as SC_VERSION,
        PUBLIKOVATELNE_POSTOJE,
        build_record,
        challenge_mismatch,
        classify_stance,
        find_candidates,
        klub_tally_for_ballot,
        load_corpus_index,
        resolve_vote,
        store_record,
    )
    from datetime import datetime

    print()
    print("--- Fáze 3: Slovo vs. Čin ---")

    client = PspClient()
    organ = str(TERM_ORGAN_ID)
    corpus_index = load_corpus_index(os.path.join(PIPELINE_DIR, "data", "psp"))
    registry = Registry.load(client)

    candidates = find_candidates(conn, corpus_index, client, id_organ=organ)
    if schuze is not None:
        candidates = [c for c in candidates if c["debate"].get("sessionNumber") == schuze]
    print("  Kandidátů (výrok + finální hlasování o témže tisku): {}".format(len(candidates)))
    if not candidates:
        return

    hotove = set()
    if pokracovat:
        hotove = {r["id"] for r in conn.execute("SELECT id FROM slovo_cin").fetchall()}

    model_name = getattr(backend, "default_model", CLAIM_EXTRACTION_MODEL)
    ulozeno = tally = 0
    prehled = {"SHODA": 0, "NESHODA": 0, "NEHLASOVAL": 0}
    nepublikovatelne = 0
    obhajeno = 0

    for index, candidate in enumerate(candidates, start=1):
        record_id = "sc-{}-{}".format(candidate["claimId"], candidate["finalVote"]["idHlasovani"])
        if record_id in hotove:
            continue

        stance = classify_stance(backend, candidate["claim"], candidate["bod"]["nazev"], model_name)
        tally += 1
        # Postoj, ze kterého se nedá nic dovodit, se dál nezpracovává —
        # ušetří to i dotaz na hlasovací lístek.
        if stance["postoj"] not in PUBLIKOVATELNE_POSTOJE:
            nepublikovatelne += 1
            continue

        final_vote = candidate["finalVote"]
        vote_row = conn.execute(
            "SELECT datum, cas FROM hlasovani WHERE id_hlasovani = ?",
            (final_vote["idHlasovani"],),
        ).fetchone()
        if not vote_row:
            continue

        id_poslanec = registry.deputy_id(candidate["idOsoba"])
        vote = resolve_vote(
            client, conn, final_vote["idHlasovani"], candidate["idOsoba"],
            id_poslanec, vote_row["datum"], vote_row["cas"], id_organ=organ,
        )
        if not vote:
            continue

        when = None
        try:
            when = datetime.strptime(vote_row["datum"], "%d.%m.%Y").date()
        except ValueError:
            pass
        klub_pomer = klub_tally_for_ballot(
            conn, registry, final_vote["idHlasovani"], vote.get("klub") or "", when
        ) if when else None

        record = build_record(candidate, stance, vote, klub_pomer)

        # Adversariální přezkum běží JEN na neshodách — jen ty o někom něco
        # tvrdí. Neobstojí-li obžaloba, položka se vůbec neuloží.
        if record["shoda"] == "NESHODA":
            obhajoba = challenge_mismatch(backend, record, model_name)
            if obhajoba["rozporMizi"]:
                obhajeno += 1
                continue
            record["obhajobaNeobstala"] = obhajoba["vyklad"]

        store_record(conn, record, model_name)
        prehled[record["shoda"]] = prehled.get(record["shoda"], 0) + 1
        ulozeno += 1

        if index % 25 == 0:
            conn.commit()
            print("  ... {}/{} posouzeno, {} uloženo".format(index, len(candidates), ulozeno))

    conn.commit()
    print("  Posouzeno modelem: {}".format(tally))
    print("  Bez publikovatelného postoje (NEUTRALNI/NEURCITELNE): {}".format(nepublikovatelne))
    print("  Neshod zamítnutých obhájcem: {}".format(obhajeno))
    print("  Uloženo záznamů: {}  (shoda {}, neshoda {}, nehlasoval {})".format(
        ulozeno, prehled.get("SHODA", 0), prehled.get("NESHODA", 0), prehled.get("NEHLASOVAL", 0)
    ))


def phase_programova_vernost(conn, backend, pokracovat: bool = False) -> None:
    """
    Fáze 4 — Programová věrnost: závazek z vládního prohlášení vedle
    hlasování koaličních klubů o odpovídajícím tisku.

    Nepotřebuje stenokorpus (na rozdíl od ostatních fází) — pracuje nad
    celým volebním obdobím z otevřených dat, ne jen nad staženými schůzemi.
    Veškerá logika a pojistky jsou v `programova_vernost.py`.
    """
    from datetime import datetime

    from programova_vernost import (
        build_record,
        challenge_pairing,
        extract_zavazky,
        fetch_prohlaseni_client,
        find_tisk_candidate,
        ingest_kapitoly,
        kluby_tally_for_ballot,
        latest_final_vote,
        store_record,
        store_zavazek,
    )
    from psp.client import PspClient
    from psp.opendata import TERM_ORGAN_ID, Registry
    from psp.tisky import TiskyRegistry

    print()
    print("--- Fáze 4: Programová věrnost ---")

    vlada_client = fetch_prohlaseni_client()
    psp_client = PspClient()
    organ = str(TERM_ORGAN_ID)
    registry = Registry.load(psp_client)
    tisky_registry = TiskyRegistry.load(psp_client)

    kapitoly = ingest_kapitoly(conn, vlada_client)
    kapitola_by_id = {k["id"]: k for k in kapitoly}
    print("  Kapitol prohlášení: {}".format(len(kapitoly)))

    model_name = getattr(backend, "default_model", CLAIM_EXTRACTION_MODEL)

    hotove_zavazky = {r["id"] for r in conn.execute("SELECT id FROM programove_zavazky").fetchall()}
    zavazky = []
    for kapitola in kapitoly:
        for zavazek in extract_zavazky(backend, kapitola, model_name):
            if zavazek["id"] not in hotove_zavazky:
                store_zavazek(conn, zavazek, model_name)
            zavazky.append(zavazek)
    conn.commit()
    print("  Konkrétních závazků nalezeno: {}".format(len(zavazky)))

    tisky_pro_prompt = [
        {"cislo": info.cislo, "nazev": info.cely_nazev}
        for info in tisky_registry.all_for_organ(organ)
    ]

    hotove_parovani = set()
    if pokracovat:
        hotove_parovani = {
            r["zavazek_id"] for r in conn.execute("SELECT zavazek_id FROM programova_vernost").fetchall()
        }

    ulozeno = bez_kandidata = zamitnuto_oponentem = bez_hlasovani = 0

    for index, zavazek in enumerate(zavazky, start=1):
        if pokracovat and zavazek["id"] in hotove_parovani:
            continue

        kandidat = find_tisk_candidate(backend, zavazek["citace"], tisky_pro_prompt, model_name)
        if not kandidat:
            bez_kandidata += 1
            continue

        tisk_info = tisky_registry.get_tisk(kandidat["cislo"], organ=organ)
        if not tisk_info:
            continue

        prezkum = challenge_pairing(
            backend, zavazek["citace"], tisk_info.cely_nazev, kandidat["zduvodneni"], model_name,
        )
        if not prezkum["parovaniPlati"]:
            zamitnuto_oponentem += 1
            continue

        final_vote = latest_final_vote(psp_client, kandidat["cislo"], conn, id_organ=organ)
        if not final_vote or not final_vote.get("idHlasovani"):
            bez_hlasovani += 1
            continue

        vote_row = conn.execute(
            "SELECT datum FROM hlasovani WHERE id_hlasovani = ?", (final_vote["idHlasovani"],),
        ).fetchone()
        when = None
        if vote_row:
            try:
                when = datetime.strptime(vote_row["datum"], "%d.%m.%Y").date()
            except ValueError:
                pass
        kluby = kluby_tally_for_ballot(conn, registry, final_vote["idHlasovani"], when) if when else {}

        record = build_record(
            zavazek, kapitola_by_id[zavazek["kapitolaId"]],
            {"cislo": tisk_info.cislo, "nazev": tisk_info.cely_nazev},
            final_vote, kandidat["zduvodneni"], kluby,
            datum=when.isoformat() if when else "",
        )
        store_record(conn, record, model_name)
        ulozeno += 1

        if index % 10 == 0:
            conn.commit()
            print("  ... {}/{} posouzeno, {} uloženo".format(index, len(zavazky), ulozeno))

    conn.commit()
    print("  Bez kandidátního tisku: {}".format(bez_kandidata))
    print("  Zamítnuto nezávislým přezkumem: {}".format(zamitnuto_oponentem))
    print("  Bez dokončeného projednání tisku: {}".format(bez_hlasovani))
    print("  Uloženo záznamů: {}".format(ulozeno))
    print("  " + psp_client.summary())
    print("  " + vlada_client.summary())


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
        choices=[
            "claims", "retrieval", "nli", "tribunal", "slovocin",
            "programovavernost", "verify", "export", "vse",
        ],
        default="vse",
        help="Spustit pouze tuto fázi (výchozí: vse).",
    )
    parser.add_argument(
        "--pokracovat", action="store_true",
        help="Přeskočit práci, která je již v engine.sqlite.",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "gemini", "api", "anthropic", "jsonl"],
        default="auto",
        help="Model backend: auto (podle nastaveného klíče), gemini, api/anthropic, jsonl.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    conn = open_engine_db()
    backend_choice = args.backend
    if backend_choice == "auto":
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            backend_choice = "gemini"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            backend_choice = "api"
        else:
            # Výchozí doporučený provider je Gemini
            backend_choice = "gemini"

    if backend_choice == "jsonl":
        backend = JsonlBackend(conn)
        backend_desc = "jsonl"
    elif backend_choice == "gemini":
        backend = GeminiBackend(conn)
        backend_desc = "gemini ({})".format(backend.default_model)
    else:
        backend = ApiBackend(conn)
        backend_desc = "anthropic ({})".format(CLAIM_EXTRACTION_MODEL)

    faze = args.faze
    run_all = faze == "vse"

    print("=== Pipeline Nezalžeme.cz (backend={}, faze={}, schuze={}) ===".format(
        backend_desc, faze, args.schuze or "vše"
    ))

    if faze == "export":
        return phase_export()

    if faze == "programovavernost":
        # Nepotřebuje stenokorpus (pracuje nad celým obdobím z otevřených
        # dat), proto stojí mimo `vse` a mimo kontrolu na `pairs` níže.
        phase_programova_vernost(conn, backend, args.pokracovat)
        backend.finalize()
        return 0

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

        if run_all or faze == "slovocin":
            phase_slovo_cin(conn, backend, args.pokracovat, args.schuze)

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
