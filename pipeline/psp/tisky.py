"""
Registr a parser sněmovních tisků (PSP tisky).

Stahuje otevřená data sněmovních tisků (`tisky.zip` z psp.cz) a páruje
číslo sněmovního tisku a fázi projednávání (1. / 2. / 3. čtení) z názvu
rozpravy.

Výstup slouží jako kontext pro:
  1. Tribunál (poslanec mluví v 2. čtení = návrh ještě lze měnit),
  2. Frontend (badge sněmovního tisku s přímým odkazem na psp.cz).
"""

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .client import PspClient
from .opendata import read_unl

_TISK_RE = re.compile(
    r"/(?:sn[eě]movn[ií]\s+)?tisk\s+(\d+)(?:/(\d+))?/",
    re.IGNORECASE,
)

_FAZE_PATTERNS = [
    (re.compile(r"t[rř]et[ií]\s+[cč]ten[ií]", re.I), "3. čtení"),
    (re.compile(r"druh[eé]\s+[cč]ten[ií]", re.I), "2. čtení"),
    (re.compile(r"prv[eé]\s+[cč]ten[ií]|1\.\s*[cč]ten[ií]", re.I), "1. čtení"),
    (re.compile(r"vysloven[ií]\s+ned[uů]v[eě]ry", re.I), "Hlasování o nedůvěře"),
    (re.compile(r"vysloven[ií]\s+d[uů]v[eě]ry", re.I), "Hlasování o důvěře"),
    (re.compile(r"[uú]stn[ií]\s+interpelace", re.I), "Ústní interpelace"),
    (re.compile(r"p[ií]semn[eé]\s+interpelace", re.I), "Písemné interpelace"),
]


@dataclass
class TiskInfo:
    id_tisk: str
    cislo: str
    organ: str
    zkraceny_nazev: str
    cely_nazev: str
    url: str


class TiskyRegistry:
    """Rejstřík sněmovních tisků pro rychlé dohledání podle čísla a období."""

    def __init__(self) -> None:
        # Klíč: (organ_id, cislo_tisku) -> TiskInfo
        self._tisky: Dict[tuple, TiskInfo] = {}

    @classmethod
    def load(cls, client: Optional[PspClient] = None) -> "TiskyRegistry":
        if client is None:
            client = PspClient()
        reg = cls()
        try:
            archive = client.opendata_archive("tisky.zip")
            reg._load_tisky(archive)
        except Exception:
            pass
        return reg

    def _load_tisky(self, archive: str) -> None:
        for cols in read_unl(archive, "tisky.unl"):
            if len(cols) < 16:
                continue
            id_tisk = cols[0]
            cislo = cols[3]
            organ = cols[7] if len(cols) > 7 else ""
            zkraceny = cols[10] if len(cols) > 10 else ""
            cely = cols[15] if len(cols) > 15 else zkraceny
            url_path = cols[19] if len(cols) > 19 else ""
            if url_path:
                url = "https://www.psp.cz" + url_path
            elif organ and cislo:
                url = f"https://www.psp.cz/sqw/historie.sqw?o={organ}&t={cislo}"
            else:
                url = ""

            info = TiskInfo(
                id_tisk=id_tisk,
                cislo=cislo,
                organ=organ,
                zkraceny_nazev=zkraceny,
                cely_nazev=cely,
                url=url,
            )
            if organ and cislo:
                self._tisky[(str(organ), str(cislo))] = info
            if cislo:
                # Záložní mapování bez ohledu na orgán (při neznámém volebním období)
                self._tisky.setdefault(("", str(cislo)), info)

    def get_tisk(self, cislo: str, organ: str = "174") -> Optional[TiskInfo]:
        """Vrátí informace o tisku pro dané období, případně ze záložního mapování."""
        return self._tisky.get((str(organ), str(cislo))) or self._tisky.get(("", str(cislo)))

    def all_for_organ(self, organ: str = "174") -> List[TiskInfo]:
        """Všechny tisky vedené pro dané volební období (bez záložních duplicit)."""
        organ = str(organ)
        return [info for (organ_key, _cislo), info in self._tisky.items() if organ_key == organ]

    def parse_debate_tisk(
        self, debate_title: str, organ: str = "174"
    ) -> Optional[Dict[str, Any]]:
        """
        Z názvu rozpravy vyextrahuje číslo tisku, fázi projednávání a dohledá
        metadata v registru.
        """
        if not debate_title:
            return None

        # 1. Číslo tisku
        m = _TISK_RE.search(debate_title)
        cislo = m.group(1) if m else None

        # 2. Fáze projednávání
        faze = None
        for pat, label in _FAZE_PATTERNS:
            if pat.search(debate_title):
                faze = label
                break

        if not cislo and not faze:
            return None

        tisk_info = self.get_tisk(cislo, organ) if cislo else None

        url = ""
        if tisk_info and tisk_info.url:
            url = tisk_info.url
        elif cislo:
            url = f"https://www.psp.cz/sqw/historie.sqw?o={organ}&t={cislo}"

        nazev = tisk_info.zkraceny_nazev if tisk_info else ""

        return {
            "cisloTisku": cislo,
            "faze": faze or "Obecná rozprava",
            "nazev": nazev,
            "url": url,
        }
