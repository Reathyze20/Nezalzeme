"""
FÁZE 6 – Časové zarovnání stenozáznamu s oficiálním videozáznamem PSP ČR.

Dvě úrovně přesnosti:
  1. OFFSET_SYNC      – vteřina dopočtená z času bloku ve stenozáznamu a času startu streamu.
  2. FORCED_ALIGNMENT – vteřina dodaná z časovaného přepisu pro konkrétní větu.

Video hostuje PSP ČR na vlastní infrastruktuře (`videoarchiv.psp.cz`,
`pipeline/psp/videoarchiv.py`), ne na YouTube — `archive_url` je vždy
oficiální sdílitelná stránka přehrávače (`playa.php?cast=...`) pro celý
jednací den, protože ten neumí seekovat na vteřinu přes URL parametr.
Přesnost proto nese jen zobrazený časový popisek, ne odkaz samotný.

TypeScript protějšek: `src/lib/media.ts` (stejné konstanty i vzorce).
"""

import re
from typing import Any, Dict, List, Optional

#: Průměrné tempo rozpravy ve znacích za sekundu (~140 slov/min, ~6,2 znaku na slovo).
CHARS_PER_SECOND = 14.5

_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?")

VIDEOARCHIV_BASE = "https://videoarchiv.psp.cz"


# --------------------------------------------------------------------------
# Odkazy
# --------------------------------------------------------------------------

def build_archive_url(cast_id: str) -> str:
    """Oficiální sdílitelná stránka přehrávače PSP pro daný "cast" (jednací den)."""
    return "{}/playa.php?cast={}".format(VIDEOARCHIV_BASE, cast_id)


# --------------------------------------------------------------------------
# Čas
# --------------------------------------------------------------------------

def parse_clock_to_seconds(value: str) -> Optional[int]:
    """"14:32" | "14:32:05" | "2023-09-05T09:00:00" -> sekundy od půlnoci."""
    if not value:
        return None
    time_part = value.split("T")[1] if "T" in value else value
    match = _CLOCK_RE.match(time_part)
    if not match:
        return None
    hours, minutes, seconds = match.group(1), match.group(2), match.group(3)
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds or 0)


def format_timestamp(total_seconds: int) -> str:
    """5284 -> "1:28:04" (pod hodinu "12:31")."""
    s = max(0, int(total_seconds))
    hours, remainder = divmod(s, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return "{}:{:02d}:{:02d}".format(hours, minutes, seconds)
    return "{}:{:02d}".format(minutes, seconds)


def offset_sync_seconds(block_timestamp: str, stream_started_at: str) -> Optional[int]:
    """
    Offset Sync – převede čas bloku ve stenozáznamu na vteřinu ve streamu.
    Vrací None, začíná-li blok před startem streamu nebo jsou-li vstupy nečitelné.
    """
    block = parse_clock_to_seconds(block_timestamp)
    start = parse_clock_to_seconds(stream_started_at)
    if block is None or start is None:
        return None
    delta = block - start
    return delta if delta >= 0 else None


def estimate_claim_offset_seconds(char_start: int) -> int:
    """Dopočet vteřiny věty uvnitř vystoupení podle znakové pozice v `cleanText`."""
    return int(round(max(0, char_start) / CHARS_PER_SECOND))


# --------------------------------------------------------------------------
# Sestavení metadat
# --------------------------------------------------------------------------

def build_stream_metadata(
    cast_id: str,
    stream_started_at: str,
    block_timestamp: str,
) -> Dict[str, Any]:
    """
    Metadata vystoupení pro `detector.format_llm_input` a pro pole `media`
    v datovém modelu frontendu.
    """
    if not cast_id:
        return {"pspCastId": None, "speechStartSeconds": 0, "alignment": "UNPAIRED"}

    offset = offset_sync_seconds(block_timestamp, stream_started_at)
    if offset is None:
        return {"pspCastId": None, "speechStartSeconds": 0, "alignment": "UNPAIRED"}

    return {
        "pspCastId": cast_id,
        "speechStartSeconds": offset,
        "alignment": "OFFSET_SYNC",
        "streamStartedAt": stream_started_at,
        "archiveUrl": build_archive_url(cast_id),
    }


def build_media_evidence(
    media: Dict[str, Any],
    char_start: int,
    exact_timestamp_seconds: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Sestaví `mediaEvidence` pro jednu anomálii.

    `exact_timestamp_seconds` z forced alignmentu má přednost; jinak se vteřina
    dopočte z pozice věty ve `cleanText` a je označena jako orientační.
    `archiveUrl` je pro celé vystoupení stejný jako v `media` – přehrávač PSP
    neumí seekovat na vteřinu přes URL, jen zobrazená vteřina se liší podle přesnosti.
    """
    cast_id = media.get("pspCastId")
    if not cast_id:
        return None

    is_exact = exact_timestamp_seconds is not None
    seconds = (
        int(exact_timestamp_seconds)
        if is_exact
        else int(media.get("speechStartSeconds", 0)) + estimate_claim_offset_seconds(char_start)
    )

    return {
        "exactTimestampSeconds": seconds,
        "archiveUrl": media.get("archiveUrl") or build_archive_url(cast_id),
        "isExact": is_exact,
    }


def align_message(
    message: Dict[str, Any],
    cast_id: str,
    stream_started_at: str,
    forced_alignment: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    Doplní vystoupení o `media` a každé jeho anotaci o `mediaEvidence`.

    `forced_alignment` je volitelná mapa {id_anotace: vteřina} z časovaného přepisu.
    Vrací novou kopii, vstup nemění.
    """
    media = build_stream_metadata(cast_id, stream_started_at, message.get("timestamp", ""))
    aligned = dict(message)
    aligned["media"] = media

    annotations: List[Dict[str, Any]] = []
    forced_count = 0
    for ann in message.get("annotations", []):
        updated = dict(ann)
        exact = (forced_alignment or {}).get(ann.get("id"))
        evidence = build_media_evidence(media, ann.get("start", 0), exact)
        if evidence:
            updated["mediaEvidence"] = evidence
        if exact is not None:
            forced_count += 1
        annotations.append(updated)

    # Stav zarovnání popisuje celé vystoupení. Kdyby ho na FORCED_ALIGNMENT
    # přepnula jediná zarovnaná věta, UI by u zbylých odhadnutých časů
    # hlásilo "přesný čas". Povyšujeme proto až při úplném zarovnání.
    if annotations and forced_count == len(annotations):
        aligned["media"] = dict(media, alignment="FORCED_ALIGNMENT")

    aligned["annotations"] = annotations
    return aligned


if __name__ == "__main__":
    message = {
        "messageId": "msg_001",
        "timestamp": "14:32",
        "cleanText": "Postoj klubu k valorizaci se nezměnil. Pro navržený škrt ruku nezvedneme.",
        "annotations": [
            {"id": "a1", "start": 0, "end": 37, "targetSnippet": "Postoj klubu k valorizaci se nezměnil."},
            {"id": "a2", "start": 38, "end": 72, "targetSnippet": "Pro navržený škrt ruku nezvedneme."},
        ],
    }

    aligned = align_message(message, "5518", "09:00", forced_alignment={"a2": 20150})

    print("stav zarovnání:", aligned["media"]["alignment"])
    for ann in aligned["annotations"]:
        evidence = ann["mediaEvidence"]
        print("{}  {}  {}  {}".format(
            ann["id"],
            format_timestamp(evidence["exactTimestampSeconds"]),
            "přesný" if evidence["isExact"] else "orientační",
            evidence["archiveUrl"],
        ))
