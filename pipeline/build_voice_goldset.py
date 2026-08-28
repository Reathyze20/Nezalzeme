"""
Vytvoření/aktualizace jednoho referenčního hlasového vzorku politika
(Fáze 6d) — vstup pro `voice_embedding.suggest_speakers`, nápovědu při
ručním tagování diarizovaných mluvčích ve videích (`tag_video_speaker.py`).

Operátor MUSÍ mít okno předem ověřené poslechem/sledováním (že v něm mluví
jen tenhle politik) — žádné strojové odhadování, kde přesně řeč začíná,
stejná disciplína jako `--datum-videa` v `prepare_video_speakers.py`.
`--cast-id`/`--stream-started-at` jsou stejné vstupy jako u vlastního
self-testu `psp/audio_align.py` (`__main__` blok) — segment videoarchivu
PSP a čas jeho startu.

    python pipeline/build_voice_goldset.py --osoba "Jméno Příjmení" \\
        --cast-id 4932 --stream-started-at "2026-01-15 09:00:00" \\
        --offset-seconds 22200 --duration-seconds 20

Znovupoužívá jen bezpečnou, ověřenou část `psp/audio_align.py` (stahování
segmentů videoarchivu) — NE `CzechForcedAligner`/`align_quote_to_stream`
(ASR + fuzzy hledání citace), ten modul je sám o sobě neověřený (viz jeho
vlastní "STAV OVĚŘENÍ"); stavět na něm gold-set hlasů by problém jen
skládalo navrch.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

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
from psp.audio_align import fetch_segment_audio, find_segment_for_moment, list_segments  # noqa: E402
from psp.client import PspClient  # noqa: E402
from psp.opendata import Registry  # noqa: E402
from voice_embedding import VoiceEmbedder  # noqa: E402


def build_goldset_sample(
    id_osoba: str,
    cast_id: str,
    stream_started_at: datetime,
    offset_seconds: int,
    duration_seconds: float,
    conn,
    client,
    embedder,
) -> bool:
    """
    Stáhne operátorem ověřené okno zvuku, spočítá otisk, uloží/přepíše
    řádek v `voice_goldset`. Vrátí `False`, když se segment videoarchivu
    kolem zadaného okamžiku nedohledá.
    """
    target_moment = stream_started_at + timedelta(seconds=offset_seconds)
    segments = list_segments(client, cast_id)
    segment = find_segment_for_moment(segments, target_moment)
    if segment is None:
        return False

    offset_into_segment = max(0.0, (target_moment - segment["start"]).total_seconds())
    with tempfile.TemporaryDirectory() as tmp_dir:
        wav_path = os.path.join(tmp_dir, "sample.wav")
        fetch_segment_audio(
            segment["url"], wav_path,
            offset_seconds=offset_into_segment, duration_seconds=duration_seconds,
        )
        embedding = embedder.embed_wav(wav_path)

    conn.execute(
        "INSERT INTO voice_goldset (id_osoba, embedding_json, cast_id, source_moment, duration_seconds, produced_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id_osoba) DO UPDATE SET "
        " embedding_json = excluded.embedding_json, cast_id = excluded.cast_id, "
        " source_moment = excluded.source_moment, duration_seconds = excluded.duration_seconds, "
        " produced_at = excluded.produced_at",
        (id_osoba, json.dumps(embedding), cast_id, target_moment.isoformat(), duration_seconds, now_iso()),
    )
    conn.commit()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osoba", required=True, help="Celé jméno politika")
    parser.add_argument("--cast-id", required=True, help="ID jednacího dne ve videoarchivu PSP (subakce)")
    parser.add_argument("--stream-started-at", required=True, help="YYYY-MM-DD HH:MM:SS, začátek streamu")
    parser.add_argument(
        "--offset-seconds", required=True, type=int,
        help="Kolik vteřin od začátku streamu ověřeně mluví jen tenhle politik",
    )
    parser.add_argument("--duration-seconds", required=True, type=float, help="Délka ověřeného okna")
    args = parser.parse_args()

    conn = open_engine_db()
    client = PspClient()
    registry = Registry.load(client)
    id_osoba = resolve_id_osoba(registry, args.osoba)
    if not id_osoba:
        print(f"„{args.osoba}\" nenalezen v registru — nic se nezměnilo.")
        return

    embedder = VoiceEmbedder()
    stream_started_at = datetime.strptime(args.stream_started_at, "%Y-%m-%d %H:%M:%S")
    ok = build_goldset_sample(
        id_osoba, args.cast_id, stream_started_at, args.offset_seconds, args.duration_seconds,
        conn, client, embedder,
    )
    if ok:
        print(f"gold-set uložen: {args.osoba} ({id_osoba}) z cast {args.cast_id}")
    else:
        print(f"segment videoarchivu pro cast {args.cast_id} kolem zadaného okamžiku nenalezen — nic se neuložilo.")


if __name__ == "__main__":
    main()
