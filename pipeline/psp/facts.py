"""
Temporální model faktů — deterministická páteř enginu (Fáze 2a).

Zobecňuje vzor, který v `psp/opendata.py` už existuje pro jednu jedinou věc
(`Registry._memberships` + `club_at()`), na libovolný fakt s platností v
čase: členství v klubu, odevzdaný hlas, časem i ministerský post nebo stav
tisku, jakmile pro ně vznikne scraper. Dokud fakt platí, `valid_to` je
`None`; `VOTE_CAST` je bodová událost, takže má `valid_from == valid_to`.

Účel: jakmile `VOTE_MISMATCH` nebo číselná lež jde ověřit dotazem sem, o
tom rozhoduje SQL, ne odhad jazykového modelu. Úložiště je SQLite se sloupci
`valid_from`/`valid_to` — žádná samostatná grafová databáze, jak stanovil
schválený plán.

    from psp.facts import FactStore, facts_from_registry, facts_from_ballot

    store = FactStore.open(path)
    store.add_many(facts_from_registry(registry, source_url, recorded_at))
    store.add_many(facts_from_ballot(ballot, recorded_at))
    store.fact_at("6987", "CLUB_MEMBERSHIP", date(2026, 3, 1))
    store.fact_for_object("6987", "VOTE_CAST", "87115")

`MINISTERIAL_POST`, `BILL_STATUS` a `ECONOMIC_INDICATOR_VALUE` jsou v
`PREDICATES` připravené schématem, ale zatím nemají producenta — v
repozitáři není scraper, který by je uměl naplnit reálnými daty, a
vymýšlet si strukturu `zarazeni.unl` pro ministerské funkce bez ověření by
znamenalo hádat. Až takový scraper vznikne, napojí se sem stejným způsobem
jako `facts_from_registry`/`facts_from_ballot`.
"""

import os
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional

#: Cesta k trvalému SQLite úložišti faktů. Sdílí ho `verify_proof.py`,
#: `run_pipeline.py` (Fáze C) a `eval_gold.py` (Fáze D). Naplňuje se
#: postupně při zpracování schůzí — fakta vydrží mezi spuštěními.
#: `psp_verify.py` záměrně používá `:memory:` (ověřuje jen aktuální den),
#: takže tuhle konstantu netáhne.
ENGINE_SQLITE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "engine.sqlite",
)

SUBJECT_TYPES = ("POLITICIAN", "CLUB", "BILL", "BALLOT", "INDICATOR")
PREDICATES = (
    "CLUB_MEMBERSHIP",
    "MINISTERIAL_POST",
    "VOTE_CAST",
    "BILL_STATUS",
    "ECONOMIC_INDICATOR_VALUE",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_type TEXT,
    object_id TEXT,
    literal_value TEXT,
    valid_from TEXT,
    valid_to TEXT,
    source_url TEXT NOT NULL,
    source_dataset TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_subject_predicate ON facts(subject_id, predicate);
CREATE INDEX IF NOT EXISTS idx_facts_object ON facts(predicate, object_id);
"""

_COLUMNS = (
    "fact_id", "subject_type", "subject_id", "predicate", "object_type",
    "object_id", "literal_value", "valid_from", "valid_to", "source_url",
    "source_dataset", "recorded_at",
)


@dataclass
class Fact:
    fact_id: str
    subject_type: str
    subject_id: str
    predicate: str
    object_type: Optional[str]
    object_id: Optional[str]
    literal_value: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    source_url: str
    source_dataset: str
    recorded_at: str

    def as_row(self):
        return tuple(getattr(self, col) for col in _COLUMNS)


def make_fact_id(predicate: str, subject_id: str, object_id: Optional[str], valid_from: Optional[str]) -> str:
    """
    Stabilní klíč pro `INSERT OR REPLACE` — opětovné zpracování téhož
    jednacího dne nebo téhož `poslanci.zip` fakt jen přepíše, nezdvojí.
    """
    return "{}:{}:{}:{}".format(predicate, subject_id, object_id or "-", valid_from or "-")


def _row_to_fact(row: sqlite3.Row) -> Fact:
    return Fact(**{col: row[col] for col in _COLUMNS})


class FactStore:
    """Tenká obálka nad SQLite s dotazy `fact_at` / `fact_for_object`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    @classmethod
    def open(cls, path: str) -> "FactStore":
        """`path` může být i `:memory:` pro testy."""
        return cls(sqlite3.connect(path))

    def add(self, fact: Fact) -> None:
        placeholders = ", ".join("?" for _ in _COLUMNS)
        self.conn.execute(
            "INSERT OR REPLACE INTO facts ({}) VALUES ({})".format(", ".join(_COLUMNS), placeholders),
            fact.as_row(),
        )

    def add_many(self, facts: Iterable[Fact]) -> int:
        count = 0
        for fact in facts:
            self.add(fact)
            count += 1
        self.conn.commit()
        return count

    def fact_at(self, subject_id: str, predicate: str, when: date) -> Optional[Fact]:
        """
        Fakt platný **k danému dni** — dotaz pro intervalové predikáty
        (`CLUB_MEMBERSHIP`, `MINISTERIAL_POST`, `BILL_STATUS`).

        Chybějící `valid_from`/`valid_to` znamená "od/do nepaměti", stejně
        jako `since`/`until is None` v `Registry.club_at()`.
        """
        when_iso = when.isoformat()
        row = self.conn.execute(
            "SELECT * FROM facts WHERE subject_id = ? AND predicate = ? "
            "AND (valid_from IS NULL OR valid_from <= ?) "
            "AND (valid_to IS NULL OR valid_to >= ?) "
            "ORDER BY valid_from IS NULL, valid_from DESC LIMIT 1",
            (str(subject_id), predicate, when_iso, when_iso),
        ).fetchone()
        return _row_to_fact(row) if row else None

    def fact_for_object(self, subject_id: str, predicate: str, object_id: str) -> Optional[Fact]:
        """Bodový dotaz pro `VOTE_CAST`: hlasoval poslanec X na hlasování Y?"""
        row = self.conn.execute(
            "SELECT * FROM facts WHERE subject_id = ? AND predicate = ? AND object_id = ? LIMIT 1",
            (str(subject_id), predicate, str(object_id)),
        ).fetchone()
        return _row_to_fact(row) if row else None

    def facts_for_subject(self, subject_id: str, predicate: Optional[str] = None) -> List[Fact]:
        if predicate:
            rows = self.conn.execute(
                "SELECT * FROM facts WHERE subject_id = ? AND predicate = ? ORDER BY valid_from",
                (str(subject_id), predicate),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM facts WHERE subject_id = ? ORDER BY predicate, valid_from",
                (str(subject_id),),
            ).fetchall()
        return [_row_to_fact(row) for row in rows]

    def count(self, predicate: Optional[str] = None) -> int:
        if predicate:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM facts WHERE predicate = ?", (predicate,)).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()
        return row["n"]

    def close(self) -> None:
        self.conn.close()


# -------------------------------------------------------------------------- #
# Producenti — mění existující scrapery na zdroj faktů
# -------------------------------------------------------------------------- #

def facts_from_registry(registry, source_url: str, recorded_at: str) -> List[Fact]:
    """`CLUB_MEMBERSHIP` fakta z `Registry.membership_intervals()`."""
    facts = []
    for id_osoba, zkratka, id_organ, since, until in registry.membership_intervals():
        valid_from = since.isoformat() if since else None
        facts.append(Fact(
            fact_id=make_fact_id("CLUB_MEMBERSHIP", id_osoba, id_organ, valid_from),
            subject_type="POLITICIAN",
            subject_id=str(id_osoba),
            predicate="CLUB_MEMBERSHIP",
            object_type="CLUB",
            object_id=str(id_organ),
            literal_value=zkratka,
            valid_from=valid_from,
            valid_to=until.isoformat() if until else None,
            source_url=source_url,
            source_dataset="psp-opendata-poslanci",
            recorded_at=recorded_at,
        ))
    return facts


def facts_from_ballot(ballot, recorded_at: str) -> List[Fact]:
    """
    `VOTE_CAST` fakta z jednoho `Ballot`.

    Bodová událost: `valid_from == valid_to` == den hlasování. Kdo u
    hlasování nebyl přítomen (`NEPRIHLASEN`), fakt přesto dostane — nepřítomnost
    u konkrétního hlasování je taky ověřitelný fakt, ne mezera v datech.
    """
    facts = []
    valid_on = ballot.date.isoformat() if ballot.date else None
    for id_osoba, vote in ballot.votes.items():
        facts.append(Fact(
            fact_id=make_fact_id("VOTE_CAST", id_osoba, ballot.ballot_id, valid_on),
            subject_type="POLITICIAN",
            subject_id=str(id_osoba),
            predicate="VOTE_CAST",
            object_type="BALLOT",
            object_id=str(ballot.ballot_id),
            literal_value=vote.value,
            valid_from=valid_on,
            valid_to=valid_on,
            source_url=ballot.url,
            source_dataset="psp-hlasovani",
            recorded_at=recorded_at,
        ))
    return facts


if __name__ == "__main__":
    # Self-test bez sítě: syntetický registr + syntetické hlasování.
    from datetime import datetime

    class _FakeVote:
        def __init__(self, id_osoba, value):
            self.id_osoba = id_osoba
            self.value = value

    class _FakeBallot:
        ballot_id = "87115"
        url = "https://www.psp.cz/sqw/hlasy.sqw?G=87115"
        date = date(2026, 4, 14)
        votes = {"6987": _FakeVote("6987", "PRO")}

    now = datetime.now().replace(microsecond=0).isoformat()
    store = FactStore.open(":memory:")

    club_facts = [
        Fact(
            fact_id=make_fact_id("CLUB_MEMBERSHIP", "6987", "174-1", "2025-11-04"),
            subject_type="POLITICIAN", subject_id="6987", predicate="CLUB_MEMBERSHIP",
            object_type="CLUB", object_id="174-1", literal_value="ODU",
            valid_from="2025-11-04", valid_to=None,
            source_url="https://www.psp.cz/eknih/cdrom/opendata/poslanci.zip",
            source_dataset="psp-opendata-poslanci", recorded_at=now,
        ),
    ]
    store.add_many(club_facts)
    store.add_many(facts_from_ballot(_FakeBallot(), now))

    print("fakta celkem:", store.count())
    print("klub 6987 k 2026-03-01:", store.fact_at("6987", "CLUB_MEMBERSHIP", date(2026, 3, 1)))
    print("klub 6987 k 2025-01-01 (před nástupem):", store.fact_at("6987", "CLUB_MEMBERSHIP", date(2025, 1, 1)))
    print("hlas 6987 na 87115:", store.fact_for_object("6987", "VOTE_CAST", "87115"))
    print("hlas 9999 na 87115 (nemělo by nic najít):", store.fact_for_object("9999", "VOTE_CAST", "87115"))
