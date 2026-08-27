"""
Engine SQLite — trvalý stav pipeline mezi fázemi.

Jedno soubor, jedno schéma. Tabulky `facts` (CLUB_MEMBERSHIP, VOTE_CAST…)
sdílí úložiště s tabulkami strojového enginu (claims, verdicts…) — jeden
SQLite soubor, jeden otevřený connection, žádné cross-DB dotazy.

    from db import open_engine_db, cache_key, now_iso

    conn = open_engine_db()            # vytvoří pipeline/data/engine.sqlite
    conn = open_engine_db(":memory:")  # testy

Cesta k souboru pochází z `psp.facts.ENGINE_SQLITE_PATH`.
"""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from psp.facts import ENGINE_SQLITE_PATH
from psp.facts import SCHEMA_SQL as _FACTS_SCHEMA   # CLUB_MEMBERSHIP, VOTE_CAST…

# ---------------------------------------------------------------------------
# Schéma
# ---------------------------------------------------------------------------

_ENGINE_SCHEMA = _FACTS_SCHEMA + """
-- Atomická tvrzení rozložená z vystoupení (Fáze 2b).
-- claim_json nese celý Claim dict tak, jak ho vyprodukoval parse_claims_response.
CREATE TABLE IF NOT EXISTS claims (
    claim_id         TEXT PRIMARY KEY,
    message_id       TEXT NOT NULL,
    speaker_id_osoba TEXT NOT NULL,
    claim_json       TEXT NOT NULL,
    produced_at      TEXT NOT NULL,
    model_name       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_message ON claims(message_id);
CREATE INDEX IF NOT EXISTS idx_claims_speaker ON claims(speaker_id_osoba, produced_at);

-- Kandidátní páry (Fáze 3, retrieval).
CREATE TABLE IF NOT EXISTS candidate_pairs (
    pair_id          TEXT PRIMARY KEY,
    claim_id_a       TEXT NOT NULL,
    claim_id_b       TEXT NOT NULL,
    similarity_score REAL NOT NULL,
    produced_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pairs_a ON candidate_pairs(claim_id_a);
CREATE INDEX IF NOT EXISTS idx_pairs_b ON candidate_pairs(claim_id_b);

-- NLI výsledky na kandidátních párech (Fáze 3, NLI).
CREATE TABLE IF NOT EXISTS nli_results (
    pair_id         TEXT PRIMARY KEY,
    entailment      REAL NOT NULL,
    neutral         REAL NOT NULL,
    contradiction   REAL NOT NULL,
    nli_relation    TEXT NOT NULL,
    produced_at     TEXT NOT NULL
);

-- Verdikty tribunálu → Annotation (Fáze 4).
-- annotation_json je celý Annotation dict připravený pro export_web.py.
-- proof_verified: 0 = čeká na kontrolu, 1 = ověřeno, -1 = zamítnuto bránou.
CREATE TABLE IF NOT EXISTS verdicts (
    verdict_id       TEXT PRIMARY KEY,
    message_id       TEXT NOT NULL,
    annotation_json  TEXT NOT NULL,
    presentation_tier TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    produced_at      TEXT NOT NULL,
    model_name       TEXT NOT NULL,
    engine_version   TEXT NOT NULL,
    proof_verified   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_verdicts_message ON verdicts(message_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_tier   ON verdicts(presentation_tier, proof_verified);

-- LLM cache — vyhne se opakovanému placení za stejný prompt.
-- Klíč = sha256(model_name + "::" + full_prompt).
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key    TEXT PRIMARY KEY,
    response_text TEXT NOT NULL,
    model_name   TEXT NOT NULL,
    cached_at    TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Veřejné rozhraní
# ---------------------------------------------------------------------------

def open_engine_db(path: str = ENGINE_SQLITE_PATH) -> sqlite3.Connection:
    """
    Otevře (nebo vytvoří) engine.sqlite s plným schématem.

    `path=":memory:"` pro testy; produkční cesta je `ENGINE_SQLITE_PATH`
    z `psp.facts`.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True) if path != ":memory:" else None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_ENGINE_SCHEMA)
    conn.commit()
    return conn


def cache_key(model_name: str, prompt: str) -> str:
    """Deterministický klíč pro LLM cache."""
    return hashlib.sha256("{}::{}".format(model_name, prompt).encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Helpery pro čtení
# ---------------------------------------------------------------------------

def load_claims_for_speaker(conn: sqlite3.Connection, speaker_id_osoba: str) -> List[Dict[str, Any]]:
    """Všechna tvrzení daného řečníka ze všech schůzí — základ pro retrieval."""
    rows = conn.execute(
        "SELECT claim_json FROM claims WHERE speaker_id_osoba = ? ORDER BY produced_at",
        (speaker_id_osoba,),
    ).fetchall()
    return [json.loads(row["claim_json"]) for row in rows]


def load_claims_for_message(conn: sqlite3.Connection, message_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT claim_json FROM claims WHERE message_id = ?",
        (message_id,),
    ).fetchall()
    return [json.loads(row["claim_json"]) for row in rows]


def message_already_processed(conn: sqlite3.Connection, message_id: str) -> bool:
    """True pokud z tohoto vystoupení byly již extrahována tvrzení."""
    row = conn.execute(
        "SELECT 1 FROM claims WHERE message_id = ? LIMIT 1",
        (message_id,),
    ).fetchone()
    return row is not None


def pair_already_nli(conn: sqlite3.Connection, pair_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM nli_results WHERE pair_id = ? LIMIT 1",
        (pair_id,),
    ).fetchone()
    return row is not None


def load_annotations_for_message(conn: sqlite3.Connection, message_id: str) -> List[Dict[str, Any]]:
    """Načte ověřené anotace (proof_verified=1) pro jedno vystoupení."""
    rows = conn.execute(
        "SELECT annotation_json FROM verdicts WHERE message_id = ? AND proof_verified = 1",
        (message_id,),
    ).fetchall()
    return [json.loads(row["annotation_json"]) for row in rows]


def analyzed_message_ids(conn: sqlite3.Connection) -> set:
    """Množina messageId, nad kterými engine extrahoval tvrzení."""
    rows = conn.execute("SELECT DISTINCT message_id FROM claims").fetchall()
    return {row["message_id"] for row in rows}


def store_claims(conn: sqlite3.Connection, message_id: str, speaker_id_osoba: str,
                 claims: List[Dict[str, Any]], model_name: str) -> None:
    ts = now_iso()
    for claim in claims:
        conn.execute(
            "INSERT OR REPLACE INTO claims (claim_id, message_id, speaker_id_osoba, claim_json, produced_at, model_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (claim["claimId"], message_id, speaker_id_osoba,
             json.dumps(claim, ensure_ascii=False), ts, model_name),
        )
    conn.commit()


def store_candidate_pair(conn: sqlite3.Connection, pair_id: str, claim_id_a: str,
                         claim_id_b: str, score: float) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO candidate_pairs (pair_id, claim_id_a, claim_id_b, similarity_score, produced_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (pair_id, claim_id_a, claim_id_b, score, now_iso()),
    )
    conn.commit()


def store_nli_result(conn: sqlite3.Connection, pair_id: str, scores: Dict[str, float],
                     relation: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO nli_results (pair_id, entailment, neutral, contradiction, nli_relation, produced_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pair_id, scores.get("ENTAILMENT", 0.0), scores.get("NEUTRAL", 0.0),
         scores.get("CONTRADICTION", 0.0), relation, now_iso()),
    )
    conn.commit()


def store_verdict(conn: sqlite3.Connection, verdict_id: str, message_id: str,
                  annotation: Dict[str, Any], tier: str, score: float,
                  model_name: str, engine_version: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO verdicts "
        "(verdict_id, message_id, annotation_json, presentation_tier, confidence_score, "
        "produced_at, model_name, engine_version, proof_verified) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (verdict_id, message_id, json.dumps(annotation, ensure_ascii=False),
         tier, score, now_iso(), model_name, engine_version),
    )
    conn.commit()


def mark_verdict_verified(conn: sqlite3.Connection, verdict_id: str, passed: bool) -> None:
    conn.execute(
        "UPDATE verdicts SET proof_verified = ? WHERE verdict_id = ?",
        (1 if passed else -1, verdict_id),
    )
    conn.commit()
