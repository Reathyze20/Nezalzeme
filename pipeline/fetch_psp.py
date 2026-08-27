"""
Stažení stenozáznamu Poslanecké sněmovny a jeho převod do modelu enginu.

    python pipeline/fetch_psp.py --posledni
    python pipeline/fetch_psp.py --schuze 29 --den 2
    python pipeline/fetch_psp.py --datum 2026-08-26 --out pipeline/data/psp
    python pipeline/fetch_psp.py --seznam

Výstupem je JSON ve tvaru `Debate[]` (viz `src/types/debate.ts`) s prázdnými
`annotations` – ty doplní až detektor. Bez `--obnovit` se používá disková
cache, takže opakované spuštění nejde znovu po síti.
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detector import validate_extracted_debate  # noqa: E402
from psp.build import build_debates, latest_day  # noqa: E402
from psp.client import PspClient  # noqa: E402
from psp.opendata import Registry  # noqa: E402
from psp.stenoprotokol import DayRecord, list_days, load_day  # noqa: E402

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "psp")
TERM_PATH = "eknih/2025ps"


def resolve_day(client: PspClient, args) -> DayRecord:
    if args.posledni:
        record = latest_day(client, TERM_PATH)
        if not record:
            raise SystemExit("Sněmovna nemá v období {} žádný zveřejněný zápis.".format(TERM_PATH))
        return record

    days = list_days(client, TERM_PATH)
    if args.schuze:
        candidates = [d for d in days if d.session == args.schuze]
        if not candidates:
            raise SystemExit("Schůze č. {} nemá zveřejněný stenozáznam.".format(args.schuze))
        if args.den:
            candidates = [d for d in candidates if d.day == args.den]
            if not candidates:
                raise SystemExit("Schůze č. {} nemá {}. jednací den.".format(args.schuze, args.den))
        return load_day(client, candidates[-1])

    if args.datum:
        wanted = datetime.strptime(args.datum, "%Y-%m-%d").date()
        # Datum není v indexu spolehlivě čitelné, hledá se od nejnovějšího
        # zápisu zpět – tím se u běžného dotazu na čerstvý den načte pár stran.
        for record in reversed(days):
            if load_day(client, record).date == wanted:
                return record
        raise SystemExit("K datu {} není zveřejněný stenozáznam.".format(args.datum))

    raise SystemExit("Zvol --posledni, --schuze N [--den D] nebo --datum RRRR-MM-DD.")


def command_list(client: PspClient, limit: int) -> int:
    days = list_days(client, TERM_PATH)
    print("Zveřejněných jednacích dnů: {}".format(len(days)))
    for record in days[-limit:]:
        load_day(client, record)
        print("  {:>3}. schůze, den {}  {}  {}".format(
            record.session, record.day, record.date or "?", record.url))
    print(client.summary())
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--posledni", action="store_true", help="poslední zveřejněný jednací den")
    parser.add_argument("--schuze", type=int, help="číslo schůze")
    parser.add_argument("--den", type=int, help="pořadí jednacího dne v rámci schůze")
    parser.add_argument("--datum", help="datum jednacího dne (RRRR-MM-DD)")
    parser.add_argument("--seznam", action="store_true", help="jen vypíše dostupné jednací dny")
    parser.add_argument("--limit", type=int, default=15, help="kolik dnů vypsat u --seznam")
    parser.add_argument("--out", default=DEFAULT_OUT, help="adresář pro výstupní JSON")
    parser.add_argument("--obnovit", action="store_true", help="obejde cache a stáhne znovu")
    args = parser.parse_args(argv)

    client = PspClient(refresh=args.obnovit)
    if args.seznam:
        return command_list(client, args.limit)

    record = resolve_day(client, args)
    registry = Registry.load(client)
    print("{}  ({})".format(record.title or record.url, record.date))
    print(registry.summary())

    debates = build_debates(client, record, registry)
    messages = sum(len(d["messages"]) for d in debates)
    characters = sum(len(m["cleanText"]) for d in debates for m in d["messages"])

    # Výstup je vstupem detektoru, takže musí projít týmž schématem jako to,
    # co detektor vrací. Nevalidní soubor se nezapisuje – tichý zápis rozbité
    # fixtury by se projevil až o dvě fáze dál.
    problems = []
    for debate in debates:
        ok, errors = validate_extracted_debate(debate)
        if not ok:
            problems.extend(errors)
    if problems:
        print("Výstup neodpovídá schématu enginu, nezapisuji:", file=sys.stderr)
        for problem in problems[:20]:
            print("  - {}".format(problem), file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    name = "schuze-{:03d}-den-{}-{}.json".format(
        record.session, record.day, record.date or "bez-data")
    path = os.path.join(args.out, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(debates, handle, ensure_ascii=False, indent=2)

    print("rozprav: {} | vystoupení: {} | {:,} znaků čistého textu".format(
        len(debates), messages, characters).replace(",", " "))
    for debate in debates:
        print("  - {} ({} vystoupení, hlasování: {})".format(
            debate["title"][:70], len(debate["messages"]),
            ", ".join(debate["source"]["ballotIds"]) or "žádné"))
    print("zapsáno: {}".format(path))
    print(client.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
