"""
Kontrola přesnosti stažených stenozáznamů.

    python pipeline/psp_verify.py                      # poslední jednací den
    python pipeline/psp_verify.py --schuze 29 --den 2
    python pipeline/psp_verify.py --vzorek 40

Smysl: než na datech postavíme značku, která tvrdí, že poslanec řekl X v čase T
a hlasoval Y, musíme vědět, jestli tomu tak opravdu je. Každá kontrola proto
porovnává náš výstup s **nezávislým** místem u Sněmovny, ne sama se sebou:

  1. Kotva     – `sSSSTTT.htm#rN` musí na běžné stránce existovat a nést téhož
                 řečníka. Tím se ověřuje dopočet kotvy z hranic turnů.
  2. Text      – text u kotvy na běžné stránce se musí shodovat s tím, co jsme
                 přečetli z `bqbs/`.
  3. Pokrytí   – součet vystoupení na běžných stránkách = počet z `bqbs/`.
  4. Čas       – časy jdou po sobě a čas, kdy předsedající řídí hlasování,
                 sedí na čas zapsaný u samotného hlasování.
  5. Klub      – klub z otevřených dat = klub, pod kterým je poslanec uvedený
                 na stránce hlasování.
  6. Hlasování – náš jmenný součet = součet, který uvádí Sněmovna.
  7. Text pro engine – `cleanText` musí být dohledatelný v původním projevu,
                 jinak by znakové indexy anotací ukazovaly jinam.

Návratový kód 1 znamená, že aspoň jedna kontrola selhala.
"""

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psp.build import build_debates, latest_day  # noqa: E402
from psp.client import PspClient  # noqa: E402
from psp.facts import FactStore, facts_from_ballot, facts_from_registry  # noqa: E402
from psp.hlasovani import load_ballots  # noqa: E402
from psp.opendata import Registry  # noqa: E402
from psp.stenoprotokol import (  # noqa: E402
    _content_region, _text, list_days, load_day, load_day_speeches,
)

TERM_PATH = "eknih/2025ps"
_SPEAKER_ON_PAGE = re.compile(
    r'<b><a href="(?P<href>[^"]*)"\s+id="(?P<anchor>r\d+)">(?P<label>.*?)</a></b>'
    r'(?P<text>.*?)(?=<b><a href="[^"]*"\s+id="r\d+"|\Z)',
    re.S,
)
_DETAIL_ID = re.compile(r"detail\.sqw\?id=(\d+)")


class Report:
    def __init__(self) -> None:
        self.checks = []

    def add(self, name: str, passed: int, total: int, problems=None, blocking: bool = True) -> None:
        """`blocking=False` = zjištění se vypíše, ale nezpůsobí nenulový návrat."""
        self.checks.append((name, passed, total, list(problems or []), blocking))

    def ok(self) -> bool:
        return all(not problems for _, _, _, problems, blocking in self.checks if blocking)

    def render(self) -> str:
        lines = []
        for name, passed, total, problems, blocking in self.checks:
            share = "{}/{}".format(passed, total) if total else "n/a"
            mark = "OK   " if not problems else ("CHYBA" if blocking else "POZOR")
            lines.append("  [{}] {:<36} {}".format(mark, name, share))
            for problem in problems[:6]:
                lines.append("            - {}".format(problem))
            if len(problems) > 6:
                lines.append("            - ... a dalších {}".format(len(problems) - 6))
        return "\n".join(lines)


def page_speeches(client: PspClient, url: str):
    """
    Vystoupení tak, jak stojí na běžné stránce stenozáznamu.

    Pozor na dvě vlastnosti zdroje: členové vlády bez mandátu mají v hlavičce
    odkaz mimo psp.cz a projev přerušený na hranici stránky pokračuje bez
    kotvy. Regulární výraz proto neváže na `detail.sqw`.
    """
    try:
        html = client.get_text(url)
    except Exception:
        return []
    region = _content_region(html)
    found = []
    for match in _SPEAKER_ON_PAGE.finditer(region):
        profile = _DETAIL_ID.search(match.group("href"))
        found.append({
            "anchor": match.group("anchor"),
            "label": _text(match.group("label")).strip(),
            "text": _text(match.group("text")).lstrip(": ").strip(),
            # Členové vlády bez mandátu mají odkaz mimo psp.cz a `id_osoba` u
            # nich takhle ověřit nejde.
            "id_osoba": profile.group(1) if profile else None,
        })
    return found


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_continuation(text: str) -> str:
    """
    Odstraní značku `***`, kterou běžná stránka končí, pokračuje-li projev
    na další stránce. Text v `bqbs/` je celý, text běžné stránky jen po hranici
    desetiminutového bloku – porovnávat se proto dá jen jejich společný začátek.
    """
    return re.sub(r"[\s*]+$", "", text)


def verify(client: PspClient, record, registry: Registry, sample: int) -> Report:
    report = Report()
    speeches = load_day_speeches(client, record)
    debates = build_debates(client, record, registry)
    messages = [m for d in debates for m in d["messages"]]

    # ---- 1+2. kotvy a text na běžných stránkách -------------------------
    unverified = [s for s in speeches if not s.anchor_verified]
    report.add(
        "kotva nalezena na běžné stránce",
        len(speeches) - len(unverified), len(speeches),
        ["{} v {} zůstal jen s odkazem na bqbs".format(s.speaker, s.clock) for s in unverified],
    )

    by_page = {}
    for speech in speeches:
        if speech.anchor_verified:
            by_page.setdefault(speech.source_url.split("#")[0], []).append(speech)

    anchor_ok = anchor_total = 0
    text_ok = text_total = 0
    identity_ok = identity_total = 0
    anchor_problems, text_problems, identity_problems = [], [], []
    checked = 0
    for page, group in sorted(by_page.items()):
        if checked >= sample:
            break
        found = {item["anchor"]: item for item in page_speeches(client, page)}
        for speech in group:
            if checked >= sample:
                break
            checked += 1
            anchor = speech.source_url.split("#")[-1]
            anchor_total += 1
            item = found.get(anchor)
            if not item:
                anchor_problems.append("{} nemá kotvu {}".format(os.path.basename(page), anchor))
                continue
            if item["label"] != speech.title:
                anchor_problems.append("{}#{}: kotva nese {!r}, čekáno {!r}".format(
                    os.path.basename(page), anchor, item["label"], speech.title))
                continue
            anchor_ok += 1

            # Nejdůležitější údaj celé značky je, kdo výrok pronesl. `id_osoba`
            # čteme ze skryté značky, profil je vedle ní v odkazu – musí sedět.
            if item["id_osoba"]:
                identity_total += 1
                if item["id_osoba"] == speech.id_osoba:
                    identity_ok += 1
                else:
                    identity_problems.append("{}#{}: profil {}, ve značce {} ({})".format(
                        os.path.basename(page), anchor, item["id_osoba"],
                        speech.id_osoba or "prázdné", speech.speaker))

            text_total += 1
            ours = strip_continuation(normalize(speech.text))
            theirs = strip_continuation(normalize(item["text"]))
            shared = min(len(ours), len(theirs), 200)
            if shared and (ours[:shared] == theirs[:shared]):
                text_ok += 1
            else:
                text_problems.append("{}#{} ({}): text se liší od běžné stránky".format(
                    os.path.basename(page), anchor, speech.speaker))

    report.add("kotva vede na téhož řečníka", anchor_ok, anchor_total, anchor_problems)
    report.add("id_osoba = profil u kotvy", identity_ok, identity_total, identity_problems)
    report.add("text sedí s běžnou stránkou", text_ok, text_total, text_problems)

    # ---- 3. pokrytí -----------------------------------------------------
    # Nezávislý součet: projdou se všechny desetiminutové stránky v rozsahu
    # jednacího dne, ne jen ty, na které jsme si sami odkázali.
    turns = sorted({s.turn for s in speeches if s.turn is not None})
    counted = 0
    if turns:
        for turn in range(turns[0], turns[-1] + 1):
            url = "https://www.psp.cz/{}/stenprot/{:03d}schuz/s{:03d}{:03d}.htm".format(
                TERM_PATH, record.session, record.session, turn)
            counted += len(page_speeches(client, url))
    coverage_problems = []
    if counted != len(speeches):
        coverage_problems.append(
            "běžné stránky (turny {}–{}) mají {} kotev, z bqbs jsme přečetli {} vystoupení".format(
                turns[0], turns[-1], counted, len(speeches)))
    report.add("pokrytí jednacího dne", len(speeches), counted, coverage_problems)

    # ---- 4. časy --------------------------------------------------------
    # Porovnává se okamžik, ne hodina na ciferníku – noční jednání pokračuje
    # po půlnoci pod datem, kdy začalo.
    # Sněmovna některé časy zaokrouhluje na celou minutu ("Je 13.39" zapsáno
    # jako 13:40), takže drobné přehození o pár vteřin je vlastnost zdroje.
    # Skok o minuty a víc už by znamenal, že jsme čas přečetli špatně.
    rounding = timedelta(seconds=60)
    time_problems = []
    rounded = 0
    previous = None
    missing = 0
    for speech in speeches:
        if not speech.clock:
            missing += 1
            continue
        moment = speech.moment(record.date)
        if previous and moment < previous:
            if previous - moment <= rounding:
                rounded += 1
            else:
                time_problems.append("{} v {} předchází předchozímu {} o {}".format(
                    speech.speaker, moment, previous, previous - moment))
        previous = moment
    if missing:
        time_problems.append("{} vystoupení bez času".format(missing))
    report.add("časy jdou po sobě", len(speeches) - missing - rounded - len(time_problems),
               len(speeches), time_problems)
    if rounded:
        print("  (poznámka: {}× zaokrouhlení času na celou minutu ve zdroji)".format(rounded))

    ballots = load_ballots(client, sorted({b for s in speeches for b in s.ballot_ids}))

    # Tvrdá podmínka: hlasování, na které se odkazujeme, musí patřit k téže
    # schůzi a témuž jednacímu dni. Odkaz jinam by znamenal, že jsme si
    # spárovali výrok s cizím hlasováním.
    origin_problems = []
    for ballot in ballots.values():
        if ballot.session != record.session:
            origin_problems.append("hlasování {} patří ke {}. schůzi, ne k {}.".format(
                ballot.ballot_id, ballot.session, record.session))
        elif ballot.date and record.date and not (
                record.date <= ballot.date <= record.date + timedelta(days=1)):
            origin_problems.append("hlasování {} je z {}, jednací den je {}".format(
                ballot.ballot_id, ballot.date, record.date))
    report.add("hlasování patří k tomuto jednání", len(ballots) - len(origin_problems),
               len(ballots), origin_problems)

    # Měkčí podmínka: hlasování obvykle padne do vystoupení, ve kterém je
    # zmíněné. Předsedající se ale legitimně vrací i k dřívějšímu hlasování
    # (opakování zmatečného, rekapitulace), takže výjimky se hlásí, nepadají.
    pair_ok = pair_total = 0
    pair_problems = []
    tolerance = timedelta(minutes=2)
    for index, speech in enumerate(speeches):
        start = speech.moment(record.date)
        if not start:
            continue
        following = next(
            (s.moment(record.date) for s in speeches[index + 1:] if s.clock), None)
        end = following or (start + timedelta(hours=1))
        for ballot_id in speech.ballot_ids:
            ballot = ballots.get(ballot_id)
            if not ballot or not ballot.clock:
                continue
            pair_total += 1
            voted = datetime.combine(start.date(), ballot.clock)
            if voted < start - tolerance:
                voted += timedelta(days=1)
            if start - tolerance <= voted <= end + tolerance:
                pair_ok += 1
            else:
                pair_problems.append("hlasování {} v {}, ale projev trval {}–{}".format(
                    ballot_id, ballot.clock, start.strftime("%H:%M"), end.strftime("%H:%M")))
    report.add("hlasování padá do doby projevu", pair_ok, pair_total, pair_problems,
               blocking=False)

    # ---- 5. kluby -------------------------------------------------------
    club_ok = club_total = 0
    club_problems = []
    for ballot in ballots.values():
        for id_osoba, vote in ballot.votes.items():
            if not vote.club:
                continue
            club_total += 1
            ours = registry.club_at(id_osoba, record.date)
            if ours == vote.club:
                club_ok += 1
            else:
                club_problems.append("{}: otevřená data {}, hlasování {}".format(
                    vote.name, ours, vote.club))
    report.add("klub z dat = klub u hlasování", club_ok, club_total, club_problems)

    # ---- 6. hlasování ---------------------------------------------------
    tally_ok = 0
    tally_problems = []
    for ballot in ballots.values():
        problems = ballot.discrepancies()
        if problems:
            tally_problems.extend("hlasování {}: {}".format(ballot.ballot_id, p) for p in problems)
        else:
            tally_ok += 1
    report.add("jmenný součet = součet Sněmovny", tally_ok, len(ballots), tally_problems)

    # ---- 7. text pro engine ---------------------------------------------
    clean_ok = 0
    clean_problems = []
    for message in messages:
        clean = message["cleanText"]
        raw = message["rawText"]
        if not clean:
            clean_problems.append("{}: prázdný cleanText".format(message["messageId"]))
            continue
        head = clean.split("\n")[0][:60]
        if head and head in raw:
            clean_ok += 1
        else:
            clean_problems.append("{}: cleanText nelze dohledat v projevu".format(message["messageId"]))
    report.add("cleanText pochází z projevu", clean_ok, len(messages), clean_problems)

    # ---- 8. deterministická páteř (Fáze 2a) ------------------------------
    # `Registry`/`Ballot` jsou od Fáze 2a producenti faktů (`psp.facts`), ne
    # jen zdroj pro `club_at()`/`vote_of()` přímo. Kontroluje se, že fakt
    # vytažený obecným dotazem `fact_at`/`fact_for_object` souhlasí s tím, co
    # už dřív ověřily kontroly 5 a 6 nad samotným `registry`/`ballots` — tedy
    # že zobecnění interval/bodového modelu nic neztratilo.
    recorded_at = datetime.now().isoformat()
    fact_store = FactStore.open(":memory:")
    fact_store.add_many(facts_from_registry(
        registry, "https://www.psp.cz/eknih/cdrom/opendata/poslanci.zip", recorded_at))
    for ballot in ballots.values():
        fact_store.add_many(facts_from_ballot(ballot, recorded_at))

    vote_fact_ok = vote_fact_total = 0
    vote_fact_problems = []
    for message in messages:
        id_osoba = message.get("source", {}).get("idOsoba")
        if not id_osoba:
            continue
        for ballot_ref in message["source"]["ballots"]:
            if ballot_ref["voteOfSpeaker"] is None:
                continue
            vote_fact_total += 1
            fact = fact_store.fact_for_object(id_osoba, "VOTE_CAST", ballot_ref["ballotId"])
            if fact and fact.literal_value == ballot_ref["voteOfSpeaker"]:
                vote_fact_ok += 1
            else:
                vote_fact_problems.append("{}: BallotRef {} tvrdí {}, VOTE_CAST fakt {}".format(
                    message["messageId"], ballot_ref["ballotId"], ballot_ref["voteOfSpeaker"],
                    fact.literal_value if fact else "chybí"))
    report.add("VOTE_CAST fakt odpovídá BallotRef vystoupení", vote_fact_ok, vote_fact_total, vote_fact_problems)

    club_fact_ok = club_fact_total = 0
    club_fact_problems = []
    for ballot in ballots.values():
        if not ballot.date:
            continue
        for id_osoba, vote in ballot.votes.items():
            if not vote.club:
                continue
            club_fact_total += 1
            fact = fact_store.fact_at(id_osoba, "CLUB_MEMBERSHIP", ballot.date)
            if fact and fact.literal_value == vote.club:
                club_fact_ok += 1
            else:
                club_fact_problems.append("{}: hlasování uvádí klub {}, CLUB_MEMBERSHIP fakt {}".format(
                    vote.name, vote.club, fact.literal_value if fact else "chybí"))
    report.add("CLUB_MEMBERSHIP fakt odpovídá klubu u hlasování", club_fact_ok, club_fact_total, club_fact_problems)

    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Kontrola přesnosti stažených stenozáznamů")
    parser.add_argument("--schuze", type=int)
    parser.add_argument("--den", type=int)
    parser.add_argument("--vzorek", type=int, default=60,
                        help="kolik vystoupení ověřit proti běžným stránkám")
    args = parser.parse_args(argv)

    client = PspClient()
    if args.schuze:
        days = [d for d in list_days(client, TERM_PATH) if d.session == args.schuze]
        if args.den:
            days = [d for d in days if d.day == args.den]
        if not days:
            raise SystemExit("Takový jednací den není zveřejněný.")
        record = load_day(client, days[-1])
    else:
        record = latest_day(client, TERM_PATH)

    registry = Registry.load(client)
    print("Kontrola: {}".format(record.title or record.url))
    print()
    report = verify(client, record, registry, args.vzorek)
    print(report.render())
    print()
    print(client.summary())
    if report.ok():
        print("Všechny kontroly prošly.")
        return 0
    print("Některá kontrola selhala.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
