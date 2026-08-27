"""
Dávkové stažení stenozáznamů PSP ČR za posledních 6 měsíců (únor 2026 – srpen 2026).

    python pipeline/fetch_half_year.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psp.client import PspClient
from psp.opendata import Registry
from psp.stenoprotokol import list_days, load_day
from psp.build import build_debates
from detector import validate_extracted_debate

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "psp")
TERM_PATH = "eknih/2025ps"

# Vybrané klíčové jednací dny pokrývající jednotlivé měsíce v okně únor–srpen 2026
TARGET_DAYS = [
    # Únor 2026
    (8, 1),   # 2026-02-03
    (7, 3),   # 2026-02-12
    # Březen 2026
    (10, 1),  # 2026-03-03
    (13, 1),  # 2026-03-24
    # Duben 2026
    (14, 1),  # 2026-04-14
    (14, 4),  # 2026-04-21
    # Květen 2026
    (16, 1),  # 2026-05-05
    (17, 4),  # 2026-05-29
    (20, 1),  # 2026-05-26
    # Červen 2026
    (21, 1),  # 2026-06-02
    (24, 1),  # 2026-06-23
    (24, 5),  # 2026-06-30
    # Červenec 2026
    (24, 9),  # 2026-07-07
    (25, 1),  # 2026-07-07
    (27, 1),  # 2026-07-10
    # Srpen 2026
    (29, 1),  # 2026-08-25
    (29, 2),  # 2026-08-26
]


def fetch_day(client: PspClient, registry: Registry, session: int, day_num: int, out_dir: str):
    days = list_days(client, TERM_PATH)
    candidates = [d for d in days if d.session == session and d.day == day_num]
    if not candidates:
        print(f"[-] Schůze {session}, den {day_num} nebyla v indexu nalezena, přeskakuji.")
        return False

    record = load_day(client, candidates[-1])
    date_str = str(record.date or "bez-data")
    name = f"schuze-{record.session:03d}-den-{record.day}-{date_str}.json"
    dest_path = os.path.join(out_dir, name)

    if os.path.exists(dest_path):
        print(f"[OK] Již existuje: {name}")
        return True

    print(f"[+] Stahuji: Schůze {record.session}, den {record.day} ({date_str})...")
    debates = build_debates(client, record, registry)

    problems = []
    for debate in debates:
        ok, errors = validate_extracted_debate(debate)
        if not ok:
            problems.extend(errors)
    if problems:
        print(f"[-] Nevalidní data pro schůzi {session} den {day_num}: {problems[:3]}")
        return False

    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(debates, f, ensure_ascii=False, indent=2)

    messages = sum(len(d["messages"]) for d in debates)
    print(f"[OK] Uloženo: {name} ({len(debates)} rozprav, {messages} vystoupení)")
    return True


def main():
    os.makedirs(DEFAULT_OUT, exist_ok=True)
    client = PspClient()
    registry = Registry.load(client)

    print(f"=== Stahování stenozáznamů PSP ČR za 6 měsíců (únor–srpen 2026) ===")
    print(f"Cílových jednacích dnů: {len(TARGET_DAYS)}")

    success_count = 0
    for session, day_num in TARGET_DAYS:
        try:
            if fetch_day(client, registry, session, day_num, DEFAULT_OUT):
                success_count += 1
        except Exception as e:
            print(f"[-] Chyba při stahování schůze {session} den {day_num}: {e}")

    print(f"\nHotovo: úspěšně připraveno {success_count}/{len(TARGET_DAYS)} dnů.")
    print(client.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
