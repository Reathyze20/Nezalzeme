"""
Jmenovité hlasování Poslanecké sněmovny – "Voting Ledger" pro Fázi 3.

Zdrojem je HTML stránka `sqw/hlasy.sqw?G=<id>`, ne hlasovací dump z otevřených
dat. Má to dva důvody a oba jsou podstatné pro důkazní hodnotu značky:

  * Dump `hl-YYYYps.zip` slučuje "zdržel se" a "nehlasoval" do jediného kódu
    `K`. Rozdíl mezi zdržením a neúčastí na hlasování ale nese úplně jiný
    význam, takže by se ztratil právě ten údaj, o který jde.
  * Dump se aktualizuje jednou denně a poslední jednací den v něm ještě není.
    Zpracovat dnešní schůzi by tedy nešlo.

Identifikátory hlasování se neodhadují – berou se z odkazů `hlasy.sqw?G=`,
které stojí přímo ve stenozáznamu v místě, kde předsedající hlasování řídí.
Vazba "tento výrok ↔ toto hlasování" tak pochází ze zdroje, ne z našeho
párování.
"""

import re
from datetime import date, time
from typing import Dict, List, Optional

from .client import PspClient
from .stenoprotokol import parse_czech_date

BALLOT_URL = "https://www.psp.cz/sqw/hlasy.sqw?G={}"

#: Grafická značka u jména -> hodnota v našem datovém modelu.
VOTE_BY_FLAG = {
    "yes": "PRO",
    "no": "PROTI",
    "refrained": "ZDRZEL_SE",
    "not-logged-in": "NEPRIHLASEN",
    "excused": "NEPRIHLASEN",
}

#: Značky, které znamenají "u hlasování vůbec nebyl", ne "hlasoval takto".
ABSENT_FLAGS = {"not-logged-in", "excused"}

_MP_ROW = re.compile(
    r'<li><span class="flag ([\w-]+)">[^<]*</span>\s*'
    r'<a href="detail\.sqw\?id=(\d+)[^"]*">(.*?)</a></li>',
    re.S,
)
_CLUB_HEADING = re.compile(r'<h2[^>]*><span>([^(<]+)\(', re.S)
_HEADLINE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_RESULT = re.compile(r"NÁVRH\s+(?:NE)?BYL\s+PŘIJAT", re.I)
_TAG = re.compile(r"<[^>]+>")

#: Souhrn nad jmenným seznamem – používá se ke kontrole, že jsme přečetli
#: tolik hlasů, kolik jich Sněmovna sama vykazuje.
_SUMMARY_LABELS = {
    "Ano": "PRO",
    "Ne": "PROTI",
    "Zdržel se": "ZDRZEL_SE",
    "Nepřihlášen": "NEPRIHLASEN",
    "Omluven": "NEPRIHLASEN",
}


def _plain(fragment: str) -> str:
    text = _TAG.sub(" ", fragment).replace("&nbsp;", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


class Vote:
    __slots__ = ("id_osoba", "name", "club", "flag", "value")

    def __init__(self, id_osoba: str, name: str, club: str, flag: str) -> None:
        self.id_osoba = id_osoba
        self.name = name
        self.club = club
        self.flag = flag
        self.value = VOTE_BY_FLAG.get(flag, "NEPRIHLASEN")

    @property
    def present(self) -> bool:
        return self.flag not in ABSENT_FLAGS

    def __repr__(self) -> str:
        return "Vote({} {} {})".format(self.name, self.club, self.value)


class Ballot:
    """Jedno jmenovité hlasování včetně toho, jak hlasoval každý poslanec."""

    def __init__(self, ballot_id: str, url: str) -> None:
        self.ballot_id = ballot_id
        self.url = url
        self.session: Optional[int] = None
        self.number: Optional[int] = None
        self.date: Optional[date] = None
        self.clock: Optional[time] = None
        self.subject: str = ""
        self.result: str = ""
        self.votes: Dict[str, Vote] = {}
        self.unknown_flags: List[str] = []
        self.declared: Dict[str, int] = {}

    def vote_of(self, id_osoba: str) -> Optional[Vote]:
        return self.votes.get(str(id_osoba))

    def tally(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for vote in self.votes.values():
            counts[vote.value] = counts.get(vote.value, 0) + 1
        return counts

    def discrepancies(self) -> List[str]:
        """
        Porovná náš součet s číslem, které stránka sama uvádí v záhlaví.

        Nesoulad znamená, že jsme část jmenného seznamu nepřečetli – a značka
        postavená na takovém hlasování by tvrdila víc, než víme.
        """
        if not self.declared:
            return ["stránka neuvádí souhrn hlasů"]
        counted = self.tally()
        problems = []
        for value, expected in sorted(self.declared.items()):
            actual = counted.get(value, 0)
            if actual != expected:
                problems.append(
                    "{}: přečteno {}, sněmovna uvádí {}".format(value, actual, expected)
                )
        return problems

    @property
    def passed(self) -> Optional[bool]:
        if not self.result:
            return None
        return "NEBYL" not in self.result.upper()

    def __repr__(self) -> str:
        return "Ballot({} {}. hlasovani {} {})".format(
            self.ballot_id, self.number, self.date, self.result
        )


def parse_ballot(html: str, ballot_id: str, url: str) -> Ballot:
    ballot = Ballot(ballot_id, url)

    headline = _HEADLINE.search(html)
    if headline:
        text = _plain(headline.group(1))
        session = re.search(r"(\d+)\.\s*schůze", text)
        number = re.search(r"(\d+)\.\s*hlasování", text)
        clock = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
        if session:
            ballot.session = int(session.group(1))
        if number:
            ballot.number = int(number.group(1))
        ballot.date = parse_czech_date(text)
        if clock:
            ballot.clock = time(
                int(clock.group(1)), int(clock.group(2)), int(clock.group(3) or 0)
            )
        # Za časem následuje předmět hlasování bez oddělovače.
        if clock:
            ballot.subject = text[clock.end():].strip()

    result = _RESULT.search(_plain(html))
    if result:
        ballot.result = result.group(0).upper()

    # Souhrn stojí nad prvním klubovým nadpisem; dál už jsou jen jména.
    first_club = html.find('<ul class="results">')
    header = _plain(html[:first_club] if first_club > 0 else html)
    for label, value in _SUMMARY_LABELS.items():
        match = re.search(re.escape(label) + r":\s*(\d+)", header)
        if match:
            ballot.declared[value] = ballot.declared.get(value, 0) + int(match.group(1))

    # Klub se odvozuje z posledního nadpisu před řádkem poslance.
    club_positions = [(m.start(), _plain(m.group(1))) for m in _CLUB_HEADING.finditer(html)]
    for match in _MP_ROW.finditer(html):
        club = ""
        for position, name in club_positions:
            if position < match.start():
                club = name
            else:
                break
        flag = match.group(1)
        if flag not in VOTE_BY_FLAG and flag not in ballot.unknown_flags:
            ballot.unknown_flags.append(flag)
        ballot.votes[match.group(2)] = Vote(match.group(2), _plain(match.group(3)), club, flag)

    return ballot


def load_ballot(client: PspClient, ballot_id: str) -> Ballot:
    url = BALLOT_URL.format(ballot_id)
    return parse_ballot(client.get_text(url), str(ballot_id), url)


def load_ballots(client: PspClient, ballot_ids) -> Dict[str, Ballot]:
    ballots: Dict[str, Ballot] = {}
    for ballot_id in ballot_ids:
        key = str(ballot_id)
        if key not in ballots:
            ballots[key] = load_ballot(client, key)
    return ballots
