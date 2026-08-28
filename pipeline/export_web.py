"""
Export staženého korpusu do jednoho artefaktu pro web.

    python pipeline/export_web.py

Tohle je **jediný šev mezi pipeline a aplikací**. Web nikdy nečte soubory
z `pipeline/data/psp/` přímo — čte výhradně `src/data/psp/dataset.json`, který
vzniká tady. Až korpus přeroste do SQLite, změní se jen zdroj čtení v tomhle
souboru; aplikace o tom nebude vědět.

Co se cestou děje:

  * zahazuje se `rawText` (u většiny vystoupení je totožný s `cleanText`
    a zdvojnásoboval by velikost artefaktu),
  * dopočítá se rejstřík řečníků a klubů — web ho nesmí odvozovat sám,
    protože klub se váže k datu vystoupení, ne k dnešku,
  * doplní se hlavička `meta` s tím, **kolik vystoupení už prošlo analýzou**.
    To je klíčový údaj: bez něj rozhraní neumí odlišit „zkontrolováno a čisté"
    od „zatím nezkontrolováno" a začne tvrdit první místo druhého.
"""

import glob
import io
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import (  # noqa: E402
    analyzed_message_ids,
    annotation_provenance,
    load_annotations_for_message,
    open_engine_db,
)
from aligner import align_message, build_archive_url  # noqa: E402
from hlasovaci_rejstrik import build_debate_ledger, voting_balance  # noqa: E402
from index_vecnosti import build_index as build_index_vecnosti  # noqa: E402
from psp.build import CLUB_COLORS  # noqa: E402
from psp.client import PspClient  # noqa: E402
from psp.facts import ENGINE_SQLITE_PATH  # noqa: E402
from psp.opendata import TERM_ORGAN_ID, Registry  # noqa: E402
from scoring import compute_sci, sci_label  # noqa: E402
from verify_proof import verify_all_annotations  # noqa: E402

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(PIPELINE_DIR)
SOURCE_DIR = os.path.join(PIPELINE_DIR, "data", "psp")
TARGET_DIR = os.path.join(ROOT, "src", "data", "psp")
TARGET_JSON = os.path.join(TARGET_DIR, "dataset.json")
HLIDAC_PROFILES_FILE = os.path.join(PIPELINE_DIR, "data", "hlidac_profiles.json")
VIDEO_RECORDINGS_FILE = os.path.join(TARGET_DIR, "videoRecordings.json")

STENO_INDEX = "https://www.psp.cz/eknih/2025ps/stenprot/index.htm"
PROFILE_URL = "https://www.psp.cz/sqw/detail.sqw?id={}"

#: Pole, která do webu neposíláme. `rawText` je duplicita `cleanText`.
DROP_MESSAGE_FIELDS = ("rawText",)


def slugify(value: str) -> str:
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c)
    )
    out = []
    for char in stripped.lower():
        out.append(char if char.isalnum() and char.isascii() else "-")
    return "-".join(part for part in "".join(out).split("-") if part)


def politician_slug(name: str) -> str:
    """
    Slug z **celého** jména, ne jen z příjmení.

    V korpusu jsou dvě Kovářové a dva Zůnové; slug z příjmení by je sloučil do
    jednoho profilu a jeden by tiše přepsal druhého.
    """
    return slugify(name)


def load_debates() -> List[Dict[str, Any]]:
    debates: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(SOURCE_DIR, "*.json"))):
        with io.open(path, encoding="utf-8") as handle:
            debates.extend(json.load(handle))
    return debates


def slim_message(message: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in message.items() if k not in DROP_MESSAGE_FIELDS}


def build_politicians(debates: List[Dict[str, Any]], hlidac_profiles: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Rejstřík řečníků odvozený z korpusu.

    Univerzum poslanců nesmí být ruční seznam – musí to být přesně ti, kdo
    v korpusu opravdu mluvili, jinak profily nesedí na vystoupení.
    """
    people: Dict[str, Dict[str, Any]] = {}
    for debate in debates:
        for message in debate["messages"]:
            name = message["speaker"]
            record = people.setdefault(name, {
                "name": name,
                "slug": politician_slug(name),
                "idOsoba": message["source"]["idOsoba"],
                "party": "",
                "roles": {},
                "speechCount": 0,
                "lastSpokeAt": "",
            })
            record["speechCount"] += 1
            record["roles"][message["role"]] = record["roles"].get(message["role"], 0) + 1
            # Klub bereme z nejnovějšího vystoupení – u přeběhlíka je to ten
            # současný, u ministra bez mandátu zůstane prázdný.
            when = message["date"]
            if when >= record["lastSpokeAt"]:
                record["lastSpokeAt"] = when
                if message.get("party"):
                    record["party"] = message["party"]

    profiles = hlidac_profiles or {}
    politicians = []
    for record in people.values():
        roles = record.pop("roles")
        record["role"] = max(roles.items(), key=lambda kv: (kv[1], kv[0]))[0]
        record["profileUrl"] = PROFILE_URL.format(record["idOsoba"])
        hlidac_info = profiles.get(record["name"])
        if hlidac_info:
            record["hlidacStatu"] = hlidac_info
        politicians.append(record)

    # Kolizi celého jména (dvě osoby stejného jména) rozliší id ze Sněmovny.
    seen: Dict[str, List[Dict[str, Any]]] = {}
    for politician in politicians:
        seen.setdefault(politician["slug"], []).append(politician)
    for slug, group in seen.items():
        if len(group) > 1:
            for politician in group:
                politician["slug"] = "{}-{}".format(slug, politician["idOsoba"])

    return sorted(politicians, key=lambda p: p["name"])


def verify_slovo_cin(conn, registry) -> Dict[str, Any]:
    """
    Důkazní brána Fáze 3 — každou položku znovu odvodí z otevřených dat.

    Nestačí, že položku někdo jednou ověřil při jejím vzniku: `investigator.py`
    v srpnu 2026 ukázal, že se ověření dá obejít jedním `if`. Proto se před
    každým exportem znovu ptáme dat:

      1. hlasování existuje, patří do tohoto období a NENÍ zmatečné,
      2. poslanec u něj má záznam a jeho hlas se shoduje s uloženým,
      3. shoda/neshoda vychází z hlasu, ne z toho, co je uložené.

    Neprojde-li položka, `overeno` se nastaví na 0 a na web se nedostane.
    """
    ok = 0
    zamitnuto: List[str] = []
    rows = conn.execute("SELECT id, id_osoba, id_hlasovani, hlas, postoj, shoda, zaznam_json FROM slovo_cin").fetchall()

    for row in rows:
        duvod = None
        ballot = conn.execute(
            "SELECT id_organ, is_zmatecne FROM hlasovani WHERE id_hlasovani = ?",
            (row["id_hlasovani"],),
        ).fetchone()

        if not ballot:
            duvod = "hlasování {} není v otevřených datech".format(row["id_hlasovani"])
        elif ballot["is_zmatecne"]:
            duvod = "hlasování {} je zmatečné".format(row["id_hlasovani"])
        else:
            id_poslanec = registry.deputy_id(row["id_osoba"]) if registry else None
            if not id_poslanec:
                duvod = "poslanec {} nemá v tomto období mandát".format(row["id_osoba"])
            else:
                hlas_row = conn.execute(
                    "SELECT kod FROM hlas_poslance WHERE id_hlasovani = ? AND id_poslanec = ?",
                    (row["id_hlasovani"], id_poslanec),
                ).fetchone()
                if not hlas_row:
                    duvod = "poslanec {} u hlasování {} není veden".format(
                        row["id_osoba"], row["id_hlasovani"])
                else:
                    # Dump slučuje "zdržel se" a "nehlasoval" do K, takže se
                    # proti němu dá ověřit jen směr PRO/PROTI — přesně ten ale
                    # nese celé tvrzení o shodě.
                    ocekavano = {"A": "PRO", "B": "PROTI"}.get(hlas_row["kod"])
                    if ocekavano and ocekavano != row["hlas"]:
                        duvod = "hlas nesouhlasí: uloženo {}, otevřená data {}".format(
                            row["hlas"], ocekavano)
                    elif not ocekavano and row["hlas"] in ("PRO", "PROTI"):
                        duvod = "uloženo {}, otevřená data ale hlásí {}".format(
                            row["hlas"], hlas_row["kod"])

        if duvod is None:
            ocekavana_shoda = (
                "SHODA" if row["hlas"] == row["postoj"]
                else "NESHODA" if row["hlas"] in ("PRO", "PROTI")
                else "NEHLASOVAL"
            )
            if ocekavana_shoda != row["shoda"]:
                duvod = "shoda nesedí: uloženo {}, přepočteno {}".format(
                    row["shoda"], ocekavana_shoda)

        conn.execute("UPDATE slovo_cin SET overeno = ? WHERE id = ?",
                     (0 if duvod else 1, row["id"]))
        if duvod:
            zamitnuto.append("{}: {}".format(row["id"], duvod))
        else:
            ok += 1

    conn.commit()
    return {"ok": ok, "zamitnuto": zamitnuto}


def load_slovo_cin(conn) -> List[Dict[str, Any]]:
    """Ověřené položky Slovo vs. Čin pro web."""
    rows = conn.execute(
        "SELECT zaznam_json FROM slovo_cin WHERE overeno = 1 ORDER BY id"
    ).fetchall()
    return [json.loads(row["zaznam_json"]) for row in rows]


def verify_programova_vernost(conn, registry) -> Dict[str, Any]:
    """
    Důkazní brána Fáze 4 — každou položku znovu odvodí z uloženého zdroje.

    Jiné riziko než `verify_slovo_cin`: tam model určuje HLAS (ověřitelný
    proti `hlas_poslance`), tady model určuje SPÁROVÁNÍ (žádná tabulka
    otevřených dat ho nepotvrdí). Brána proto kontroluje, co ověřit jde:

      1. citace pořád leží v uloženém textu kapitoly (`programove_kapitoly`)
         — kdyby vláda stránku upravila, ingesce se musí spustit znovu,
      2. hlasování existuje a NENÍ zmatečné,
      3. poměr hlasů klubů se přepočítá znovu, ne jen přebírá z uloženého JSON.

    Samotné spárování „tenhle tisk plní tenhle slib" brána neověří — to je
    posouzení, ne fakt; jeho pojistka je nezávislý přezkum při vzniku
    (`programova_vernost.challenge_pairing`), ne tahle brána.
    """
    from datetime import datetime as _datetime

    from psp.opendata import COALITION_CLUBS_AFTER_SWITCH
    from slovo_cin import klub_tally_for_ballot

    ok = 0
    zamitnuto: List[str] = []
    rows = conn.execute(
        "SELECT pv.id AS id, pv.id_hlasovani AS id_hlasovani, pv.zaznam_json AS zaznam_json, "
        "z.kapitola_id AS kapitola_id, z.citace AS citace "
        "FROM programova_vernost pv JOIN programove_zavazky z ON z.id = pv.zavazek_id"
    ).fetchall()

    for row in rows:
        duvod = None
        kapitola = conn.execute(
            "SELECT text FROM programove_kapitoly WHERE id = ?", (row["kapitola_id"],)
        ).fetchone()
        ballot = conn.execute(
            "SELECT is_zmatecne, datum FROM hlasovani WHERE id_hlasovani = ?",
            (row["id_hlasovani"],),
        ).fetchone()

        if not kapitola:
            duvod = "kapitola {} není uložená".format(row["kapitola_id"])
        elif row["citace"] not in kapitola["text"]:
            duvod = "citace už neleží v uloženém textu kapitoly {}".format(row["kapitola_id"])
        elif not ballot:
            duvod = "hlasování {} není v otevřených datech".format(row["id_hlasovani"])
        elif ballot["is_zmatecne"]:
            duvod = "hlasování {} je zmatečné".format(row["id_hlasovani"])

        if duvod is None:
            when = None
            try:
                when = _datetime.strptime(ballot["datum"], "%d.%m.%Y").date()
            except (ValueError, TypeError):
                pass
            prepocteno = {
                klub: klub_tally_for_ballot(conn, registry, row["id_hlasovani"], klub, when)
                for klub in sorted(COALITION_CLUBS_AFTER_SWITCH - {"ANO"})
            } if when and registry else {}
            zaznam = json.loads(row["zaznam_json"])
            if prepocteno != zaznam.get("kluby"):
                duvod = "poměr hlasů klubů nesedí s přepočtem"

        conn.execute("UPDATE programova_vernost SET overeno = ? WHERE id = ?",
                     (0 if duvod else 1, row["id"]))
        if duvod:
            zamitnuto.append("{}: {}".format(row["id"], duvod))
        else:
            ok += 1

    conn.commit()
    return {"ok": ok, "zamitnuto": zamitnuto}


def load_programova_vernost(conn) -> List[Dict[str, Any]]:
    """Ověřené položky Programové věrnosti pro web."""
    rows = conn.execute(
        "SELECT zaznam_json FROM programova_vernost WHERE overeno = 1 ORDER BY id"
    ).fetchall()
    return [json.loads(row["zaznam_json"]) for row in rows]


def verify_media_role_flip(conn, registry) -> Dict[str, Any]:
    """
    Důkazní brána Fáze 6b — jako `verify_slovo_cin`, plus druhá podmínka
    navíc: `schvaleno`.

    Na rozdíl od `slovo_cin`/`programova_vernost` NENÍ zdroj citace oficiální
    záznam (novinový článek, ne stenozáznam) — strojová brána proto ověří jen
    to, co jde: hlas v `hlas_poslance`, hlasování mimo `zmatecne`, přepočtená
    shoda. Neověří (a nemůže) přesnost novinářovy citace ani kontext — to
    zaručuje `schvaleno`, které nastavuje výhradně `promote_media_lead.py`
    poté, co si operátor přečetl `zdroj_url` sám. Obě podmínky se musí
    potkat, jinak se položka nevyexportuje.
    """
    ok = 0
    zamitnuto: List[str] = []
    rows = conn.execute(
        "SELECT id, id_osoba, id_hlasovani, hlas, postoj, shoda, schvaleno, zaznam_json "
        "FROM media_role_flip"
    ).fetchall()

    for row in rows:
        duvod = None
        if not row["schvaleno"]:
            duvod = "nebylo schváleno operátorem"
        else:
            ballot = conn.execute(
                "SELECT id_organ, is_zmatecne FROM hlasovani WHERE id_hlasovani = ?",
                (row["id_hlasovani"],),
            ).fetchone()
            if not ballot:
                duvod = "hlasování {} není v otevřených datech".format(row["id_hlasovani"])
            elif ballot["is_zmatecne"]:
                duvod = "hlasování {} je zmatečné".format(row["id_hlasovani"])
            else:
                id_poslanec = registry.deputy_id(row["id_osoba"]) if registry else None
                if not id_poslanec:
                    duvod = "poslanec {} nemá v tomto období mandát".format(row["id_osoba"])
                else:
                    hlas_row = conn.execute(
                        "SELECT kod FROM hlas_poslance WHERE id_hlasovani = ? AND id_poslanec = ?",
                        (row["id_hlasovani"], id_poslanec),
                    ).fetchone()
                    if not hlas_row:
                        duvod = "poslanec {} u hlasování {} není veden".format(
                            row["id_osoba"], row["id_hlasovani"])
                    else:
                        ocekavano = {"A": "PRO", "B": "PROTI"}.get(hlas_row["kod"])
                        if ocekavano and ocekavano != row["hlas"]:
                            duvod = "hlas nesouhlasí: uloženo {}, otevřená data {}".format(
                                row["hlas"], ocekavano)
                        elif not ocekavano and row["hlas"] in ("PRO", "PROTI"):
                            duvod = "uloženo {}, otevřená data ale hlásí {}".format(
                                row["hlas"], hlas_row["kod"])

            if duvod is None:
                ocekavana_shoda = (
                    "SHODA" if row["hlas"] == row["postoj"]
                    else "NESHODA" if row["hlas"] in ("PRO", "PROTI")
                    else "NEHLASOVAL"
                )
                if ocekavana_shoda != row["shoda"]:
                    duvod = "shoda nesedí: uloženo {}, přepočteno {}".format(
                        row["shoda"], ocekavana_shoda)

        conn.execute("UPDATE media_role_flip SET overeno = ? WHERE id = ?",
                     (0 if duvod else 1, row["id"]))
        if duvod:
            zamitnuto.append("{}: {}".format(row["id"], duvod))
        else:
            ok += 1

    conn.commit()
    return {"ok": ok, "zamitnuto": zamitnuto}


def load_media_role_flip(conn) -> List[Dict[str, Any]]:
    """Schválené A znovu ověřené leady rolového obratu pro web."""
    rows = conn.execute(
        "SELECT zaznam_json, schvaleno_at FROM media_role_flip "
        "WHERE schvaleno = 1 AND overeno = 1 ORDER BY schvaleno_at DESC"
    ).fetchall()
    out = []
    for row in rows:
        zaznam = json.loads(row["zaznam_json"])
        zaznam["schvalenoAt"] = row["schvaleno_at"]
        out.append(zaznam)
    return out


def build_sci_index(engine_conn, msg_to_speaker: Optional[Dict[str, str]] = None) -> Dict[str, Dict]:
    """
    Spočítá Index konzistence poslance (SCI) pro každého poslance.

    Čte přímo z engine.sqlite:
      - `claims`: počet výroků typu STANCE_COMMITMENT na poslance (= jmenovatel).
      - `verdicts`: composition score aktivních rozporů (PUBLISHED + CONTEXT_DEV).

    Vrátí slovník { idOsoba: { sci, sciLabel, contradictionCount, commitmentCount } }.
    """
    if not engine_conn:
        return {}

    import json as _json

    # Počet STANCE_COMMITMENT claimů na poslance
    commitment_rows = engine_conn.execute(
        "SELECT claim_json FROM claims"
    ).fetchall()

    commitments_per_speaker: Dict[str, int] = {}
    for (cj,) in commitment_rows:
        try:
            c = _json.loads(cj)
            cat = c.get("claimCategory") or c.get("claim_category", "")
            if cat != "STANCE_COMMITMENT":
                continue
            speaker_id = str(c.get("speakerIdOsoba") or "")
            if speaker_id:
                commitments_per_speaker[speaker_id] = commitments_per_speaker.get(speaker_id, 0) + 1
        except Exception:
            continue

    # Conviction scores z verdiktů (PUBLISHED + CONTEXT_DEVELOPMENT)
    verdict_rows = engine_conn.execute(
        "SELECT message_id, confidence_score FROM verdicts "
        "WHERE presentation_tier IN ('PUBLISHED', 'CONTEXT_DEVELOPMENT')"
    ).fetchall()

    scores_per_speaker: Dict[str, list] = {}
    for (mid, score) in verdict_rows:
        sid = (msg_to_speaker or {}).get(mid)
        if not sid:
            crow = engine_conn.execute(
                "SELECT claim_json FROM claims WHERE message_id = ? LIMIT 1", (mid,)
            ).fetchone()
            if crow:
                try:
                    c = _json.loads(crow[0])
                    sid = str(c.get("speakerIdOsoba") or "")
                except Exception:
                    pass
        if sid and score is not None:
            scores_per_speaker.setdefault(sid, []).append(float(score))

    result: Dict[str, Dict] = {}
    all_speakers = set(commitments_per_speaker) | set(scores_per_speaker)
    for sid in all_speakers:
        n = commitments_per_speaker.get(sid, 0)
        scores = scores_per_speaker.get(sid, [])
        sci = compute_sci(n, scores)
        result[sid] = {
            "sci": sci,
            "sciLabel": sci_label(sci),
            "contradictionCount": len(scores),
            "commitmentCount": n,
        }
    return result


def build_parties(politicians: List[Dict[str, Any]], registry: Registry) -> List[Dict[str, Any]]:
    used = sorted({p["party"] for p in politicians if p["party"]})
    parties = []
    for zkratka in used:
        party_politicians = [p for p in politicians if p.get("party") == zkratka]
        party_scis = [
            p["stanceConsistency"]["sci"]
            for p in party_politicians
            if "stanceConsistency" in p and p["stanceConsistency"].get("sci") is not None
        ]
        avg_sci = round(sum(party_scis) / len(party_scis), 4) if party_scis else 1.0

        parties.append({
            "name": zkratka,
            "fullName": registry.club_full_name(zkratka) or zkratka,
            "color": CLUB_COLORS.get(zkratka, "#64748B"),
            "averageSci": avg_sci,
            "averageSciLabel": sci_label(avg_sci),
            "deputyCount": len(party_politicians),
        })
    return parties


def main() -> int:
    debates = load_debates()
    if not debates:
        print("V {} nejsou žádná stažená data. Spusť nejdřív pipeline/fetch_psp.py.".format(
            SOURCE_DIR), file=sys.stderr)
        return 1

    for debate in debates:
        debate["messages"] = [slim_message(m) for m in debate["messages"]]

    # ---------- Fáze C: anotace z engine.sqlite, ne z korpusových souborů ----------
    # Korpusové JSON soubory nesou pouze text a metadata — žádné `annotations`.
    # Zdrojem anotací je výhradně engine.sqlite (verdikty s proof_verified=1).
    # Pokud soubor neexistuje (engine ještě neběžel), přeskočíme prázdnou DB.
    engine_conn = None
    engine_analyzed_ids: set = set()
    # Skutečná provenience publikovaných anotací — kdo verdikt vyrobil, ne kdo
    # tvrdí, že ho vyrobil. Viz `db.annotation_provenance`: srpen 2026 ukázal,
    # že ruční vstup (investigator.py) se dal vydávat za `engine` natvrdo
    # napsanou nulou v `handAuthored`.
    provenance = {"engine": 0, "handAuthored": 0}
    if os.path.exists(ENGINE_SQLITE_PATH):
        engine_conn = open_engine_db(ENGINE_SQLITE_PATH)
        engine_analyzed_ids = analyzed_message_ids(engine_conn)
        provenance = annotation_provenance(engine_conn)

    hlidac_profiles = {}
    if os.path.exists(HLIDAC_PROFILES_FILE):
        try:
            with io.open(HLIDAC_PROFILES_FILE, "r", encoding="utf-8") as handle:
                hlidac_profiles = json.load(handle)
        except Exception:
            hlidac_profiles = {}

    video_recordings = {}
    if os.path.exists(VIDEO_RECORDINGS_FILE):
        try:
            with io.open(VIDEO_RECORDINGS_FILE, "r", encoding="utf-8") as handle:
                video_recordings = json.load(handle)
        except Exception:
            video_recordings = {}

    tisky_registry = None
    try:
        from psp.tisky import TiskyRegistry
        tisky_registry = TiskyRegistry.load()
    except Exception:
        tisky_registry = None

    # Hlasovací rejstřík (Fáze 2) — hlasování o bodu pořadu, ke kterému
    # rozprava patří. Vyžaduje naplněné tabulky z `psp/opendata_hlasovani.py`;
    # bez nich (nebo bez rejstříku osob) se rozpravy exportují beze změny.
    registry = None
    try:
        registry = Registry.load(PspClient())
    except Exception:
        registry = None

    for debate in debates:
        tisk_info = None
        if tisky_registry and debate.get("title"):
            tisk_info = tisky_registry.parse_debate_tisk(debate.get("title", ""))
            if tisk_info:
                debate["tisk"] = tisk_info

        if engine_conn is not None and registry is not None:
            try:
                ledger = build_debate_ledger(
                    engine_conn, registry, debate, str(TERM_ORGAN_ID),
                    faze=(tisk_info or {}).get("faze"),
                )
            except Exception:
                ledger = None
            if ledger and ledger.get("hlasovani"):
                debate["bod"] = ledger["bod"]
                debate["hlasovani"] = ledger["hlasovani"]
                debate["hlasyRecniku"] = ledger["hlasyRecniku"]

        rec = video_recordings.get(debate.get("debateId"))
        cast_id = rec.get("pspCastId") if rec else None
        stream_start = rec.get("streamStartedAt") if rec else None

        for msg in debate["messages"]:
            mid = msg["messageId"]
            if engine_conn:
                anns = load_annotations_for_message(engine_conn, mid)
                msg["annotations"] = anns
                msg["hasAnomalies"] = len(anns) > 0
                if mid in engine_analyzed_ids:
                    msg["analyzedAt"] = msg.get("analyzedAt") or "engine"
            else:
                msg.setdefault("annotations", [])
                msg.setdefault("hasAnomalies", False)

            # Doplnit media a mediaEvidence serverově přes aligner.py
            if cast_id and stream_start:
                aligned = align_message(msg, cast_id, stream_start)
                msg["media"] = aligned.get("media")
                msg["annotations"] = aligned.get("annotations", [])

        if cast_id and stream_start and not debate.get("media"):
            debate["media"] = {
                "pspCastId": cast_id,
                "speechStartSeconds": 0,
                "archiveUrl": build_archive_url(cast_id),
                "alignment": "OFFSET_SYNC",
                "streamStartedAt": stream_start,
            }

    # ---------- Důkazní brána (Fáze B) ----------
    # Ověří, že každá anotace z engine.sqlite má doložení ověřitelné na zdroji.
    # proof_verified=1 v engine.sqlite znamená, že verify_proof.py již prošlo
    # v run_pipeline.py — tady je to pojistná kontrola při každém exportu.
    all_annotations = [
        ann
        for debate in debates
        for msg in debate["messages"]
        for ann in msg.get("annotations", [])
    ]
    if all_annotations:
        client = PspClient()
        def _label(ann):
            return ann.get("id") or ann.get("shortBadgeLabel") or "?"
        failures = verify_all_annotations(all_annotations, client, label_fn=_label)
        if failures:
            print("=== DŮKAZNÍ BRÁNA: export zastaven ===", file=sys.stderr)
            for failure_msg in failures:
                print("  [BRÁNA] {}".format(failure_msg), file=sys.stderr)
            print(
                "{} anotaci/í neprošlo ověřením.".format(len(failures)),
                file=sys.stderr,
            )
            return 1

    politicians = build_politicians(debates, hlidac_profiles)

    # SCI index — zapéct do profilů před sestavením stran, aby šel spočítat průměr strany
    speaker_to_id = {p["name"]: str(p.get("idOsoba", "")) for p in politicians}
    msg_to_speaker = {}
    for deb in debates:
        for m in deb.get("messages", []):
            sid = str(m.get("source", {}).get("idOsoba") or "") or speaker_to_id.get(m.get("speaker", ""), "")
            if sid:
                msg_to_speaker[m["messageId"]] = sid

    sci_index = build_sci_index(engine_conn, msg_to_speaker)
    for politician in politicians:
        sid = str(politician.get("idOsoba", ""))
        if sid in sci_index:
            politician["stanceConsistency"] = sci_index[sid]
        # Hlasovací bilance (Fáze 2) — počitatelná veličina z otevřených dat,
        # ne odhad modelu. Chybí u členů vlády bez poslaneckého mandátu, kteří
        # v `poslanec.unl` nemají `id_poslanec`.
        if engine_conn is not None and registry is not None:
            try:
                balance = voting_balance(engine_conn, registry, sid, str(TERM_ORGAN_ID))
            except Exception:
                balance = None
            if balance:
                politician["hlasovaciBilance"] = balance

    parties = build_parties(politicians, registry)
    party_averages = {p["name"]: p["averageSci"] for p in parties}

    # Doplnit k poslaneckému profilu benchmark vůči průměru jeho strany
    for politician in politicians:
        if "stanceConsistency" in politician:
            p_sci = politician["stanceConsistency"].get("sci", 1.0)
            pty = politician.get("party", "")
            pty_avg = party_averages.get(pty, 1.0)
            politician["stanceConsistency"]["partyAverageSci"] = pty_avg
            politician["stanceConsistency"]["sciVsPartyDelta"] = round(p_sci - pty_avg, 4)

    # Index věcnosti (Fáze 5) — žádné volání modelu, jen počitatelné veličiny
    # z otevřených dat (poslanecké návrhy zákonů) a ze staženého vzorku
    # stenozáznamů (rozklad délky vystoupení). Viz `index_vecnosti.py`.
    try:
        index_vecnosti_by_person = build_index_vecnosti(
            PspClient(), debates, [str(p.get("idOsoba", "")) for p in politicians],
            id_organ=str(TERM_ORGAN_ID),
        )
    except Exception:
        index_vecnosti_by_person = {}
    for politician in politicians:
        sid = str(politician.get("idOsoba", ""))
        if sid in index_vecnosti_by_person:
            politician["indexVecnosti"] = index_vecnosti_by_person[sid]

    messages = [m for d in debates for m in d["messages"]]
    # `analyzedAt` je nastaven pro každé vystoupení, nad kterým engine extrahoval
    # tvrzení (i ta, kde nenašel žádný rozpor). Čteme z engine_analyzed_ids, ne
    # z pole v korpusovém JSON — to je po Fázi A prázdné a engine ho neplní.
    analyzed = [m for m in messages if m.get("analyzedAt")]

    days = sorted({(d["sessionNumber"], d["date"]) for d in debates})

    # Kolik dnů s hlasováním má CELÉ volební období (z kompletního dumpu
    # `hl-2025ps.zip`, nezávisle na tom, kolik jednacích dnů jsme stáhli
    # textem) — jmenovatel pro poctivé "vzorek N z M" u Indexu věcnosti.
    hlasovani_dnu_celkem = None
    if engine_conn is not None:
        try:
            hlasovani_dnu_celkem = engine_conn.execute(
                "SELECT COUNT(DISTINCT datum) FROM hlasovani WHERE id_organ = ?",
                (str(TERM_ORGAN_ID),),
            ).fetchone()[0]
        except Exception:
            hlasovani_dnu_celkem = None

    dataset = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "source": STENO_INDEX,
            "term": debates[0]["term"],
            "chamber": debates[0]["chamber"],
            "sittingDays": [{"sessionNumber": s, "date": d} for s, d in days],
            "hlasovaniDnuCelkem": hlasovani_dnu_celkem,
            "debateCount": len(debates),
            "messageCount": len(messages),
            "analyzedMessageCount": len(analyzed),
            "annotationCount": sum(len(m["annotations"]) for m in messages),
            "politicianCount": len(politicians),
            # Rozpad podle skutečné provenience z `verdicts.engine_version`
            # (`db.annotation_provenance`), ne podle toho, co si o sobě
            # verdikt tvrdí. `engine` = vyrobeno `run_pipeline.py` /
            # `slovo_cin.py`; `handAuthored` = cokoliv jiného ověřeného.
            "byProvenance": provenance,
        },
        "parties": parties,
        "politicians": politicians,
        "debates": debates,
    }

    # Fáze 3 — Slovo vs. Čin. Důkazní brána běží při KAŽDÉM exportu a znovu
    # odvozuje každou položku z otevřených dat; co neprojde, se nerenderuje.
    slovo_cin: List[Dict[str, Any]] = []
    if engine_conn is not None:
        gate = verify_slovo_cin(engine_conn, registry)
        slovo_cin = load_slovo_cin(engine_conn)
        print("  Slovo vs. Čin: {} ověřeno, {} zamítnuto".format(
            gate["ok"], len(gate["zamitnuto"])))
        for duvod in gate["zamitnuto"][:10]:
            print("    [ZAMÍTNUTO] {}".format(duvod))
    dataset["slovoCin"] = slovo_cin
    dataset["meta"]["slovoCinCount"] = len(slovo_cin)
    dataset["meta"]["slovoCinNeshod"] = sum(
        1 for z in slovo_cin if z.get("shoda") == "NESHODA")

    # Fáze 4 — Programová věrnost. Stejná disciplína: brána běží při KAŽDÉM
    # exportu, co neprojde, se nerenderuje.
    programova_vernost: List[Dict[str, Any]] = []
    if engine_conn is not None:
        pv_gate = verify_programova_vernost(engine_conn, registry)
        programova_vernost = load_programova_vernost(engine_conn)
        print("  Programová věrnost: {} ověřeno, {} zamítnuto".format(
            pv_gate["ok"], len(pv_gate["zamitnuto"])))
        for duvod in pv_gate["zamitnuto"][:10]:
            print("    [ZAMÍTNUTO] {}".format(duvod))
    dataset["programovaVernost"] = programova_vernost
    dataset["meta"]["programovaVernostCount"] = len(programova_vernost)

    # Fáze 6b — Rolový obrat v médiích. Dvojí podmínka: `schvaleno` (ruční,
    # jednou nastavené `promote_media_lead.py`) A `overeno` (strojové, znovu
    # při KAŽDÉM exportu) — chybí-li jedna z nich, položka se nerenderuje.
    media_role_flip: List[Dict[str, Any]] = []
    if engine_conn is not None:
        mrf_gate = verify_media_role_flip(engine_conn, registry)
        media_role_flip = load_media_role_flip(engine_conn)
        print("  Rolový obrat: {} ověřeno, {} zamítnuto".format(
            mrf_gate["ok"], len(mrf_gate["zamitnuto"])))
        for duvod in mrf_gate["zamitnuto"][:10]:
            print("    [ZAMÍTNUTO] {}".format(duvod))
    dataset["rolovyObrat"] = media_role_flip
    dataset["meta"]["rolovyObratCount"] = len(media_role_flip)

    os.makedirs(TARGET_DIR, exist_ok=True)
    with io.open(TARGET_JSON, "w", encoding="utf-8") as handle:
        json.dump(dataset, handle, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(TARGET_JSON)
    print("zapsáno: {}".format(TARGET_JSON))
    print("  {} rozprav, {} vystoupení, {} řečníků, {} klubů".format(
        len(debates), len(messages), len(politicians), len(parties)))
    print("  analyzováno: {} z {} vystoupení, {} značek".format(
        len(analyzed), len(messages), dataset["meta"]["annotationCount"]))
    print("  Slovo vs. Čin: {} položek ({} neshod)".format(
        dataset["meta"]["slovoCinCount"], dataset["meta"]["slovoCinNeshod"]))
    print("  Programová věrnost: {} položek".format(dataset["meta"]["programovaVernostCount"]))
    print("  Rolový obrat: {} položek".format(dataset["meta"]["rolovyObratCount"]))
    print("  Index věcnosti: {} poslanců, vzorek {} z {} dnů s hlasováním".format(
        len(index_vecnosti_by_person), len(days), hlasovani_dnu_celkem or "?"))
    print("  velikost: {:.1f} MB".format(size / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
