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

#: Otevřená data hlasování PSP ČR (`psp/opendata_hlasovani.py`) — samostatné
#: tabulky, ne generický `facts` EAV. Naplňuje je `populate_voting_tables()`;
#: zdroj je `hl-YYYYps.zip` + `schuze.zip` + `steno.zip`, vždy pro jedno
#: volební období (`id_organ`).
_VOTING_SCHEMA = """
CREATE TABLE IF NOT EXISTS schuze (
    id_schuze TEXT PRIMARY KEY,
    id_organ  TEXT NOT NULL,
    cislo     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schuze_organ_cislo ON schuze(id_organ, cislo);

CREATE TABLE IF NOT EXISTS bod_schuze (
    id_bod    TEXT PRIMARY KEY,
    id_schuze TEXT NOT NULL,
    id_tisk   TEXT,
    bod       INTEGER,
    nazev     TEXT NOT NULL,
    tisk_ref  TEXT
);
CREATE INDEX IF NOT EXISTS idx_bod_schuze_schuze_bod ON bod_schuze(id_schuze, bod);
CREATE INDEX IF NOT EXISTS idx_bod_schuze_tisk ON bod_schuze(id_tisk);

-- Denormalizovaný spoj steno.unl (id_steno -> organ/schůze/turn) a rec.unl
-- (id_steno + kotva #rN -> id_bod) do jediné tabulky, protože jediný dotaz,
-- který nad ní kdy poběží, je přesně tenhle spoj: (turn, kotva, id_osoba)
-- z projevu -> id_bod, na kterém se hlasovalo.
CREATE TABLE IF NOT EXISTS rec_bod (
    id_organ TEXT NOT NULL,
    schuze   INTEGER NOT NULL,
    turn     INTEGER NOT NULL,
    anchor_n INTEGER NOT NULL,
    id_osoba TEXT NOT NULL,
    id_bod   TEXT NOT NULL,
    druh     TEXT,
    PRIMARY KEY (id_organ, schuze, turn, anchor_n)
);
CREATE INDEX IF NOT EXISTS idx_rec_bod_bod ON rec_bod(id_bod);

CREATE TABLE IF NOT EXISTS hlasovani (
    id_hlasovani TEXT PRIMARY KEY,
    id_organ     TEXT NOT NULL,
    schuze       INTEGER NOT NULL,
    cislo        INTEGER NOT NULL,
    bod          INTEGER NOT NULL,
    datum        TEXT NOT NULL,
    cas          TEXT NOT NULL,
    pro          INTEGER NOT NULL,
    proti        INTEGER NOT NULL,
    zdrzel       INTEGER NOT NULL,
    nehlasoval   INTEGER NOT NULL,
    prihlaseno   INTEGER NOT NULL,
    kvorum       INTEGER NOT NULL,
    vysledek     TEXT NOT NULL,
    nazev        TEXT NOT NULL,
    is_zmatecne  INTEGER NOT NULL DEFAULT 0,
    url          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hlasovani_bod ON hlasovani(id_organ, schuze, bod);

-- `kod` je syrový jednopísmenný kód z UNL (A/B/K/@ — viz VOTE_CODE_* v
-- opendata_hlasovani.py). Rozlišení "zdržel se" vs. "nehlasoval" (obojí K)
-- musí publikovaná položka dověřit z HTML `psp/hlasovani.py`, ne odsud.
CREATE TABLE IF NOT EXISTS hlas_poslance (
    id_hlasovani TEXT NOT NULL,
    id_poslanec  TEXT NOT NULL,
    kod          TEXT NOT NULL,
    PRIMARY KEY (id_hlasovani, id_poslanec)
);
CREATE INDEX IF NOT EXISTS idx_hlas_poslance_poslanec ON hlas_poslance(id_poslanec, id_hlasovani);

-- `id_poslanec`, ne `id_osoba` — omluvy.unl je jediný dump, který identifikuje
-- osobu přes id_poslanec přímo (ověřeno; id_osoba v tomhle souboru nefunguje).
CREATE TABLE IF NOT EXISTS omluva (
    id_organ    TEXT NOT NULL,
    id_poslanec TEXT NOT NULL,
    datum       TEXT NOT NULL,
    od          TEXT NOT NULL,
    do_cas      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_omluva_poslanec ON omluva(id_organ, id_poslanec, datum);

-- Zmatečná (zrušená) hlasování z zmatecne.unl — musí se vyloučit před
-- jakýmkoliv párováním výroku na hlasování.
CREATE TABLE IF NOT EXISTS zmatecne (
    id_hlasovani TEXT PRIMARY KEY
);

-- Slovo vs. Čin (Fáze 3) — postoj z rozpravy vedle jmenovitého hlasování.
-- Záměrně mimo `verdicts`: není to obvinění se skóre a závažností, ale
-- doložený výpis, u kterého si závěr dělá čtenář. `overeno` se přepočítává
-- při exportu znovu z otevřených dat; bez něj se položka nerenderuje.
CREATE TABLE IF NOT EXISTS slovo_cin (
    id            TEXT PRIMARY KEY,
    claim_id      TEXT NOT NULL,
    message_id    TEXT NOT NULL,
    id_osoba      TEXT NOT NULL,
    id_hlasovani  TEXT NOT NULL,
    tisk          TEXT,
    postoj        TEXT NOT NULL,
    hlas          TEXT NOT NULL,
    shoda         TEXT NOT NULL,
    zaznam_json   TEXT NOT NULL,
    overeno       INTEGER NOT NULL DEFAULT 0,
    produced_at   TEXT NOT NULL,
    model_name    TEXT NOT NULL,
    engine_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_slovo_cin_osoba ON slovo_cin(id_osoba);
CREATE INDEX IF NOT EXISTS idx_slovo_cin_message ON slovo_cin(message_id);
CREATE INDEX IF NOT EXISTS idx_slovo_cin_shoda ON slovo_cin(shoda, overeno);

-- Programová věrnost (Fáze 4) — text Programového prohlášení vlády, uložený
-- při ingesci stejně jako hlasovací dumpy, aby brána při exportu mohla
-- citaci znovu ověřit proti ULOŽENÉMU zdroji, ne proti tvrzení modelu o něm.
CREATE TABLE IF NOT EXISTS programove_kapitoly (
    id          TEXT PRIMARY KEY,
    poradi      INTEGER NOT NULL,
    nazev       TEXT NOT NULL,
    text        TEXT NOT NULL,
    fetched_at  TEXT NOT NULL
);

-- Atomizované závazky z jednotlivých kapitol. `citace` je vždy doslovný
-- podřetězec `programove_kapitoly.text` téže kapitoly — kontroluje se
-- při vzniku i znovu při exportu (`export_web.verify_programova_vernost`).
CREATE TABLE IF NOT EXISTS programove_zavazky (
    id              TEXT PRIMARY KEY,
    kapitola_id     TEXT NOT NULL,
    citace          TEXT NOT NULL,
    char_start      INTEGER NOT NULL,
    char_end        INTEGER NOT NULL,
    produced_at     TEXT NOT NULL,
    model_name      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_programove_zavazky_kapitola ON programove_zavazky(kapitola_id);

-- Spárování závazku se sněmovním tiskem a jeho finálním hlasováním.
-- Na rozdíl od `slovo_cin` tahle vazba není strukturální (žádný dump nespojuje
-- text vládního prohlášení s číslem tisku) — určuje ji model, a proto prochází
-- vlastní adversariální bránou (`programova_vernost.challenge_pairing`) už při
-- vzniku a `overeno` se při exportu nepočítá z ničeho uloženého, ale znovu
-- z otevřených dat (viz `programove_kapitoly`, `hlasovani`, `hlas_poslance`).
CREATE TABLE IF NOT EXISTS programova_vernost (
    id              TEXT PRIMARY KEY,
    zavazek_id      TEXT NOT NULL,
    tisk            TEXT NOT NULL,
    id_hlasovani    TEXT NOT NULL,
    zaznam_json     TEXT NOT NULL,
    overeno         INTEGER NOT NULL DEFAULT 0,
    produced_at     TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    engine_version  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_programova_vernost_zavazek ON programova_vernost(zavazek_id);
CREATE INDEX IF NOT EXISTS idx_programova_vernost_tisk ON programova_vernost(tisk);

-- Rolový obrat v médiích (Fáze 6b) — citace z novinového článku z doby, kdy
-- byl politik v opozici, vedle jeho hlasování z doby, kdy je (nebo byl) ve
-- vládní straně. Na rozdíl od `slovo_cin`/`programova_vernost` NENÍ zdroj
-- citace oficiální záznam (je to zpráva novináře o tom, co bylo řečeno, ne
-- stenozáznam) — proto navíc `schvaleno`: dokud je 0, `export_web.py`
-- záznam nikdy nevyexportuje, ať prošel jakoukoli strojovou bránou.
-- `schvaleno` nastavuje výhradně `promote_media_lead.py`, jeden lead po
-- druhém, poté co si operátor přečetl `zdroj_url` sám.
CREATE TABLE IF NOT EXISTS media_role_flip (
    id              TEXT PRIMARY KEY,
    id_osoba        TEXT NOT NULL,
    citace          TEXT NOT NULL,
    zdroj_url       TEXT NOT NULL,
    medium          TEXT NOT NULL,
    datum_clanku    TEXT NOT NULL,
    tisk            TEXT NOT NULL,
    id_hlasovani    TEXT NOT NULL,
    postoj          TEXT NOT NULL,
    hlas            TEXT NOT NULL,
    shoda           TEXT NOT NULL,
    parovani_plati  INTEGER NOT NULL DEFAULT 0,
    rozpor_mizi     INTEGER NOT NULL DEFAULT 1,
    zaznam_json     TEXT NOT NULL,
    schvaleno       INTEGER NOT NULL DEFAULT 0,
    schvaleno_at    TEXT,
    overeno         INTEGER NOT NULL DEFAULT 0,
    produced_at     TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    engine_version  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_role_flip_osoba ON media_role_flip(id_osoba);
CREATE INDEX IF NOT EXISTS idx_media_role_flip_schvaleno ON media_role_flip(schvaleno);

-- Diarizovaní mluvčí YouTube videí (Fáze 6c, pipeline/video_diarization.py).
-- Diarizace sama vrátí jen anonymní `speaker_label` (SPEAKER_00…) podle
-- hlasu — `id_osoba` je NULL, dokud ho ručně nenastaví
-- `tag_video_speaker.py` pro jednoho mluvčího jednoho videa. Dokud je
-- `id_osoba` NULL, `media_role_flip.py` z jeho úseků citace nestaví.
CREATE TABLE IF NOT EXISTS video_speakers (
    video_url     TEXT NOT NULL,
    speaker_label TEXT NOT NULL,
    id_osoba      TEXT,
    sample_text   TEXT NOT NULL,
    total_seconds REAL NOT NULL,
    tagged_at     TEXT,
    produced_at   TEXT NOT NULL,
    PRIMARY KEY (video_url, speaker_label)
);
CREATE INDEX IF NOT EXISTS idx_video_speakers_osoba ON video_speakers(id_osoba);

-- Cache sloučeného přepisu+diarizace pro jedno video (drahé na přepočet —
-- stažení zvuku + diarizace), `segments_json` = výstup
-- `video_diarization.merge_transcript_with_diarization`. `datum_videa` se
-- dodává ručně při `prepare_video_speakers.py` (`/youtube/info` datum
-- publikace nevrací, viz `psp/youtube_transcript.py`) — NULL, dokud ho
-- operátor nezadá, nikdy se neodhaduje.
CREATE TABLE IF NOT EXISTS video_transcript_cache (
    video_url     TEXT PRIMARY KEY,
    medium        TEXT NOT NULL,
    datum_videa   TEXT,
    segments_json TEXT NOT NULL,
    produced_at   TEXT NOT NULL
);

-- Hlasové otisky známých politiků (Fáze 6d, pipeline/voice_embedding.py) —
-- vstup pro `suggest_speakers`, jen NÁPOVĚDA operátorovi při tagování
-- diarizovaných mluvčích (`tag_video_speaker.py`), nikdy zdroj pravdy —
-- `video_speakers.id_osoba` z tohohle nikdy nečerpá přímo. Jeden vzorek na
-- politika (`build_voice_goldset.py`, přepisovatelný), z okna zvuku, které
-- si operátor sám ověřil poslechem/sledováním, ne z odhadu.
CREATE TABLE IF NOT EXISTS voice_goldset (
    id_osoba          TEXT PRIMARY KEY,
    embedding_json    TEXT NOT NULL,
    cast_id           TEXT NOT NULL,
    source_moment     TEXT NOT NULL,
    duration_seconds  REAL NOT NULL,
    produced_at       TEXT NOT NULL
);
"""

_ENGINE_SCHEMA = _FACTS_SCHEMA + _VOTING_SCHEMA + """
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
    pair_id            TEXT PRIMARY KEY,
    claim_id_a         TEXT NOT NULL,
    claim_id_b         TEXT NOT NULL,
    similarity_score   REAL NOT NULL,
    timeframe_conflict INTEGER NOT NULL DEFAULT 0,
    produced_at        TEXT NOT NULL
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
    # Bezpečná migrace pro stávající tabulky
    try:
        conn.execute("ALTER TABLE candidate_pairs ADD COLUMN timeframe_conflict INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
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


#: Anotace vyrobené `run_pipeline.py` nesou tuto předponu v `engine_version`.
#: Cokoliv jiného je ruční vstup a musí se tak i vykázat — v srpnu 2026 se do
#: `verdicts` dostalo 22 ručně napsaných "nálezů" pod skutečnými jmény, které se
#: přes `byProvenance.handAuthored = 0` tvářily jako výstup enginu.
PIPELINE_ENGINE_PREFIX = "run-pipeline"


def annotation_provenance(conn: sqlite3.Connection) -> Dict[str, int]:
    """Počty ověřených anotací podle skutečné provenience, ne podle deklarace."""
    rows = conn.execute(
        "SELECT engine_version, COUNT(*) AS n FROM verdicts "
        "WHERE proof_verified = 1 GROUP BY engine_version"
    ).fetchall()
    counts = {"engine": 0, "handAuthored": 0}
    for row in rows:
        version = row["engine_version"] or ""
        key = "engine" if version.startswith(PIPELINE_ENGINE_PREFIX) else "handAuthored"
        counts[key] += row["n"]
    return counts


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
                         claim_id_b: str, score: float,
                         timeframe_conflict: bool = False) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO candidate_pairs (pair_id, claim_id_a, claim_id_b, similarity_score, timeframe_conflict, produced_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pair_id, claim_id_a, claim_id_b, score, 1 if timeframe_conflict else 0, now_iso()),
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
