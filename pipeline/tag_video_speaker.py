"""
Ruční přiřazení jména jednomu diarizovanému mluvčímu jednoho videa
(Fáze 6c). Jediná věc, kterou dělá: `UPDATE video_speakers SET id_osoba`.

Stejná disciplína jako `promote_media_lead.py` — jeden mluvčí po druhém,
operátor si ukázku (`sample_text` z `prepare_video_speakers.py`) přečetl/
poslechl sám a rozpoznal hlas. Žádné hromadné tagování, žádný `--all`.

    python pipeline/tag_video_speaker.py --video-url <url> \
        --speaker SPEAKER_00 --osoba "Jméno Příjmení"
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import dotenv
    _root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _env_file = os.path.join(_root_dir, ".env")
    if os.path.exists(_env_file):
        dotenv.load_dotenv(_env_file)
    else:
        dotenv.load_dotenv()
except Exception:
    pass

from db import now_iso, open_engine_db  # noqa: E402
from media_role_flip import resolve_id_osoba  # noqa: E402
from psp.client import PspClient  # noqa: E402
from psp.opendata import Registry  # noqa: E402


def tag_speaker(conn, video_url: str, speaker_label: str, id_osoba: str) -> bool:
    cur = conn.execute(
        "UPDATE video_speakers SET id_osoba = ?, tagged_at = ? WHERE video_url = ? AND speaker_label = ?",
        (id_osoba, now_iso(), video_url, speaker_label),
    )
    conn.commit()
    return cur.rowcount > 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-url", required=True)
    parser.add_argument("--speaker", required=True, help="Štítek z prepare_video_speakers.py, např. SPEAKER_00")
    parser.add_argument("--osoba", required=True, help="Celé jméno politika")
    args = parser.parse_args()

    conn = open_engine_db()
    client = PspClient()
    registry = Registry.load(client)
    id_osoba = resolve_id_osoba(registry, args.osoba)
    if not id_osoba:
        print(f"„{args.osoba}\" nenalezen v registru — nic se nezměnilo.")
        return

    if tag_speaker(conn, args.video_url, args.speaker, id_osoba):
        print(f"označeno: {args.speaker} ({args.video_url}) = {args.osoba} ({id_osoba})")
    else:
        print(
            f"mluvčí {args.speaker} pro {args.video_url} neexistuje — "
            "spusť nejdřív pipeline/prepare_video_speakers.py."
        )


if __name__ == "__main__":
    main()
