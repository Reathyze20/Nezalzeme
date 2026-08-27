"""
Videoarchiv Poslanecké sněmovny (`videoarchiv.psp.cz`) — Fáze 6.

Sněmovna nehostuje videozáznamy schůzí na YouTube, jak předpokládal
schválený plán, ale na vlastní infrastruktuře (`videoarchiv.psp.cz`,
vlastní `video.js` přehrávač, žádné přihlášení). Modul mapuje
`(sessionNumber, date)` na skutečný záznam jednacího dne: "cast" (subakce)
ID a přesný čas startu streamu toho konkrétního dne — ne celé, případně
vícedenní schůze.

`playa.php?cast=<id>` je oficiální, sdílitelná stránka přehrávače (má
vlastní `og:title`/`og:image` pro sdílení) — to je jediný odkaz, který
tenhle modul produkuje. Syrové mp4 segmenty (`video2/.../*.mp4`) jsou sice
veřejně dostupné bez přihlášení (ověřeno HTTP Range dotazem), ale modul je
nikdy nehotlinkuje přímo — přehrávání zůstává na oficiální stránce PSP.
"""

import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .client import PspClient

BASE = "https://videoarchiv.psp.cz"
_SCHUZE_NAME = re.compile(r"^(\d+)\.\s*sch[uů]ze\s+Poslaneck[ée]\s+[Ss]n[eě]movny", re.I)
_DT_FORMAT = "%d.%m.%Y %H:%M"


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, _DT_FORMAT)
    except ValueError:
        return None


def list_session_events(client: PspClient, obdobi: str) -> List[Dict[str, Any]]:
    """Záznamy `catname == "Jednání Poslanecké sněmovny"` pro dané volební období."""
    raw = client.get_text(BASE + "/akce_data.php")
    data = json.loads(raw)
    events = []
    for row in data.get("rows", []):
        if row.get("catname") != "Jednání Poslanecké sněmovny":
            continue
        if str(row.get("obdobi")) != str(obdobi):
            continue
        match = _SCHUZE_NAME.match(row.get("Name") or "")
        if not match:
            continue
        events.append({
            "eventId": row["Id"],
            "sessionNumber": int(match.group(1)),
            "name": row["Name"],
            "totalStart": _parse_dt(row.get("total_start")),
            "totalStop": _parse_dt(row.get("total_stop")),
        })
    return events


def list_day_casts(client: PspClient, event_id: str) -> List[Dict[str, Any]]:
    """Jednotlivé jednací dny ("cast"/subakce) uvnitř jedné schůze."""
    raw = client.get_text(BASE + "/subakce_data.php?Id={}".format(event_id))
    rows = json.loads(raw)
    casts = []
    for row in rows:
        casts.append({
            "castId": row["Id"],
            "start": _parse_dt(row.get("start")),
            "stop": _parse_dt(row.get("stop")),
        })
    return casts


def find_day_recording(
    client: PspClient, session_number: int, date_iso: str, obdobi: str
) -> Optional[Dict[str, str]]:
    """
    Najde záznam pro konkrétní jednací den daného čísla schůze.

    Vrací `{"castId", "streamStartedAt"}` (ISO 8601), nebo `None`, není-li
    spárováno. `streamStartedAt` je start streamu TOHO DNE, ne celé
    (případně vícedenní) schůze — přesně to, co potřebuje Offset Sync.
    """
    target_date = datetime.strptime(date_iso, "%Y-%m-%d").date()
    for event in list_session_events(client, obdobi):
        if event["sessionNumber"] != session_number:
            continue
        for cast in list_day_casts(client, event["eventId"]):
            if cast["start"] and cast["start"].date() == target_date:
                return {
                    "castId": str(cast["castId"]),
                    "streamStartedAt": cast["start"].strftime("%Y-%m-%dT%H:%M:%S"),
                }
    return None


def build_archive_url(cast_id: str) -> str:
    """Oficiální sdílitelná stránka přehrávače pro daný jednací den."""
    return "{}/playa.php?cast={}".format(BASE, cast_id)


if __name__ == "__main__":
    import sys

    client = PspClient()
    events = list_session_events(client, "10")
    print("nalezeno {} schůzí PS v období 10".format(len(events)))
    for event in sorted(events, key=lambda e: e["sessionNumber"])[:5]:
        print("  {}. schůze (eventId={}) {} -- {}".format(
            event["sessionNumber"], event["eventId"], event["totalStart"], event["totalStop"]))

    recording = find_day_recording(client, 10, "2026-03-03", "10")
    print("\n10. schůze, 2026-03-03 ->", recording)
    if recording:
        print("archiveUrl:", build_archive_url(recording["castId"]))
