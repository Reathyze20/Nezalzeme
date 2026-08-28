"""
Hlasové otisky (Fáze 6d) — asistence operátorovi při ručním tagování
diarizovaných mluvčích (`tag_video_speaker.py`), NIKDY náhrada za jeho
rozhodnutí. `VoiceEmbedder` (SpeechBrain ECAPA-TDNN,
`speechbrain/spkrec-ecapa-voxceleb` z HuggingFace Hubu, bez vlastního
tréninku) spočítá 192místný vektor z krátkého úseku zvuku; `suggest_speakers`
ho porovná kosinovou podobností s gold-setem známých hlasů
(`build_voice_goldset.py`) a vrátí seřazený seznam kandidátů — jen jako
nápovědu do konzole `prepare_video_speakers.py`. Výsledek se nikam neukládá
do `video_speakers` — `id_osoba` tam znamená výhradně "člověk potvrdil"
(viz komentář nad tou tabulkou v `db.py`); přidání strojového návrhu do
stejného sloupce by ten význam rozmazalo.
"""

import json
import math
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_wav_clip(
    src_wav_path: str, out_wav_path: str, start_seconds: float, duration_seconds: float
) -> str:
    """
    Ořízne LOKÁLNÍ WAV (`-ss`/`-t` na vstupní soubor, ne URL — jinak stejný
    vzorec jako `psp/audio_align.fetch_segment_audio`).
    """
    cmd = [
        _ffmpeg_exe(), "-y",
        "-ss", str(max(0.0, start_seconds)),
        "-i", src_wav_path,
        "-t", str(duration_seconds),
        "-vn", "-ac", "1", "-ar", "16000",
        out_wav_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg selhal ({}): {}".format(src_wav_path, result.stderr[-2000:]))
    return out_wav_path


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        raise ValueError("vektory různé délky ({} vs {})".format(len(a), len(b)))
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class VoiceEmbedder:
    """
    `speechbrain/spkrec-ecapa-voxceleb` — import `speechbrain`/`torchaudio`
    uvnitř `__init__`, aby zbytek modulu šel použít i bez těžkých ML
    závislostí nainstalovaných (stejný vzorec jako `CzechForcedAligner`
    v `psp/audio_align.py` a `SpeakerDiarizer` v `video_diarization.py`).
    """

    def __init__(self, model_name: str = "speechbrain/spkrec-ecapa-voxceleb") -> None:
        from speechbrain.inference.speaker import EncoderClassifier

        self.model_name = model_name
        self.classifier = EncoderClassifier.from_hparams(source=model_name)

    def embed_wav(self, wav_path: str) -> List[float]:
        import torchaudio

        waveform, sample_rate = torchaudio.load(wav_path)
        if sample_rate != 16000:
            raise ValueError("model očekává 16 kHz, dostal {}".format(sample_rate))
        embedding = self.classifier.encode_batch(waveform)
        return embedding.squeeze().tolist()


def load_goldset(conn) -> Dict[str, List[float]]:
    """Všechny hlasové otisky z `voice_goldset`, `{id_osoba: embedding}`."""
    rows = conn.execute("SELECT id_osoba, embedding_json FROM voice_goldset").fetchall()
    return {row["id_osoba"]: json.loads(row["embedding_json"]) for row in rows}


def _longest_turn(turns: List[Dict[str, Any]], speaker_label: str) -> Optional[Dict[str, Any]]:
    candidates = [t for t in turns if t["speaker"] == speaker_label]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t["end"] - t["start"])


def suggest_speakers(
    wav_path: str,
    turns: List[Dict[str, Any]],
    goldset: Dict[str, List[float]],
    embedder: "VoiceEmbedder",
    top_n: int = 3,
    max_clip_seconds: float = 20.0,
    min_clip_seconds: float = 1.0,
) -> Dict[str, List[Tuple[str, float]]]:
    """
    Pro každého anonymního mluvčího vezme jeho nejdelší souvislý diarizační
    úsek (ořízlý na `max_clip_seconds`), spočítá hlasový otisk a porovná ho
    kosinovou podobností se všemi vzorky gold-setu. Vrací
    `{speaker_label: [(id_osoba, skóre), ...]}`, sestupně, nejvýš `top_n`.
    Mluvčí bez dost dlouhého úseku i prázdný gold-set → chybí v odpovědi
    (ne chyba — hlasová nápověda je vždy nepovinná).
    """
    if not goldset:
        return {}

    speaker_labels = sorted({t["speaker"] for t in turns})
    suggestions: Dict[str, List[Tuple[str, float]]] = {}
    for speaker_label in speaker_labels:
        turn = _longest_turn(turns, speaker_label)
        if turn is None:
            continue
        duration = min(turn["end"] - turn["start"], max_clip_seconds)
        if duration < min_clip_seconds:
            continue
        with tempfile.TemporaryDirectory() as tmp_dir:
            clip_path = os.path.join(tmp_dir, "clip.wav")
            extract_wav_clip(wav_path, clip_path, turn["start"], duration)
            embedding = embedder.embed_wav(clip_path)
        scored = sorted(
            ((id_osoba, cosine_similarity(embedding, ref)) for id_osoba, ref in goldset.items()),
            key=lambda pair: pair[1],
            reverse=True,
        )
        suggestions[speaker_label] = scored[:top_n]
    return suggestions
