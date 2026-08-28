"""
Schválení jednoho leadu z `media_role_flip` k veřejné publikaci (Fáze 6b).

Jediná věc, kterou tenhle skript dělá: nastaví `schvaleno = 1` pro JEDEN
`--lead-id`. Žádné `--all`, žádné hromadné schvalování — schválení je akt
jednoho člověka, který si přečetl `zdroj_url` (vidět v `/interni/prehled`),
nad jedním leadem. Teprve schválené záznamy `export_web.py`
(`verify_media_role_flip`) zahrne do `dataset.json`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import open_engine_db  # noqa: E402
from media_role_flip import approve_lead  # noqa: E402


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lead-id", required=True, help="`id` z /interni/prehled -> rolovyObrat.")
    args = parser.parse_args()

    conn = open_engine_db()
    if approve_lead(conn, args.lead_id):
        print(f"schváleno: {args.lead_id} — objeví se v dataset.json po dalším `python pipeline/export_web.py`.")
    else:
        print(f"lead {args.lead_id} v media_role_flip neexistuje — nic se nezměnilo.")


if __name__ == "__main__":
    main()
