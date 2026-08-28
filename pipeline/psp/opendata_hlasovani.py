"""
Otevřená data jmenovitých hlasování PSP ČR (`psp.cz/eknih/cdrom/opendata/`).

Doplňuje `psp/opendata.py` (osoby, kluby, členství) o tři další dumpy, které
dohromady dají odpověď na otázku "o čem se hlasovalo, když tohle řekl(a)":

  * `hl-YYYYps.zip`  — `hl2025s.unl` (hlasování), `hl2025h1.unl` (jak kdo
    hlasoval), `zmatecne.unl` (zrušená hlasování), `omluvy.unl` (omluvy).
  * `schuze.zip`     — `schuze.unl` (schůze), `bod_schuze.unl` (body pořadu,
    s vazbou na sněmovní tisk).
  * `steno.zip`      — `steno.unl` (jeden řádek = jeden `turn` ve
    stenozáznamu), `rec.unl` (kdo v tom turnu mluvil a u kterého bodu).

Spojovací klíč ověřený proti reálnému korpusu (28. 8. 2026, schůze 1 a 5):

    projev (turn, kotva #rN, id_osoba)
      -> steno.unl (id_organ, schůze, turn)   -> id_steno
      -> rec.unl   (id_steno, kotva, id_osoba) -> id_bod
      -> bod_schuze.unl (id_bod)               -> id_tisk, číslo bodu
      -> hl2025s.unl (id_organ, schůze, bod)   -> všechna hlasování o bodu
      -> hl2025h1.unl (id_hlasovani, id_poslanec) -> kód hlasu

`hl2025h1.unl` slučuje "zdržel se" a "nehlasoval" do jednoho kódu `K` (ověřeno
křížovou kontrolou 200 hlasů proti HTML `hlasy.sqw?G=` — 0 neshod, viz
`psp/hlasovani.py`, které tohle rozlišení má). Kdokoli publikuje konkrétní
hlas, musí ho pro tenhle případ dověřit z HTML, ne spoléhat na `K` odsud.

`omluvy.unl` identifikuje osobu přes **`id_poslanec`**, ne `id_osoba` — jediný
z dumpů v tomhle modulu, který to dělá (ověřeno; `id_osoba` v tomhle souboru
nic nevrací).
"""

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from .client import PspClient
from .opendata import TERM_ORGAN_ID, read_unl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import now_iso  # noqa: E402

#: Syrový jednopísmenný kód z `hl2025h1.unl` -> náš `VoteValue`.
#: `K` je záměrně nejednoznačný (viz docstring modulu) a `@` slučuje
#: "nepřihlášen" a "omluven" — přesně jak to dělá `VOTE_BY_FLAG`
#: v `psp/hlasovani.py`, se kterým se tahle tabulka musí shodovat.
VOTE_CODE_MAP = {
    "A": "PRO",
    "B": "PROTI",
    "K": "ZDRZEL_SE",  # nebo NEHLASOVAL — nerozlišitelné z dumpu, viz výše
    "@": "NEPRIHLASEN",
}


# ---------------------------------------------------------------------------
# Stahování archivů
# ---------------------------------------------------------------------------

def _archive(client: PspClient, name: str) -> str:
    return client.opendata_archive(name)


def hlasovani_archive_name(rok_snemovny: int) -> str:
    """`hl-2025ps.zip` pro volební období zvolené v roce 2025."""
    return "hl-{}ps.zip".format(rok_snemovny)


# ---------------------------------------------------------------------------
# Parsery jednotlivých UNL souborů — čisté funkce, žádné I/O mimo archiv
# ---------------------------------------------------------------------------

def parse_schuze(archive_path: str, term_organ_id: str) -> Dict[str, Tuple[str, int]]:
    """`id_schuze -> (id_organ, číslo schůze)`, jen pro dané volební období."""
    out: Dict[str, Tuple[str, int]] = {}
    for cols in read_unl(archive_path, "schuze.unl"):
        if len(cols) < 3:
            continue
        id_schuze, id_organ, cislo = cols[0], cols[1], cols[2]
        if id_organ != term_organ_id:
            continue
        try:
            out[id_schuze] = (id_organ, int(cislo))
        except ValueError:
            continue
    return out


def parse_bod_schuze(archive_path: str, schuze_ids: set) -> List[Dict[str, Any]]:
    """Body pořadu schůze, jen pro `id_schuze` z `parse_schuze`."""
    out = []
    for cols in read_unl(archive_path, "bod_schuze.unl"):
        if len(cols) < 6:
            continue
        id_bod, id_schuze, id_tisk = cols[0], cols[1], cols[2]
        if id_schuze not in schuze_ids:
            continue
        bod_raw = cols[4]
        nazev = cols[5]
        tisk_ref = cols[6] if len(cols) > 6 else ""
        try:
            bod = int(bod_raw) if bod_raw else None
        except ValueError:
            bod = None
        out.append({
            "id_bod": id_bod,
            "id_schuze": id_schuze,
            "id_tisk": id_tisk or None,
            "bod": bod,
            "nazev": nazev,
            "tisk_ref": tisk_ref,
        })
    return out


def parse_steno_turns(archive_path: str, term_organ_id: str) -> Dict[str, Tuple[str, int, int]]:
    """`id_steno -> (id_organ, schůze, turn)`, jen pro dané volební období."""
    out: Dict[str, Tuple[str, int, int]] = {}
    for cols in read_unl(archive_path, "steno.unl"):
        if len(cols) < 4:
            continue
        id_steno, id_organ, schuze, turn = cols[0], cols[1], cols[2], cols[3]
        if id_organ != term_organ_id:
            continue
        try:
            out[id_steno] = (id_organ, int(schuze), int(turn))
        except ValueError:
            continue
    return out


def parse_rec(archive_path: str, steno_index: Dict[str, Tuple[str, int, int]]) -> List[Dict[str, Any]]:
    """Řečníci v jednotlivých bodech, spojeno se `steno_index` na (organ, schůze, turn)."""
    out = []
    for cols in read_unl(archive_path, "rec.unl"):
        if len(cols) < 4:
            continue
        id_steno, id_osoba, anchor_n, id_bod = cols[0], cols[1], cols[2], cols[3]
        steno = steno_index.get(id_steno)
        # `id_bod == "0"` znamená "bez konkrétního bodu pořadu" (např. obecné
        # řízení schůze mimo projednávání bodu) — string "0" je v Pythonu
        # truthy, `not id_bod` by ho tedy nezachytilo.
        if not steno or not id_bod or id_bod == "0":
            continue
        id_organ, schuze, turn = steno
        try:
            anchor = int(anchor_n)
        except ValueError:
            continue
        out.append({
            "id_organ": id_organ,
            "schuze": schuze,
            "turn": turn,
            "anchor_n": anchor,
            "id_osoba": id_osoba,
            "id_bod": id_bod,
            "druh": cols[4] if len(cols) > 4 else None,
        })
    return out


def parse_hlasovani(archive_path: str, member: str, term_organ_id: str) -> List[Dict[str, Any]]:
    """Hlasování (`hl2025s.unl`), jen pro dané volební období."""
    out = []
    for cols in read_unl(archive_path, member):
        if len(cols) < 15:
            continue
        id_hlasovani, id_organ = cols[0], cols[1]
        if id_organ != term_organ_id:
            continue
        try:
            schuze = int(cols[2])
            cislo = int(cols[3])
            bod = int(cols[4]) if cols[4] else 0
            pro = int(cols[7])
            proti = int(cols[8])
            zdrzel = int(cols[9])
            nehlasoval = int(cols[10])
            prihlaseno = int(cols[11])
            kvorum = int(cols[12])
        except ValueError:
            continue
        out.append({
            "id_hlasovani": id_hlasovani,
            "id_organ": id_organ,
            "schuze": schuze,
            "cislo": cislo,
            "bod": bod,
            "datum": cols[5],
            "cas": cols[6],
            "pro": pro,
            "proti": proti,
            "zdrzel": zdrzel,
            "nehlasoval": nehlasoval,
            "prihlaseno": prihlaseno,
            "kvorum": kvorum,
            "vysledek": cols[14],
            "nazev": cols[15] if len(cols) > 15 else "",
            "url": "https://www.psp.cz/sqw/hlasy.sqw?G={}".format(id_hlasovani),
        })
    return out


def parse_hlas_poslance(archive_path: str, member: str, hlasovani_ids: set) -> List[Tuple[str, str, str]]:
    """`(id_hlasovani, id_poslanec, kod)`, jen pro hlasování z `hlasovani_ids`."""
    out = []
    for cols in read_unl(archive_path, member):
        if len(cols) < 3:
            continue
        id_poslanec, id_hlasovani, kod = cols[0], cols[1], cols[2]
        if id_hlasovani not in hlasovani_ids:
            continue
        out.append((id_hlasovani, id_poslanec, kod))
    return out


def parse_zmatecne(archive_path: str, member: str, hlasovani_ids: set) -> set:
    out = set()
    for cols in read_unl(archive_path, member):
        if cols and cols[0] in hlasovani_ids:
            out.add(cols[0])
    return out


def parse_omluvy(archive_path: str, member: str, term_organ_id: str) -> List[Tuple[str, str, str, str, str]]:
    """`(id_organ, id_poslanec, datum, od, do)`, jen pro dané volební období."""
    out = []
    for cols in read_unl(archive_path, member):
        if len(cols) < 5:
            continue
        id_organ = cols[0]
        if id_organ != term_organ_id:
            continue
        out.append((id_organ, cols[1], cols[2], cols[3], cols[4]))
    return out


# ---------------------------------------------------------------------------
# Naplnění engine.sqlite
# ---------------------------------------------------------------------------

def populate_voting_tables(conn, client: Optional[PspClient] = None,
                            term_organ_id: int = TERM_ORGAN_ID,
                            hlasovani_archive: str = "hl-2025ps.zip") -> Dict[str, int]:
    """
    Stáhne (nebo použije z cache) `hl-*ps.zip`, `schuze.zip`, `steno.zip` a
    naplní tabulky `schuze`, `bod_schuze`, `rec_bod`, `hlasovani`,
    `hlas_poslance`, `omluva`, `zmatecne`.

    Idempotentní — pro dané `term_organ_id` nejdřív smaže staré řádky, pak
    vloží nové. Bezpečné volat opakovaně (denní refresh dumpů).
    """
    if client is None:
        client = PspClient()
    organ = str(term_organ_id)

    hl_path = _archive(client, hlasovani_archive)
    schuze_path = _archive(client, "schuze.zip")
    steno_path = _archive(client, "steno.zip")

    schuze = parse_schuze(schuze_path, organ)
    schuze_ids = set(schuze.keys())
    bod_schuze = parse_bod_schuze(schuze_path, schuze_ids)

    steno_index = parse_steno_turns(steno_path, organ)
    rec_bod = parse_rec(steno_path, steno_index)

    hlasovani = parse_hlasovani(hl_path, "hl2025s.unl", organ)
    hlasovani_ids = {h["id_hlasovani"] for h in hlasovani}
    hlas_poslance = parse_hlas_poslance(hl_path, "hl2025h1.unl", hlasovani_ids)
    zmatecne = parse_zmatecne(hl_path, "zmatecne.unl", hlasovani_ids)
    omluvy = parse_omluvy(hl_path, "omluvy.unl", organ)

    ts = now_iso()

    conn.execute("DELETE FROM schuze WHERE id_organ = ?", (organ,))
    conn.executemany(
        "INSERT INTO schuze (id_schuze, id_organ, cislo) VALUES (?, ?, ?)",
        [(sid, o, c) for sid, (o, c) in schuze.items()],
    )

    conn.execute(
        "DELETE FROM bod_schuze WHERE id_schuze IN (SELECT id_schuze FROM schuze WHERE id_organ = ?)",
        (organ,),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO bod_schuze (id_bod, id_schuze, id_tisk, bod, nazev, tisk_ref) "
        "VALUES (:id_bod, :id_schuze, :id_tisk, :bod, :nazev, :tisk_ref)",
        bod_schuze,
    )

    conn.execute("DELETE FROM rec_bod WHERE id_organ = ?", (organ,))
    conn.executemany(
        "INSERT OR REPLACE INTO rec_bod (id_organ, schuze, turn, anchor_n, id_osoba, id_bod, druh) "
        "VALUES (:id_organ, :schuze, :turn, :anchor_n, :id_osoba, :id_bod, :druh)",
        rec_bod,
    )

    conn.execute("DELETE FROM hlasovani WHERE id_organ = ?", (organ,))
    conn.executemany(
        "INSERT OR REPLACE INTO hlasovani "
        "(id_hlasovani, id_organ, schuze, cislo, bod, datum, cas, pro, proti, zdrzel, "
        " nehlasoval, prihlaseno, kvorum, vysledek, nazev, is_zmatecne, url) "
        "VALUES (:id_hlasovani, :id_organ, :schuze, :cislo, :bod, :datum, :cas, :pro, :proti, "
        " :zdrzel, :nehlasoval, :prihlaseno, :kvorum, :vysledek, :nazev, 0, :url)",
        hlasovani,
    )
    if zmatecne:
        conn.executemany(
            "UPDATE hlasovani SET is_zmatecne = 1 WHERE id_hlasovani = ?",
            [(hid,) for hid in zmatecne],
        )

    conn.execute(
        "DELETE FROM hlas_poslance WHERE id_hlasovani IN "
        "(SELECT id_hlasovani FROM hlasovani WHERE id_organ = ?)",
        (organ,),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO hlas_poslance (id_hlasovani, id_poslanec, kod) VALUES (?, ?, ?)",
        hlas_poslance,
    )

    conn.execute("DELETE FROM zmatecne WHERE id_hlasovani IN (SELECT id_hlasovani FROM hlasovani WHERE id_organ = ?)", (organ,))
    conn.executemany(
        "INSERT OR REPLACE INTO zmatecne (id_hlasovani) VALUES (?)",
        [(hid,) for hid in zmatecne],
    )

    conn.execute("DELETE FROM omluva WHERE id_organ = ?", (organ,))
    conn.executemany(
        "INSERT INTO omluva (id_organ, id_poslanec, datum, od, do_cas) VALUES (?, ?, ?, ?, ?)",
        omluvy,
    )

    conn.commit()

    return {
        "schuze": len(schuze),
        "bod_schuze": len(bod_schuze),
        "rec_bod": len(rec_bod),
        "hlasovani": len(hlasovani),
        "hlas_poslance": len(hlas_poslance),
        "zmatecne": len(zmatecne),
        "omluva": len(omluvy),
    }


# ---------------------------------------------------------------------------
# Dotazy nad naplněnými tabulkami
# ---------------------------------------------------------------------------

def find_id_bod(conn, id_organ: str, schuze: int, turn: int, anchor_n: int,
                 id_osoba: str) -> Optional[str]:
    """`(turn, kotva #rN, id_osoba)` z projevu -> `id_bod`, na kterém se hlasovalo."""
    row = conn.execute(
        "SELECT id_bod FROM rec_bod WHERE id_organ = ? AND schuze = ? AND turn = ? "
        "AND anchor_n = ? AND id_osoba = ?",
        (str(id_organ), int(schuze), int(turn), int(anchor_n), str(id_osoba)),
    ).fetchone()
    return row["id_bod"] if row else None


def bod_info(conn, id_bod: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT id_bod, id_schuze, id_tisk, bod, nazev, tisk_ref FROM bod_schuze WHERE id_bod = ?",
        (id_bod,),
    ).fetchone()
    return dict(row) if row else None


def votes_for_bod(conn, id_organ: str, schuze: int, bod: int,
                   include_zmatecne: bool = False) -> List[Dict[str, Any]]:
    """Všechna hlasování o daném bodu pořadu, seřazená podle času."""
    where = "id_organ = ? AND schuze = ? AND bod = ?"
    if not include_zmatecne:
        where += " AND is_zmatecne = 0"
    rows = conn.execute(
        "SELECT * FROM hlasovani WHERE {} ORDER BY cislo".format(where),
        (str(id_organ), int(schuze), int(bod)),
    ).fetchall()
    return [dict(r) for r in rows]


def hlas_poslance_kod(conn, id_hlasovani: str, id_poslanec: str) -> Optional[str]:
    """Syrový kód (A/B/K/@) hlasu daného poslance; `None` = v dumpu vůbec není."""
    row = conn.execute(
        "SELECT kod FROM hlas_poslance WHERE id_hlasovani = ? AND id_poslanec = ?",
        (id_hlasovani, id_poslanec),
    ).fetchone()
    return row["kod"] if row else None


def is_omluven(conn, id_organ: str, id_poslanec: str, datum_hlasovani: str, cas_hlasovani: str) -> bool:
    """
    `True`, pokud má poslanec k datu a času hlasování zaznamenanou omluvu.

    `datum_hlasovani` ve tvaru `dd.mm.yyyy` (jak ho dává `hl2025s.unl`),
    `cas_hlasovani` ve tvaru `HH:MM`. Omluvy v `omluvy.unl` jsou po dnech
    a časových oknech `od`–`do` v témže formátu.
    """
    rows = conn.execute(
        "SELECT od, do_cas FROM omluva WHERE id_organ = ? AND id_poslanec = ? AND datum = ?",
        (str(id_organ), str(id_poslanec), datum_hlasovani),
    ).fetchall()
    if not rows:
        return False
    try:
        h, m = cas_hlasovani.split(":")[:2]
        cas_min = int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return bool(rows)
    for row in rows:
        try:
            oh, om = row["od"].split(":")[:2]
            dh, dm = row["do_cas"].split(":")[:2]
            od_min = int(oh) * 60 + int(om)
            do_min = int(dh) * 60 + int(dm)
        except (ValueError, AttributeError):
            continue
        if od_min <= cas_min <= do_min:
            return True
    return False
