"""
Diarizace mluvčích v YouTube videích (Fáze 6c, rozšíření Rolového obratu).

TranscriptAPI.com (`psp/youtube_transcript.py`) vrací jen souvislý text s
timestampy, ŽÁDNOU informaci o tom, kdo mluví — potvrzeno přímo z REST
dokumentace (transcriptapi.com/docs/api/). U jednohlasého projevu to nevadí
(mluvčí = majitel kanálu), ale u tiskovky nebo diskuse s víc lidmi to bez
dalšího kroku nejde použít vůbec — bez diarizace by šlo výrok přiřadit ke
jménu jen odhadem LLM z kontextu, což je přesně to riziko špatné atribuce
pod skutečné jméno, kterému se má tenhle modul vyhnout, ne ho přidat.

Řešení: `pyannote.audio` provede diarizaci ČISTĚ z akustiky (kolik hlasů,
který úsek čí) — bez znalosti obsahu, bez hádání identity. Výsledkem jsou
anonymní štítky `SPEAKER_00`/`SPEAKER_01`/…, nikdy jméno.

Přiřazení jména zůstává vždy lidský krok: `tag_video_speaker.py` nastaví
`id_osoba` jednomu mluvčímu jednoho videa najednou, po přečtení/poslechu
ukázky (`group_by_speaker` k tomu dá `sampleText` + `totalSeconds`) — stejná
disciplína jako `promote_media_lead.py` u schvalování leadů. Dokud mluvčí
nemá `id_osoba`, jeho úseky se do extrakce citací (`media_role_flip.py`)
vůbec nezapojí.

Řetěz:
    stažení zvuku (yt-dlp + ffmpeg)      [download_audio]
    přepis s timestampy (transcriptapi)  [psp/youtube_transcript.py, mimo tenhle modul]
    diarizace (pyannote.audio)           [SpeakerDiarizer.diarize]
    sloučení podle času                  [merge_transcript_with_diarization]
    seskupení pro operátora              [group_by_speaker]

STAV OVĚŘENÍ: `download_audio`/`SpeakerDiarizer` jsou nové a nikdy neběžely
proti reálnému YouTube videu (chybí `HUGGINGFACE_TOKEN` s přijatými
podmínkami modelu `pyannote/speaker-diarization-3.1`) — než se použijí
naostro, ověřit na pár známých videích, že se štítky mluvčích shodují se
skutečností. `merge_transcript_with_diarization`/`group_by_speaker` jsou
čistá funkce nad daty a jsou pokryté testy bez potřeby sítě/ML modelu.
"""

import glob
import os
import subprocess
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# 1. Stažení zvuku
# --------------------------------------------------------------------------- #

def _ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def download_audio(
    video_url: str,
    out_path: str,
    user_agent: str = "nezalzeme.cz/0.1 (zpracovani verejne dostupnych youtube prepisu)",
) -> str:
    """
    Stáhne zvuk YouTube videa (`yt-dlp`) a převede na 16kHz mono WAV
    (`ffmpeg` přes `imageio-ffmpeg`, žádná systémová instalace) — formát,
    který vyžaduje `SpeakerDiarizer`. `yt_dlp` je importované uvnitř funkce,
    aby zbytek modulu šel použít i bez něj nainstalovaného.
    """
    import yt_dlp

    tmp_template = out_path + ".src.%(ext)s"
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": tmp_template,
        "quiet": True,
        "noplaylist": True,
        "http_headers": {"User-Agent": user_agent},
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    matches = glob.glob(out_path + ".src.*")
    if not matches:
        raise RuntimeError("yt-dlp nevytvořil žádný soubor pro {}".format(video_url))
    src_path = matches[0]

    cmd = [_ffmpeg_exe(), "-y", "-i", src_path, "-vn", "-ac", "1", "-ar", "16000", out_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(src_path)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg selhal ({}): {}".format(video_url, result.stderr[-2000:]))
    return out_path


# --------------------------------------------------------------------------- #
# 2. Diarizace: čistě z akustiky, žádná znalost obsahu ani identity
# --------------------------------------------------------------------------- #

class SpeakerDiarizer:
    """
    `pyannote/speaker-diarization-3.1` — vyžaduje `HUGGINGFACE_TOKEN` s
    přijatými podmínkami modelu (huggingface.co/pyannote/speaker-diarization-3.1).
    Import uvnitř `__init__`, aby zbytek modulu šel použít i bez
    torch/pyannote nainstalovaných (stejný vzorec jako `CzechForcedAligner`
    v `psp/audio_align.py`).
    """

    def __init__(self, hf_token: Optional[str] = None, model_name: str = "pyannote/speaker-diarization-3.1") -> None:
        from pyannote.audio import Pipeline

        token = hf_token or os.environ.get("HUGGINGFACE_TOKEN", "")
        if not token:
            raise RuntimeError(
                "HUGGINGFACE_TOKEN chybí — diarizace vyžaduje token s přijatými podmínkami modelu " + model_name
            )
        self.model_name = model_name
        self.pipeline = Pipeline.from_pretrained(model_name, use_auth_token=token)

    def diarize(self, wav_path: str) -> List[Dict[str, Any]]:
        """Vrátí úseky `{"speaker": "SPEAKER_00", "start": float, "end": float}` seřazené podle času."""
        diarization = self.pipeline(wav_path)
        turns = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            turns.append({"speaker": speaker, "start": float(turn.start), "end": float(turn.end)})
        turns.sort(key=lambda t: t["start"])
        return turns


# --------------------------------------------------------------------------- #
# 3. Sloučení přepisu s diarizací, seskupení pro operátora — čisté funkce
# --------------------------------------------------------------------------- #

def merge_transcript_with_diarization(
    transcript_segments: List[Dict[str, Any]], diarization_turns: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Každému textovému úseku z přepisu (`{"text", "start", "duration"}`, tvar
    transcriptapi.com) přiřadí mluvčího podle toho, do kterého diarizačního
    úseku spadá jeho začátek. Úsek mimo pokrytí diarizací (ticho, přeslech)
    dostane `speaker: None` — `group_by_speaker` ho nezapočítá, ať ho nikdo
    nepřipíše ke špatnému hlasu jen proto, že "musí patřit někomu".
    """
    out = []
    for seg in transcript_segments:
        start = seg.get("start", 0.0)
        speaker = None
        for turn in diarization_turns:
            if turn["start"] <= start < turn["end"]:
                speaker = turn["speaker"]
                break
        out.append({
            "speaker": speaker,
            "text": seg.get("text", ""),
            "start": start,
            "duration": seg.get("duration", 0.0),
        })
    return out


def group_by_speaker(merged_segments: List[Dict[str, Any]], sample_chars: int = 300) -> Dict[str, Dict[str, Any]]:
    """
    Seskupí sloučené úseky podle anonymního mluvčího — vstup pro
    `tag_video_speaker.py`: kolik mluvil (`totalSeconds`), ukázka textu
    k rozpoznání (`sampleText`), plný text + úseky pro pozdější extrakci
    citací, jakmile mluvčí dostane `id_osoba`.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for seg in merged_segments:
        speaker = seg["speaker"]
        if speaker is None:
            continue
        g = groups.setdefault(speaker, {"segments": [], "totalSeconds": 0.0})
        g["segments"].append(seg)
        g["totalSeconds"] += seg.get("duration", 0.0)

    for g in groups.values():
        full_text = " ".join(s["text"] for s in g["segments"])
        g["fullText"] = full_text
        g["sampleText"] = full_text[:sample_chars]

    return groups
