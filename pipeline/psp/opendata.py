"""
Otevřená data Poslanecké sněmovny (`psp.cz/eknih/cdrom/opendata/`).

Dumpy jsou ve formátu UNL: řádky oddělené `\n`, sloupce `|`, kódování
`windows-1250`, prázdná hodnota = prázdný řetězec. Tenhle modul z nich staví
rejstřík, který zbytek pipeline potřebuje ke dvěma věcem:

  * přeložit `id_osoba` ze stenozáznamu na jméno poslance,
  * zjistit **klub k datu vystoupení** – přeběhy mezi kluby jsou v datech
    zachycené intervalem, takže klub nesmí být brán „k dnešku".

Rozsah dumpů je záměrně omezený: hlasovací archiv `hl-YYYYps.zip` sice existuje,
ale slučuje „zdržel se" a „nehlasoval" do jednoho kódu a zaostává o poslední
jednací den. Jmenovité hlasování proto čte `psp.hlasovani` z HTML.
"""

import os
import zipfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .client import PspClient

#: `id_organ` volebního období. 174 = Poslanecká sněmovna zvolená v roce 2025.
TERM_ORGAN_ID = 174

#: `id_typ_organu` = 1 znamená poslanecký klub.
CLUB_TYPE_ID = 1

#: Datum výměny vlády Fialy za vládu Babiše. Koaliční příslušnost klubu není
#: v otevřených datech Sněmovny vůbec — organy.unl typ 5 dá jen členy vlády
#: (ministry), ne to, které kluby vládu v Poslanecké sněmovně podpírají. To je
#: politický fakt, ne strukturální, proto je tenhle seznam a datum editorská
#: konstanta, ne odvozenina z dumpu; při další výměně vlády ji je třeba ručně
#: doplnit o nový řádek, ne přepsat.
GOVERNMENT_SWITCH_DATE = date(2025, 12, 15)
COALITION_CLUBS_BEFORE_SWITCH = {"ODS", "KDU-ČSL", "TOP09", "STAN", "PIRÁTI", "PIRATI"}
COALITION_CLUBS_AFTER_SWITCH = {"ANO2011", "ANO", "MS", "SPD"}


def read_unl(archive_path: str, member: str) -> List[List[str]]:
    """Načte jeden UNL soubor z archivu na seznam sloupců."""
    with zipfile.ZipFile(archive_path) as archive:
        raw = archive.read(member).decode("windows-1250", "replace")
    rows = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        # Řádek končí oddělovačem; rstrip('|') by ale spolkl i prázdné
        # koncové sloupce, proto se ořezává právě jeden.
        if line.endswith("|"):
            line = line[:-1]
        rows.append(line.split("|"))
    return rows


def _parse_date(value: str) -> Optional[date]:
    """UNL míchá dva tvary: `dd.mm.yyyy` (organy) a `yyyy-mm-dd HH` (zarazeni)."""
    value = (value or "").strip()
    if not value:
        return None
    for pattern, length in (("%d.%m.%Y", 10), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(value[:length], pattern).date()
        except ValueError:
            continue
    return None


class Person:
    __slots__ = ("id_osoba", "titul_pred", "prijmeni", "jmeno", "titul_za", "narozeni", "pohlavi")

    def __init__(self, cols: List[str]) -> None:
        get = lambda i: cols[i] if i < len(cols) else ""
        self.id_osoba = get(0)
        self.titul_pred = get(1)
        self.prijmeni = get(2)
        self.jmeno = get(3)
        self.titul_za = get(4)
        self.narozeni = get(5)
        self.pohlavi = get(6)

    @property
    def full_name(self) -> str:
        return "{} {}".format(self.jmeno, self.prijmeni).strip()

    def __repr__(self) -> str:
        return "Person({} {})".format(self.id_osoba, self.full_name)


class Registry:
    """Rejstřík osob a klubů pro jedno volební období."""

    def __init__(self, term_organ_id: int = TERM_ORGAN_ID) -> None:
        self.term_organ_id = str(term_organ_id)
        self.people: Dict[str, Person] = {}
        self.clubs: Dict[str, Dict[str, str]] = {}
        self._memberships: Dict[str, List[Tuple[str, Optional[date], Optional[date]]]] = {}
        self._gov_memberships: Dict[str, List[Tuple[str, Optional[date], Optional[date]]]] = {}
        self._deputy_id: Dict[str, str] = {}

    @classmethod
    def load(cls, client: PspClient, term_organ_id: int = TERM_ORGAN_ID) -> "Registry":
        registry = cls(term_organ_id)
        archive = client.opendata_archive("poslanci.zip")
        registry._load_people(archive)
        registry._load_clubs(archive)
        registry._load_memberships(archive)
        registry._load_governments(archive)
        registry._load_deputies(archive)
        return registry

    # -- načítání ----------------------------------------------------------

    def _load_people(self, archive: str) -> None:
        for cols in read_unl(archive, "osoby.unl"):
            if cols and cols[0]:
                self.people[cols[0]] = Person(cols)

    def _load_clubs(self, archive: str) -> None:
        for cols in read_unl(archive, "organy.unl"):
            if len(cols) < 8:
                continue
            id_organ, parent, typ = cols[0], cols[1], cols[2]
            if typ != str(CLUB_TYPE_ID):
                continue
            self.clubs[id_organ] = {
                "zkratka": cols[3],
                "nazev": cols[4],
                "od": cols[6],
                "do": cols[7],
            }

    def _load_governments(self, archive: str) -> None:
        """Načte intervaly členství ve vládách ČR (typ orgánu = 5)."""
        gov_ids = set()
        for cols in read_unl(archive, "organy.unl"):
            if len(cols) > 2 and cols[2] == "5":
                gov_ids.add(cols[0])
        for cols in read_unl(archive, "zarazeni.unl"):
            if len(cols) < 5:
                continue
            id_osoba, id_of, cl_funkce = cols[0], cols[1], cols[2]
            if cl_funkce != "0" or id_of not in gov_ids:
                continue
            self._gov_memberships.setdefault(id_osoba, []).append(
                (id_of, _parse_date(cols[3]), _parse_date(cols[4]))
            )

    def _load_memberships(self, archive: str) -> None:
        club_ids = set(self.clubs)
        for cols in read_unl(archive, "zarazeni.unl"):
            if len(cols) < 5:
                continue
            id_osoba, id_of, cl_funkce = cols[0], cols[1], cols[2]
            # cl_funkce = 0 -> členství v orgánu; 1 -> výkon funkce.
            if cl_funkce != "0" or id_of not in club_ids:
                continue
            self._memberships.setdefault(id_osoba, []).append(
                (id_of, _parse_date(cols[3]), _parse_date(cols[4]))
            )

    def _load_deputies(self, archive: str) -> None:
        for cols in read_unl(archive, "poslanec.unl"):
            if len(cols) >= 5 and cols[4] == self.term_organ_id:
                self._deputy_id[cols[1]] = cols[0]

    # -- dotazy ------------------------------------------------------------

    def is_government_member(self, id_osoba: str, when: date) -> bool:
        """Zda byla osoba k danému dni členem Vlády ČR."""
        for id_organ, since, until in self._gov_memberships.get(str(id_osoba), []):
            if since and when < since:
                continue
            if until and when > until:
                continue
            return True
        return False

    def political_role_at(self, id_osoba: str, when: date) -> Dict[str, Any]:
        """
        Určí politickou roli osoby k danému datu:
        - role: 'MINISTER' (člen vlády), 'COALITION_DEPUTY', 'OPPOSITION_DEPUTY', 'INDEPENDENT'
        - club: zkratka klubu k datu
        - isGovernment: přímý člen vlády
        """
        is_gov = self.is_government_member(id_osoba, when)
        club = self.club_at(id_osoba, when)

        coalition_clubs = (
            COALITION_CLUBS_BEFORE_SWITCH if when < GOVERNMENT_SWITCH_DATE
            else COALITION_CLUBS_AFTER_SWITCH
        )

        if is_gov:
            role = "MINISTER"
        elif club and club.upper() in coalition_clubs:
            role = "COALITION_DEPUTY"
        elif club:
            role = "OPPOSITION_DEPUTY"
        else:
            role = "INDEPENDENT"

        return {
            "role": role,
            "club": club or "",
            "isGovernment": is_gov,
        }

    # -- dotazy ------------------------------------------------------------

    def person(self, id_osoba: str) -> Optional[Person]:
        return self.people.get(str(id_osoba))

    def name(self, id_osoba: str) -> str:
        person = self.person(id_osoba)
        return person.full_name if person else ""

    def club_at(self, id_osoba: str, when: date) -> Optional[str]:
        """
        Zkratka klubu, ve kterém byl poslanec **k danému dni**.

        Vrací None u členů vlády bez poslaneckého mandátu i u nezařazených –
        obojí je legitimní stav, ne chyba dat.
        """
        for id_organ, since, until in self._memberships.get(str(id_osoba), []):
            if since and when < since:
                continue
            if until and when > until:
                continue
            return self.clubs[id_organ]["zkratka"]
        return None

    def membership_intervals(self):
        """
        Všechny intervaly členství v klubu jako `(id_osoba, zkratka, id_organ, since, until)`.

        Veřejný pohled na `_memberships` pro `psp.facts` (Fáze 2a) — ten
        generalizuje přesně tenhle interval na libovolný typ faktu, aniž by
        musel sahat na soukromý atribut.
        """
        for id_osoba, memberships in self._memberships.items():
            for id_organ, since, until in memberships:
                club = self.clubs.get(id_organ)
                if club:
                    yield id_osoba, club["zkratka"], id_organ, since, until

    def club_full_name(self, zkratka: str) -> Optional[str]:
        for club in self.clubs.values():
            if club["zkratka"] == zkratka:
                return club["nazev"]
        return None

    def deputy_id(self, id_osoba: str) -> Optional[str]:
        """`id_poslanec` pro dané volební období (klíč hlasovacích dumpů)."""
        return self._deputy_id.get(str(id_osoba))

    def deputy_ids(self):
        """
        Všechny dvojice `(id_osoba, id_poslanec)` pro dané volební období.

        Veřejný pohled na `_deputy_id` — hlasovací dumpy (`hl2025h1.unl`,
        `omluvy.unl`) identifikují člověka přes `id_poslanec`, takže kdokoli
        z nich počítá poměry po klubech, potřebuje mapování zpátky na
        `id_osoba`, na kterém stojí `club_at()`.
        """
        return self._deputy_id.items()

    def summary(self) -> str:
        return "rejstřík: {} osob, {} klubů, {} poslanců období {}".format(
            len(self.people), len(self.clubs), len(self._deputy_id), self.term_organ_id
        )


if __name__ == "__main__":
    client = PspClient()
    registry = Registry.load(client)
    print(registry.summary())
    print("kluby:", sorted(c["zkratka"] for c in registry.clubs.values()))
    when = date(2026, 8, 26)
    for id_osoba in ("6987", "6468", "6552", "6205", "6687", "6150"):
        person = registry.person(id_osoba)
        print("  {} {:<22} klub={} id_poslanec={}".format(
            id_osoba,
            person.full_name if person else "?",
            registry.club_at(id_osoba, when),
            registry.deputy_id(id_osoba),
        ))
