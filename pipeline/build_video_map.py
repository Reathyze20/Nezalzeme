"""
Generuje `src/data/psp/videoRecordings.json` — Fáze 6.

    python pipeline/build_video_map.py

Jediné místo, které spojuje scrapovaný korpus s reálným videozáznamem PSP
ČR (`psp.videoarchiv`, `videoarchiv.psp.cz` — vlastní infrastruktura
Sněmovny, ne YouTube). Nic si nevymýšlí: `find_day_recording` vrátí
`None`, není-li jednací den ve videoarchivu spárovatelný, a rozprava se
pak vynechá stejně, jako to dělalo prázdné `SESSION_RECORDINGS` předtím.
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psp.client import PspClient  # noqa: E402
from psp.videoarchiv import find_day_recording  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "psp")
OUT_FILE = os.path.join(
    os.path.dirname(__file__), "..", "src", "data", "psp", "videoRecordings.json"
)

#: `obdobi` ve videoarchivu = pořadové číslo volebního období, ne `id_organ`
#: (174) z `psp.opendata`. Sedí s naším "10. volební období".
TERM_OBDOBI = "10"


def main() -> int:
    client = PspClient()
    recordings = {}
    unmatched = []
    cache = {}

    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
    if not files:
        print("Žádná data v {}".format(DATA_DIR))
        return 1

    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as handle:
            debates = json.load(handle)
        for debate in debates:
            key = (debate["sessionNumber"], debate["date"])
            if key not in cache:
                cache[key] = find_day_recording(client, debate["sessionNumber"], debate["date"], TERM_OBDOBI)
            recording = cache[key]
            if recording is None:
                unmatched.append("{} ({}. schůze, {})".format(debate["debateId"], *key[::-1]))
                continue
            recordings[debate["debateId"]] = {
                "pspCastId": recording["castId"],
                "streamStartedAt": recording["streamStartedAt"],
                "sourceLabel": "videoarchiv.psp.cz",
            }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(recordings, handle, ensure_ascii=False, indent=2, sort_keys=True)

    print("spárováno {} rozprav z {} jednacích dnů".format(len(recordings), len(cache)))
    if unmatched:
        print("nespárováno ({}):".format(len(unmatched)))
        for item in unmatched[:10]:
            print("  -", item)
    print("zapsáno do", OUT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
