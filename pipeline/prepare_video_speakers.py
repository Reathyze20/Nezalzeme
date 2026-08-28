"""
Zpracování jednoho YouTube videa pro Rolový obrat (Fáze 6c) — stáhne zvuk,
získá přepis (TranscriptAPI.com) a diarizaci (pyannote.audio), uloží anonymní
mluvčí (`SPEAKER_00`, `SPEAKER_01`, …) do `video_speakers` k ručnímu
přiřazení jménem přes `tag_video_speaker.py`.

Datum publikace videa je POVINNÝ parametr, ne odhad — `/youtube/info` z
TranscriptAPI.com ho podle dokumentace nevrací (jen title/kanál/jazyky),
operátor ho přebírá přímo z YouTube (den, kdy video přidal kanál).

    python pipeline/prepare_video_speakers.py --video-url <url> \
        --datum-videa 2026-03-05

Bez `HUGGINGFACE_TOKEN` (s přijatými podmínkami modelu
pyannote/speaker-diarization-3.1) ani `TRANSCRIPTAPI_KEY` v `.env` skončí
hned se srozumitelnou hláškou.

Nepovinně (Fáze 6d): je-li nainstalovaný `speechbrain` a `voice_goldset`
(`pipeline/build_voice_goldset.py`) má aspoň jeden vzorek, ke každému
mluvčímu se do konzole vypíše nejbližší hlasová shoda jako NÁPOVĚDA —
`video_speakers.id_osoba` z toho nikdy nečerpá, tag zůstává výhradně na
`tag_video_speaker.py`.
"""

import argparse
import json
import os
import sys
import tempfile

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
from psp.youtube_transcript import TranscriptApiClient  # noqa: E402
from video_diarization import (  # noqa: E402
    SpeakerDiarizer,
    download_audio,
    group_by_speaker,
    merge_transcript_with_diarization,
)
from voice_embedding import VoiceEmbedder, load_goldset, suggest_speakers  # noqa: E402


def prepare_video(video_url, datum_videa, conn, transcript_client, diarizer, embedder=None):
    """
    Stáhne+přepíše+diarizuje video, uloží cache a anonymní mluvčí. Vrátí
    `group_by_speaker` výstup. Je-li dodaný `embedder` (Fáze 6d), každá
    skupina navíc dostane `voiceSuggestions` — jen NÁPOVĚDA do konzole,
    nikdy se neukládá do `video_speakers` (viz `tag_speaker` v
    `tag_video_speaker.py`, jediné místo, které smí `id_osoba` nastavit).
    """
    transcript = transcript_client.get_transcript(video_url)
    if not transcript:
        raise RuntimeError("TranscriptAPI nevrátilo přepis pro {}".format(video_url))

    info = transcript_client.get_video_info(video_url) or {}
    medium = "YouTube · {}".format(info.get("authorName")) if info.get("authorName") else "YouTube"

    with tempfile.TemporaryDirectory() as tmp_dir:
        wav_path = os.path.join(tmp_dir, "audio.wav")
        download_audio(video_url, wav_path)
        turns = diarizer.diarize(wav_path)

        voice_suggestions = {}
        if embedder is not None:
            goldset = load_goldset(conn)
            voice_suggestions = suggest_speakers(wav_path, turns, goldset, embedder)

    merged = merge_transcript_with_diarization(transcript, turns)
    conn.execute(
        "INSERT OR REPLACE INTO video_transcript_cache (video_url, medium, datum_videa, segments_json, produced_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (video_url, medium, datum_videa, json.dumps(merged, ensure_ascii=False), now_iso()),
    )
    conn.commit()

    groups = group_by_speaker(merged)
    for speaker_label, g in groups.items():
        g["voiceSuggestions"] = voice_suggestions.get(speaker_label, [])
        conn.execute(
            "INSERT INTO video_speakers (video_url, speaker_label, id_osoba, sample_text, total_seconds, "
            " tagged_at, produced_at) VALUES (?, ?, NULL, ?, ?, NULL, ?) "
            "ON CONFLICT(video_url, speaker_label) DO UPDATE SET "
            " sample_text = excluded.sample_text, total_seconds = excluded.total_seconds",
            (video_url, speaker_label, g["sampleText"], g["totalSeconds"], now_iso()),
        )
    conn.commit()
    return groups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-url", required=True)
    parser.add_argument("--datum-videa", required=True, help="YYYY-MM-DD, den kdy kanál video zveřejnil")
    args = parser.parse_args()

    transcriptapi_key = os.environ.get("TRANSCRIPTAPI_KEY", "")
    hf_token = os.environ.get("HUGGINGFACE_TOKEN", "")
    if not transcriptapi_key:
        print("TRANSCRIPTAPI_KEY chybí v .env — bez něj nemá tenhle nástroj co dělat.")
        return
    if not hf_token:
        print("HUGGINGFACE_TOKEN chybí v .env — diarizace vyžaduje token s přijatými "
              "podmínkami modelu pyannote/speaker-diarization-3.1.")
        return

    conn = open_engine_db()
    transcript_client = TranscriptApiClient(api_key=transcriptapi_key)
    diarizer = SpeakerDiarizer(hf_token=hf_token)

    embedder = None
    try:
        embedder = VoiceEmbedder()
    except Exception as exc:
        print(f"(hlasové otisky vypnuté, žádná nápověda k mluvčím: {exc})")

    groups = prepare_video(args.video_url, args.datum_videa, conn, transcript_client, diarizer, embedder=embedder)

    registry = None
    if any(g.get("voiceSuggestions") for g in groups.values()):
        from psp.client import PspClient  # noqa: E402 (jen když je co jménem rozpoznat)
        from psp.opendata import Registry  # noqa: E402

        registry = Registry.load(PspClient())

    print(f"{len(groups)} mluvčích nalezeno ve videu {args.video_url}:")
    for speaker_label, g in sorted(groups.items()):
        minutes = g["totalSeconds"] / 60
        preview = g["sampleText"][:150].replace("\n", " ")
        print(f"  {speaker_label}  ({minutes:.1f} min)")
        print(f"    „{preview}…\"")
        suggestions = g.get("voiceSuggestions") or []
        if suggestions and registry is not None:
            parts = []
            for id_osoba, score in suggestions:
                person = registry.people.get(id_osoba)
                name = person.full_name if person else id_osoba
                parts.append(f"{name} ({score:.2f})")
            print("    nejbližší shoda v gold-setu (jen nápověda): " + ", ".join(parts))
    print(
        "\nOznač mluvčí: python pipeline/tag_video_speaker.py --video-url <url> "
        "--speaker <label> --osoba \"Jméno Příjmení\""
    )


if __name__ == "__main__":
    main()
