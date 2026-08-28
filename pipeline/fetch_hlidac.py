"""
Stahovač a materializátor profilů z Hlídače Státu pro Nezalžeme.cz.

Spouští se dávkově offline:
    python pipeline/fetch_hlidac.py

Výstupem je statický soubor `pipeline/data/hlidac_profiles.json`, který
následně `export_web.py` načítá bez jakéhokoliv síťového volání.
"""

import glob
import io
import json
import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psp.hlidac_client import HlidacClient  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PSP_DATA_DIR = os.path.join(DATA_DIR, "psp")
OUT_FILE = os.path.join(DATA_DIR, "hlidac_profiles.json")


def load_corpus_speakers() -> Dict[str, Dict[str, Any]]:
    """Vytáhne ze všech rozprav seznam unikátních politiků s jejich idOsoba."""
    speakers: Dict[str, Dict[str, Any]] = {}
    pattern = os.path.join(PSP_DATA_DIR, "*.json")
    for fpath in sorted(glob.glob(pattern)):
        with io.open(fpath, encoding="utf-8") as handle:
            debates = json.load(handle)
        for debate in debates:
            for msg in debate.get("messages", []):
                name = msg.get("speaker")
                if not name:
                    continue
                src = msg.get("source") or {}
                # Předsedající přeskakujeme, zajímají nás poslanci s vystoupeními
                speakers.setdefault(name, {
                    "name": name,
                    "idOsoba": src.get("idOsoba"),
                    "party": msg.get("party", ""),
                })
    return speakers


def main() -> int:
    speakers = load_corpus_speakers()
    if not speakers:
        print("V korpusu nebyli nalezeni žádní řečníci.", file=sys.stderr)
        return 1

    print(f"=== Stahování profilů z Hlídače Státu (nalezeno {len(speakers)} řečníků) ===")
    client = HlidacClient()

    if not client.api_token:
        print("UPOZORNĚNÍ: Není nastaven HLIDAC_STATU_TOKEN v .env.")
        print("Klient použije lokální mezipaměť (pokud existuje) nebo vrátí prázdné profily.\n")

    profiles: Dict[str, Any] = {}
    enriched = 0
    skipped = 0
    errors = 0

    for name, info in sorted(speakers.items(), key=lambda kv: kv[0]):
        try:
            dict_data = client.enrichment_dict(name, psp_id=info.get("idOsoba"))
            if dict_data:
                profiles[name] = dict_data
                enriched += 1
                roles_cnt = len(dict_data.get("historicalRoles", []))
                print(f"  ✓ {name}: {dict_data['osobaId']} ({roles_cnt} rolí, {dict_data['corporateTiesCount']} firem)")
            else:
                skipped += 1
        except Exception as exc:
            errors += 1
            print(f"  ✗ {name}: chyba ({exc})", file=sys.stderr)

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with io.open(OUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(profiles, handle, ensure_ascii=False, indent=2)

    print("\n=== Souhrn stahování ===")
    print(f"  Celkem řečníků:          {len(speakers)}")
    print(f"  Úspěšně obohaceno:       {enriched}")
    print(f"  Nenalezeno / nejednoznač: {skipped}")
    print(f"  Chyby:                   {errors}")
    print(f"  Uloženo do:              {OUT_FILE}")
    print(f"  Statistika mezipaměti:   {client.stats}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
