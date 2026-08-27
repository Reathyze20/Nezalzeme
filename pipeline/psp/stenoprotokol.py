"""
Parser stenografických zápisů Poslanecké sněmovny.

Sněmovna publikuje týž stenozáznam ve dvou podobách. Běžná stránka
`sSSSTTT.htm` je čitelná, ale nese jen jméno řečníka. Vedle ní stojí pohled
"po bodech pořadu" v adresáři `bqbs/`, který má u každého projevu skrytý
strukturovaný komentář:

    <!--###3#6687|92703|0|Poslanec Jan Jakob|Jan|Jakob|Řeč poslance ...|@@-->

Z něj čteme `id_osoba` a **čas zahájení projevu s přesností na sekundy** – to
je přesně ten údaj, který Fáze 6 potřebuje a který se z běžné stránky
dopočítat nedá. Text i metadata proto bereme z `bqbs/`.

Citovat se ale sluší na běžnou stránku, kterou čtenář zná. Ta kotva se
**hledá** (`attach_source_urls`), nedopočítává: běžná stránka dělí záznam po
desetiminutových blocích, takže umí přeříznout jeden projev na dvě části a
pokračování už uvede jen poznámkou "(pokračuje Jan Jakob)" bez kotvy. Pořadové
číslo by se proto s pořadím projevů rozešlo.
"""

import re
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

from .client import PspClient, absolute

BASE = "https://www.psp.cz"

_MONTHS = {
    "ledna": 1, "února": 2, "března": 3, "dubna": 4, "května": 5, "června": 6,
    "července": 7, "srpna": 8, "září": 9, "října": 10, "listopadu": 11, "prosince": 12,
}

#: Skrytá značka projevu. Zápis musí sedět celý včetně koncového `@@-->`:
#: stránka nese i značky bez polí (`<!--###1#-->` uvozuje název bodu) a volnější
#: výraz by od nich přečetl hodnoty až u nejbližšího projevu za nimi.
_SPEECH_MARKER = re.compile(
    r"<!--###(?P<kind>\d+)#(?P<osoba>\d*)\|(?P<cas>\d*)\|(?P<flag>[^|]*)\|"
    r"(?P<titul>[^|]*)\|(?P<jmeno>[^|]*)\|(?P<prijmeni>[^|]*)\|(?P<popis>[^|]*)\|@@-->"
)
#: Řečnická hlavička. Odkaz nemíří vždy na profil poslance – členové vlády bez
#: mandátu mají odkaz na vlada.gov.cz – proto se na cíl odkazu neváže.
_ANCHOR = re.compile(r'<b><a href="[^"]*"\s+id="(r\d+)">(.*?)</a></b>\s*:?', re.S)
_TURN = re.compile(r"<!--\s*turn\s+(\d+)\s*-->")
_BALLOT = re.compile(r"hlasy\.sqw\?G=(\d+)")
_TAG = re.compile(r"<[^>]+>")
_PARAGRAPH = re.compile(r"</p\s*>|<br\s*/?>", re.I)
_ENTITIES = {
    "&nbsp;": " ", "&ndash;": "–", "&mdash;": "—", "&amp;": "&",
    "&lt;": "<", "&gt;": ">", "&quot;": '"', "&bdquo;": "„",
    "&ldquo;": "“", "&rdquo;": "“", "&hellip;": "…",
    "&#8211;": "–", "&sbquo;": "‚",
}


def _text(fragment: str) -> str:
    """HTML fragment -> čistý text; odstavce zůstávají oddělené novým řádkem."""
    fragment = _PARAGRAPH.sub("\n", fragment)
    fragment = _TAG.sub("", fragment)
    for entity, char in _ENTITIES.items():
        fragment = fragment.replace(entity, char)
    fragment = re.sub(r"&[#\w]{2,8};", " ", fragment)
    fragment = fragment.replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in fragment.split("\n")]
    return "\n".join(line for line in lines if line)


def clock_readings(value: str) -> List[time]:
    """
    Možná čtení času ze skryté značky stenozáznamu.

    Sněmovna zapisuje čas jako celé číslo bez vodicích nul a nekonzistentně –
    jednou se sekundami, jindy bez nich. Krátký zápis je proto dvojznačný:
    `2110` je „21:10" na odpolední schůzi, ale „0:21:10" po půlnoci. Rozhodnout
    se dá jen podle sousedních projevů, takže tahle funkce vrací obě čtení
    a výběr dělá `resolve_clocks`.
    """
    digits = (value or "").strip()
    if not digits.isdigit() or not digits:
        return []
    readings: List[time] = []
    for width, with_seconds in ((6, True), (4, False)):
        if len(digits) > width:
            continue
        padded = digits.zfill(width)
        try:
            readings.append(time(
                int(padded[0:2]), int(padded[2:4]),
                int(padded[4:6]) if with_seconds else 0,
            ))
        except ValueError:
            continue
    return readings


#: Nejdřívější hodina, kdy Sněmovna zahajuje jednací den. Používá se jen na
#: úplně první čas dne, kde není podle čeho se rozhodnout.
_SITTING_STARTS_AFTER = time(7, 0)

#: Mez, nad kterou už "skok dopředu" není věrohodný. Nad ní se čtení bere jako
#: drobné přehození pořadí v ručně psaném zápisu, ne jako pokračování po půlnoci.
_MAX_FORWARD_GAP = timedelta(hours=6)

_EPOCH = date(2000, 1, 1)


def resolve_clocks(speeches: List["Speech"]) -> None:
    """
    Doplní `clock` a `day_offset` všem vystoupením jednacího dne.

    Postupuje se od začátku dne a z možných čtení se vždy bere to, které
    navazuje na předchozí projev nejtěsněji. Tím se současně vyřeší dvojznačný
    zápis času i to, že noční jednání pokračuje po půlnoci pod datem, kdy
    začalo.
    """
    previous: Optional[datetime] = None
    offset = 0

    for speech in speeches:
        readings = clock_readings(speech.clock_raw)
        if not readings:
            speech.clock = None
            speech.day_offset = offset
            continue

        if previous is None:
            chosen = next((r for r in readings if r >= _SITTING_STARTS_AFTER), readings[0])
            speech.clock = chosen
            speech.day_offset = offset
            previous = datetime.combine(_EPOCH, chosen)
            continue

        # Kandidáti se staví vůči dosud dosaženému dni, ne vůči začátku –
        # jinak by se každý další noční projev počítal jako nový přelom.
        best = None
        for reading in readings:
            for extra in (0, 1):
                moment = datetime.combine(_EPOCH + timedelta(days=offset + extra), reading)
                if moment < previous:
                    continue
                gap = moment - previous
                if best is None or gap < best[0]:
                    best = (gap, reading, extra)

        if best is None or best[0] > _MAX_FORWARD_GAP:
            # Žádné čtení nejde věrohodně dopředu. Nejblíž pravdě je to, které
            # leží nejblíž předchozímu času – i když je o pár vteřin dřív.
            reading = min(readings, key=lambda r: abs(
                datetime.combine(_EPOCH + timedelta(days=offset), r) - previous))
            speech.clock = reading
            speech.day_offset = offset
            previous = max(previous, datetime.combine(_EPOCH + timedelta(days=offset), reading))
            continue

        _, reading, extra = best
        offset += extra
        speech.clock = reading
        speech.day_offset = offset
        previous = datetime.combine(_EPOCH + timedelta(days=offset), reading)


class Speech:
    """Jedno vystoupení tak, jak stojí ve stenozáznamu."""

    def __init__(self, **kwargs) -> None:
        self.id_osoba: str = kwargs["id_osoba"]
        self.title: str = kwargs["title"]
        self.first_name: str = kwargs["first_name"]
        self.last_name: str = kwargs["last_name"]
        self.clock_raw: str = kwargs.get("clock_raw", "")
        self.clock: Optional[time] = kwargs.get("clock")
        self.text: str = kwargs["text"]
        self.turn: Optional[int] = kwargs["turn"]
        self.anchor: str = kwargs["anchor"]
        self.section_title: str = kwargs["section_title"]
        self.source_url: str = kwargs["source_url"]
        self.page_url: str = kwargs["page_url"]
        self.ballot_ids: List[str] = kwargs["ballot_ids"]
        self.order: int = kwargs["order"]
        #: True, jakmile `source_url` míří na kotvu skutečně nalezenou na běžné
        #: stránce stenozáznamu. Dokud je False, ukazuje odkaz na stránku
        #: `bqbs/`, ze které jsme text četli – taky doložitelnou, ale méně
        #: obvyklou pro čtenáře.
        self.anchor_verified: bool = False
        #: 0 pro jednací den, 1 pro jeho pokračování po půlnoci. Sněmovna vede
        #: noční jednání pod datem, kdy začalo, takže projev ve 2:10 má
        #: kalendářní datum o den vyšší.
        self.day_offset: int = 0

    def moment(self, base: date):
        """Datum a čas projevu; None, když stenozáznam čas neuvádí."""
        if not self.clock:
            return None
        return datetime.combine(base + timedelta(days=self.day_offset), self.clock)

    @property
    def speaker(self) -> str:
        return "{} {}".format(self.first_name, self.last_name).strip()

    @property
    def role(self) -> str:
        """Funkce před jménem - "Poslanec", "Místopředseda PSP", ministr..."""
        name = self.speaker
        index = self.title.find(name)
        return self.title[:index].strip() if index > 0 else self.title.strip()

    def __repr__(self) -> str:
        return "Speech({} {} {} znaku)".format(self.clock, self.speaker, len(self.text))


#: Prvky stránky, které nepatří žádnému projevu. Kdyby zůstaly, přilepily by
#: se k poslednímu vystoupení na stránce – a znakové indexy anotací by pak
#: ukazovaly do textu, který nikdo neřekl ("Zvukový záznam", "Aktualizováno...").
_FURNITURE = (
    re.compile(r'<div class="media-links[^"]*">.*?</div>', re.S),
    re.compile(r'<p class="status[^"]*">.*?</p>', re.S),
    re.compile(r'<div class="document-nav[^"]*">.*?</div>', re.S),
)


def _content_region(html: str) -> str:
    """Ořízne stránku na vlastní záznam a odstraní z ní prvky stránky."""
    start = html.find('id="main-content"')
    if start < 0:
        start = 0

    candidates = []
    for marker in ('<a id="_d"', '<a name="_d"', "<!--/ Body"):
        position = html.find(marker, start + 1)
        if position > start:
            candidates.append(position)
    # Navigace je na stránce dvakrát, nahoře a dole; koncem je ta spodní.
    navigation = [m.start() for m in re.finditer(r"document-nav", html)]
    if len(navigation) > 1 and navigation[-1] > start:
        candidates.append(html.rfind("<", start, navigation[-1]))

    end = min(p for p in candidates if p > start) if candidates else -1
    region = html[start:end] if end > start else html[start:]
    for pattern in _FURNITURE:
        region = pattern.sub(" ", region)
    return region


def _section_title(html: str) -> str:
    """
    Název bodu pořadu schůze.

    Sněmovna ho vyznačuje vlastní dvojicí prázdných značek `###1#`/`###2#`
    (číslo bodu a jeho název) uzavřenou `@@`. U sekcí bez bodu – zahájení
    jednacího dne – takové značky nejsou a název se bere z titulku stránky.
    """
    heading = re.search(r"<!--###1#-->(.*?)<!--@@-->", html, re.S)
    if heading:
        title = re.sub(r"\s+", " ", _text(heading.group(1)).replace("\n", " ")).strip()
        if title:
            return title
    # Sekce bez bodu (zahájení, přerušení) se pozná z popisku nad záznamem:
    # "Středa 26. srpna 2026, stenozáznam zahájení jednacího dne schůze".
    label = re.search(r'<p class="date">(.*?)</p>', html, re.S)
    if label:
        text = re.sub(r"\s+", " ", _text(label.group(1)).replace("\n", " ")).strip()
        if "," in text:
            tail = text.split(",", 1)[1].strip()
            if tail:
                return tail[0].upper() + tail[1:]
    match = re.search(r"<title>(.*?)</title>", html, re.S)
    return _text(match.group(1)).strip() if match else ""


def parse_bqbs_page(html: str, page_url: str, session: int, term_path: str) -> List["Speech"]:
    """Rozebere jednu stránku `bqbs/` na seznam vystoupení."""
    region = _content_region(html)
    section = _section_title(html)
    markers = list(_SPEECH_MARKER.finditer(region))
    speeches: List[Speech] = []

    # Značka `<!-- turn N -->` stojí až tam, kde začíná další desetiminutový
    # blok. První projevy stránky ji tedy před sebou nemají a jejich turn se
    # bere z názvu souboru (`b070...` = turn 70).
    filename = page_url.rsplit("/", 1)[-1]
    default_turn = int(filename[1:4]) if re.match(r"b\d{8}\.html?$", filename) else None

    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(region)
        block = region[marker.start():end]

        turns = _TURN.findall(region[:marker.start()])
        turn = int(turns[-1]) if turns else default_turn

        anchor_match = _ANCHOR.search(block)
        anchor = anchor_match.group(1) if anchor_match else ""
        body = block[anchor_match.end():] if anchor_match else block[marker.end():]

        # Odkaz na běžnou stránku doplní `attach_source_urls` až po přečtení
        # stránek; dopočítávat ho z pořadí nelze, protože běžná stránka umí
        # projev rozdělit na dvě části a druhou už kotvou neopatří.
        source_url = page_url + ("#" + anchor if anchor else "")

        speeches.append(Speech(
            id_osoba=marker.group("osoba"),
            title=_text(marker.group("titul")),
            first_name=_text(marker.group("jmeno")),
            last_name=_text(marker.group("prijmeni")),
            clock_raw=marker.group("cas"),
            text=_text(body),
            turn=turn,
            anchor=anchor,
            section_title=section,
            source_url=source_url,
            page_url=page_url + ("#" + anchor if anchor else ""),
            ballot_ids=sorted(set(_BALLOT.findall(block))),
            order=index + 1,
        ))
    return speeches


# --------------------------------------------------------------------------
# Objevování schůzí a jednacích dnů
# --------------------------------------------------------------------------

def parse_czech_date(text: str) -> Optional[date]:
    match = re.search(r"(\d{1,2})\.\s*([^\W\d_]+)\s*(\d{4})", text, re.UNICODE)
    if not match:
        return None
    month = _MONTHS.get(match.group(2).lower())
    if not month:
        return None
    return date(int(match.group(3)), month, int(match.group(1)))


class DayRecord:
    def __init__(self, session: int, day: int, url: str,
                 when: Optional[date] = None, title: str = "") -> None:
        self.session = session
        self.day = day
        self.url = url
        self.date = when
        self.title = title

    def __repr__(self) -> str:
        return "{}. schuze, den {} ({})".format(self.session, self.day, self.date)


def list_days(client: PspClient, term_path: str = "eknih/2025ps") -> List[DayRecord]:
    """Všechny jednací dny volebního období, seřazené podle schůze a dne."""
    index_url = "{}/{}/stenprot/index.htm".format(BASE, term_path)
    html = client.get_text(index_url)
    unique: Dict[str, DayRecord] = {}
    pattern = r'href="(?P<href>\d{3}schuz/(?P<s>\d+)-(?P<d>\d+)\.html?)"'
    for match in re.finditer(pattern, html):
        url = "{}/{}/stenprot/{}".format(BASE, term_path, match.group("href"))
        unique.setdefault(url, DayRecord(int(match.group("s")), int(match.group("d")), url))
    return sorted(unique.values(), key=lambda r: (r.session, r.day))


def load_day(client: PspClient, record: DayRecord) -> DayRecord:
    """Doplní datum a titulek jednacího dne z jeho stránky."""
    html = client.get_text(record.url)
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    record.title = _text(title.group(1)).strip() if title else ""
    record.date = parse_czech_date(record.title)
    return record


def day_sections(client: PspClient, record: DayRecord) -> List[str]:
    """Absolutní URL stránek `bqbs/`, na které se jednací den dělí."""
    html = client.get_text(record.url)
    base = record.url.rsplit("/", 1)[0]
    seen: List[str] = []
    for href in re.findall(r'href="(bqbs/b\d+\.html?)"', html):
        url = absolute(href, base)
        if url not in seen:
            seen.append(url)
    return seen


def page_anchors(client: PspClient, url: str):
    """Řečnické kotvy běžné stránky stenozáznamu v pořadí, v jakém tam stojí."""
    try:
        html = client.get_text(url)
    except Exception:
        return []
    region = _content_region(html)
    return [(match.group(1), _text(match.group(2)).strip()) for match in _ANCHOR.finditer(region)]


def attach_source_urls(client: PspClient, speeches: List[Speech], session: int,
                       term_path: str = "eknih/2025ps") -> None:
    """
    Nahradí odkaz na stránku `bqbs/` odkazem na běžnou stránku stenozáznamu.

    Kotva se **hledá**, nedopočítává. Běžná stránka umí projev přerušit na
    hranici desetiminutového bloku a pokračování už uvede jen poznámkou
    „(pokračuje Jan Jakob)" bez kotvy, takže pořadové číslo by se rozešlo se
    skutečností. Postupuje se proto oběma seznamy současně a páruje se na shodu
    řečnické hlavičky; co se nespáruje, zůstane s odkazem na `bqbs/`.
    """
    turns = sorted({s.turn for s in speeches if s.turn is not None})
    if not turns:
        return

    anchors = []
    for turn in range(turns[0], turns[-1] + 1):
        url = "{}/{}/stenprot/{:03d}schuz/s{:03d}{:03d}.htm".format(
            BASE, term_path, session, session, turn)
        for anchor, label in page_anchors(client, url):
            anchors.append((url, anchor, label))

    cursor = 0
    for speech in speeches:
        for offset in range(0, 6):
            index = cursor + offset
            if index >= len(anchors):
                break
            url, anchor, label = anchors[index]
            if label == speech.title:
                speech.source_url = url + "#" + anchor
                speech.anchor_verified = True
                cursor = index + 1
                break


def load_day_speeches(client: PspClient, record: DayRecord,
                      term_path: str = "eknih/2025ps") -> List[Speech]:
    """Všechna vystoupení jednacího dne napříč jeho sekcemi."""
    speeches: List[Speech] = []
    for url in day_sections(client, record):
        html = client.get_text(url)
        speeches.extend(parse_bqbs_page(html, url, record.session, term_path))
    resolve_clocks(speeches)
    attach_source_urls(client, speeches, record.session, term_path)
    return speeches
