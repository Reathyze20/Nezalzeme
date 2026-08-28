"""
Zdrojová důvěryhodnostní vrstva pro Rolový obrat z médií (Fáze 6e).

Seznam domén převzatý z `aicenter/FactCheckAgent` (sestaveného ve
spolupráci s Demagog.cz nad reálnými českými politickými zdroji, ověřeno
přímo ze zdroje) — `pipeline/data/source_ranking.csv`. Řadí často viděné
české mediální domény do 5 stupňů důvěryhodnosti; stupeň 4 a 5 se v
`media_role_flip.py` blokují ještě před stažením článku, aby se citace pod
skutečným jménem politika nikdy neopřela o bulvár, názorový server, nebo
cizí parafrázi (Wikipedia, Demagog.cz) místo primárního zdroje.

Rozšiřovat seznam domén jen po stejném ověření jako u zbytku projektu —
needitovat bez rozmyslu, viz zdůvodnění per doména v plánu.
"""

import csv
import os
from typing import Dict, Optional

MAX_ALLOWED_TIER = 3  # stupeň 4 a 5 se blokují (rozhodnuto s uživatelem)

_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "source_ranking.csv")

_ranking_cache: Optional[Dict[str, int]] = None


def _load_ranking() -> Dict[str, int]:
    global _ranking_cache
    if _ranking_cache is not None:
        return _ranking_cache

    ranking: Dict[str, int] = {}
    with open(_CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ranking[row["domain"].strip().lower()] = int(row["tier"])
    _ranking_cache = ranking
    return ranking


def tier_for_url(url: str) -> Optional[int]:
    """
    Doména z `url` (bez `www.`) -> tier. Nejdřív přesná shoda hostname
    (řeší např. `ct24.ceskatelevize.cz` odlišně od `ceskatelevize.cz` —
    obě jsou v seznamu zvlášť). Bez přesné shody zkusí postupně kratší
    rodičovské domény (`foo.denik.cz` -> `denik.cz`). Nenalezeno -> `None`
    (neznámá doména prochází beze změny — seznam je blacklist/whitelist
    hybrid, ne uzavřený výčet).
    """
    import urllib.parse

    ranking = _load_ranking()
    host = urllib.parse.urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None

    if host in ranking:
        return ranking[host]

    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in ranking:
            return ranking[parent]
    return None


def is_source_allowed(url: str, max_tier: int = MAX_ALLOWED_TIER) -> bool:
    """`True` pro neznámou doménu i pro tier <= max_tier."""
    tier = tier_for_url(url)
    return tier is None or tier <= max_tier
