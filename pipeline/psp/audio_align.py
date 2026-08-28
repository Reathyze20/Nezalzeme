"""
Forced alignment nad reálným zvukem PSP ČR (Fáze 7, WhisperX-style).

[EXPERIMENTÁLNÍ VÝZKUMNÝ MODUL — NENÍ ZAPOJEN DO PRODUKČNÍ PIPELINE]
Podmínka produkčního nasazení: ručně verifikovaný gold set ~20 časových kotev.
V produkci se používá deterministický aligner.py (OFFSET_SYNC / orientační čas).

`pipeline/aligner.align_message()` už cestu FORCED_ALIGNMENT plně
modeluje — přijímá `{id_anotace: přesná_vteřina}` a promítne ji do
`mediaEvidence`. Tenhle modul je to, co ten slovník skutečně vyrobí:

    1. `find_segment_for_moment`   – z `subfiles.php` najde mp4 segment
       videoarchivu PSP, který pokrývá odhadovaný okamžik (Offset Sync).
    2. `fetch_segment_audio`       – stáhne segment (jsou to reálná,
       veřejně dostupná data, ověřeno HTTP Range dotazem) a vytáhne z něj
       zvuk přes `ffmpeg` (přenosný binární přes `imageio-ffmpeg`, žádná
       systémová instalace).
    3. `CzechForcedAligner`        – wav2vec2 CTC model pro češtinu
       (`comodoro/wav2vec2-xls-r-300m-cs-250`) najde, kde v okně kolem
       odhadu known-text skutečně leží.

DŮLEŽITÉ ZJIŠTĚNÍ Z TESTOVÁNÍ: `torchaudio.functional.forced_align`
NENÍ vhodný nástroj na "najdi citaci v širším okně" — vynucuje monotónní
zarovnání přes CELÝ dodaný zvuk, takže dostane-li víc zvuku, než kolik
textu odpovídá (cizí řeč před/po citaci), stejně něco vrátí, jen typicky
špatně (první verze takhle spletla čas o celých 10 minut). `locate_quote`
proto místo toho okno nejdřív volně přepíše (ASR) a citaci hledá jako
nejdelší souvislou shodu slov — to je úloha vyhledávání v okně, ne
zarovnání 1:1, a `forced_align` by se hodil až na už nalezený, úzký úsek.

STAV OVĚŘENÍ: pipeline běží end-to-end nad reálným zvukem (Vít Rakušan,
5. schůze, 15.01.2026, `psp-5-3-4-165-33`) a trefuje se do správné
desetiminutové oblasti se správným obsahem (ASR rozeznává větnou stavbu
odpovídající stenoprotokolu). Přesnost na vteřiny ale NENÍ nezávisle
ověřená — dvě různá okna dala výsledky lišící se o cca 70–90 s a bez
poslechu skutečného zvuku nejde odsud rozhodnout, které je přesnější.
Přesně tohle schválený plán označuje jako nutný krok před nasazením:
"porovnat forced-alignment časy s ručně ověřenými na malém vzorku." Než
někdo výstupy poslechem ověří, `align_quote_to_stream` NEPOUŽÍVAT jako
zdroj `FORCED_ALIGNMENT` v produkční pipeline — jen jako podklad pro
ruční kontrolu.

Posouzení tónu/sarkasmu (`SpeechAct.RHETORICAL` ze zvuku) je DRUHÁ,
samostatná schopnost nad rámec forced alignmentu a tenhle modul ji
nevyrábí — potřebuje vlastní malý gold set (textový obsah tón nepokryje),
který v repozitáři zatím neexistuje. `assess_tone()` níž je proto jen
rozhraní, ne fungující klasifikátor.
"""

import os
import re
import subprocess
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .client import PspClient

VIDEOARCHIV_BASE = "https://videoarchiv.psp.cz"
DEFAULT_MODEL = "comodoro/wav2vec2-xls-r-300m-cs-250"

_SEGMENT_TS = re.compile(r"_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\.mp4$")


# -------------------------------------------------------------------------- #
# 1. Který segment pokrývá daný okamžik
# -------------------------------------------------------------------------- #

def list_segments(client: PspClient, cast_id: str) -> List[Dict[str, Any]]:
    """
    Segmenty jednoho jednacího dne (`subfiles.php?subakce=<cast_id>`),
    seřazené podle skutečného startu — ten je zakódovaný přímo v názvu
    souboru (`_YYYYMMDDHHMMSS.mp4`), ne odhadovaný.
    """
    import json

    raw = client.get_text("{}/subfiles.php?subakce={}".format(VIDEOARCHIV_BASE, cast_id))
    rows = json.loads(raw)
    segments = []
    for row in rows:
        name = row.get("name", "")
        match = _SEGMENT_TS.search(name)
        if not match:
            continue
        start = datetime(*(int(g) for g in match.groups()))
        segments.append({"name": name, "start": start, "url": "{}/{}".format(VIDEOARCHIV_BASE, name)})
    segments.sort(key=lambda s: s["start"])
    return segments


def find_segment_for_moment(segments: List[Dict[str, Any]], moment: datetime) -> Optional[Dict[str, Any]]:
    """Poslední segment, jehož start je <= `moment` — segmenty jsou desetiminutové bloky."""
    candidates = [s for s in segments if s["start"] <= moment]
    return max(candidates, key=lambda s: s["start"]) if candidates else None


# -------------------------------------------------------------------------- #
# 2. Stažení zvuku (ffmpeg přes imageio-ffmpeg, žádná systémová instalace)
# -------------------------------------------------------------------------- #

def _ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def fetch_segment_audio(
    segment_url: str,
    out_path: str,
    offset_seconds: float = 0.0,
    duration_seconds: Optional[float] = None,
    user_agent: str = "nezalzeme.cz/0.1 (zpracovani verejnych stenozaznamu PSP CR)",
) -> str:
    """
    Stáhne (streamuje) segment a vytáhne z něj zvuk jako 16kHz mono WAV —
    formát, který vyžaduje `CzechForcedAligner`. `offset_seconds`/
    `duration_seconds` omezí, kolik z desetiminutového segmentu se
    skutečně stahuje.
    """
    cmd = [_ffmpeg_exe(), "-y", "-user_agent", user_agent]
    if offset_seconds:
        cmd += ["-ss", str(max(0.0, offset_seconds))]
    cmd += ["-i", segment_url, "-vn", "-ac", "1", "-ar", "16000"]
    if duration_seconds:
        cmd += ["-t", str(duration_seconds)]
    cmd.append(out_path)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg selhal ({}): {}".format(segment_url, result.stderr[-2000:]))
    return out_path


# -------------------------------------------------------------------------- #
# 3. Forced alignment: kde v tom zvuku known-text skutečně leží
# -------------------------------------------------------------------------- #

class CzechForcedAligner:
    """
    Wav2vec2 CTC model pro češtinu + `torchaudio.functional.forced_align`.

    Načítá model jednou (~1.2 GB vah); import `torch`/`torchaudio`/
    `transformers` je schválně uvnitř `__init__`, aby zbytek modulu
    (`list_segments`, `find_segment_for_moment`) šel použít i bez těžkých
    ML závislostí nainstalovaných.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        self._torch = torch
        self.model_name = model_name
        self.processor = Wav2Vec2Processor.from_pretrained(model_name)
        self.model = Wav2Vec2ForCTC.from_pretrained(model_name)
        self.model.eval()

    def _emission(self, waveform, sample_rate: int):
        if sample_rate != 16000:
            raise ValueError("model očekává 16 kHz, dostal {}".format(sample_rate))
        inputs = self.processor(waveform, sampling_rate=16000, return_tensors="pt")
        with self._torch.no_grad():
            logits = self.model(inputs.input_values).logits
        return self._torch.log_softmax(logits, dim=-1)

    def _decode_words_with_times(self, log_probs, frame_duration: float) -> List[Dict[str, Any]]:
        """
        Volné (ne vynucené) CTC dekódování s časy jednotlivých slov —
        standardní "collapse opakování, pak odstraň blank" nad argmaxem.
        Na rozdíl od `forced_align` nepředpokládá, že celý úsek zvuku patří
        zadanému textu; jen řekne, co model slyšel a kdy.
        """
        pad_id = self.model.config.pad_token_id
        delim_id = self.processor.tokenizer.word_delimiter_token_id
        ids = log_probs[0].argmax(dim=-1).tolist()

        words: List[Dict[str, Any]] = []
        chars: List[str] = []
        start_frame: Optional[int] = None
        prev_id: Optional[int] = None

        def flush(end_frame: int) -> None:
            if chars:
                words.append({
                    "word": "".join(chars),
                    "start": start_frame * frame_duration,
                    "end": end_frame * frame_duration,
                })

        for frame_idx, token_id in enumerate(ids):
            if token_id == prev_id:
                continue  # CTC collapse: opakování stejného tokenu bez blank mezi nimi
            prev_id = token_id
            if token_id == pad_id:
                continue
            if token_id == delim_id:
                flush(frame_idx)
                chars, start_frame = [], None
                continue
            if start_frame is None:
                start_frame = frame_idx
            chars.append(self.processor.tokenizer.convert_ids_to_tokens([token_id])[0])
        flush(len(ids))
        return words

    def locate_quote(self, waveform, sample_rate: int, quote_text: str) -> Tuple[float, float]:
        """
        Najde, ve které části `waveform` leží `quote_text`.

        DŮLEŽITÉ: `torchaudio.functional.forced_align` tu záměrně NENÍ
        použitý jako hlavní nástroj — vynucuje monotónní zarovnání přes
        CELÝ dodaný zvuk, takže dostane-li delší okno, než kolik textu
        skutečně odpovídá (cizí řeč před/po citaci), stejně něco vrátí, jen
        typicky špatně (ověřeno: bez tohohle přístupu vracel čas o celé
        minuty vedle). Místo toho se okno nejdřív volně přepíše (ASR) a
        citace se hledá jako nejlepší souvislá shoda slov — to je úloha
        vyhledávání v širším okně, ne zarovnání 1:1.

        Vrací `(start_seconds, end_seconds)` relativně k začátku `waveform`.
        """
        import difflib

        log_probs = self._emission(waveform, sample_rate)
        frame_duration = waveform.shape[-1] / sample_rate / log_probs.shape[1]
        heard = self._decode_words_with_times(log_probs, frame_duration)
        if not heard:
            raise RuntimeError("ASR v okně nerozeznalo žádné slovo")

        heard_words = [w["word"] for w in heard]
        quote_words = re.findall(r"[\wáéíóúýčďěňřšťžů]+", quote_text.lower())
        if not quote_words:
            raise ValueError("quote_text po normalizaci nedal žádná slova")

        matcher = difflib.SequenceMatcher(None, heard_words, quote_words, autojunk=False)
        best_block = max(matcher.get_matching_blocks(), key=lambda block: block.size)
        if best_block.size == 0:
            raise RuntimeError("ASR výstup v okně nemá s citací žádnou shodu slov — okno pravděpodobně netrefilo správný segment")

        first = heard[best_block.a]
        last = heard[best_block.a + best_block.size - 1]
        return first["start"], last["end"]


# -------------------------------------------------------------------------- #
# 4. Sešití: odhad (Offset Sync) -> reálná vteřina relativně ke streamu
# -------------------------------------------------------------------------- #

def align_quote_to_stream(
    client: PspClient,
    cast_id: str,
    stream_started_at: datetime,
    estimated_speech_start_seconds: int,
    quote_text: str,
    aligner: "CzechForcedAligner",
    audio_cache_dir: str,
    lead_seconds: float = 60.0,
    search_window_seconds: float = 90.0,
) -> Optional[int]:
    """
    Odhadne skutečnou vteřinu citace zpřesněním Offset Syncu — NE
    ověřená FORCED_ALIGNMENT hodnota, viz "STAV OVĚŘENÍ" v hlavičce modulu.

    Kriticky důležité je stahovat úzké okno kolem odhadu, ne celý
    desetiminutový segment: `forced_align` vynucuje monotónní zarovnání
    přes CELÝ dodaný zvuk, takže když se mu dá 600 s zvuku pro ~1minutovou
    citaci, najde nějaké zarovnání i tak — jen typicky špatné, protože
    ho "natáhne" přes cizí řeč okolo. Tohle je ověřeno na vlastní kůži:
    dřívější verze bez `lead_seconds`/omezeného okna vracela hodnotu o
    celých 10 minut mimo. I s omezeným oknem se ale dvě různé volby okna
    lišily o ~70–90 s — proto zůstává tohle jen ODHAD, ne hotová hodnota
    pro `mediaEvidence.exactTimestampSeconds`, dokud ho někdo neověří
    poslechem. `lead_seconds`
    kompenzuje, že stenoprotokol má jen minutovou přesnost — skutečný
    začátek může být až minutu před odhadem, nikdy až minutu po něm.

    Stáhne `lead_seconds + search_window_seconds` zvuku kolem odhadovaného
    okamžiku a v něm forced alignmentem najde `quote_text`. Vrací vteřinu
    relativně ke `stream_started_at`, nebo `None`, nejde-li segment
    dohledat. Okno, které přesáhne přes hranici segmentu, se zatím
    neřeší (ořízne se koncem segmentu) — pro produkční nasazení by bylo
    potřeba slepit sousední segmenty.
    """
    import torchaudio

    target_moment = stream_started_at + timedelta(seconds=estimated_speech_start_seconds)
    window_start_moment = max(stream_started_at, target_moment - timedelta(seconds=lead_seconds))

    segments = list_segments(client, cast_id)
    segment = find_segment_for_moment(segments, window_start_moment)
    if segment is None:
        return None

    offset_into_segment = max(0.0, (window_start_moment - segment["start"]).total_seconds())
    os.makedirs(audio_cache_dir, exist_ok=True)
    wav_path = os.path.join(
        audio_cache_dir,
        "{}_{}_{}.wav".format(cast_id, segment["start"].strftime("%Y%m%d%H%M%S"), int(offset_into_segment)),
    )
    if not os.path.exists(wav_path):
        fetch_segment_audio(
            segment["url"], wav_path,
            offset_seconds=offset_into_segment,
            duration_seconds=lead_seconds + search_window_seconds,
        )

    waveform, sample_rate = torchaudio.load(wav_path)
    start_in_window, _end = aligner.locate_quote(waveform[0], sample_rate, quote_text)

    window_start_relative_to_stream = (window_start_moment - stream_started_at).total_seconds()
    return int(round(window_start_relative_to_stream + start_in_window))


# -------------------------------------------------------------------------- #
# Tón / sarkasmus — rozhraní, ne funkční klasifikátor (viz docstring modulu)
# -------------------------------------------------------------------------- #

def assess_tone(waveform, sample_rate: int) -> None:
    """
    NENÍ IMPLEMENTOVÁNO. Posouzení tónu/sarkasmu (přispívající do
    `SpeechAct.RHETORICAL`) potřebuje vlastní malý gold set, aby šlo
    vůbec poznat, jestli klasifikátor funguje — ten v repozitáři
    neexistuje. Nasazovat nevalidovaný soud o tónu skutečné řeči
    konkrétních politiků by bylo nezodpovědné; funkce záměrně vyvolává
    výjimku, aby ji nešlo omylem považovat za hotovou.
    """
    raise NotImplementedError(
        "posouzení tónu/sarkasmu vyžaduje vlastní gold set (viz docstring modulu) — zatím neexistuje"
    )


if __name__ == "__main__":
    # Self-test na reálném, ověřeném příkladu (vyžaduje síť a stažení modelu
    # při prvním spuštění — ~1,2 GB, pak cache HF Hubu). Cíl: Vít Rakušan,
    # 5. schůze, 15. 1. 2026, `psp-5-3-4-165-33`, `speechStartSeconds`
    # odpovídá Offset Sync odhadu z timestampu "15:10" a streamStartedAt
    # "09:00:00" -> 6*3600+10*60 = 22200 s.
    client = PspClient()
    aligner = CzechForcedAligner()

    quote = (
        "Děkuju za slovo. Dobrý den, pane premiére, dámy a pánové, kolegyně, kolegové, "
        "já tady stojím proto, abych upozornil na hazard, kterého se tato vláda dopouští "
        "nebo chce dopustit na stabilitě a profesionalitě naší státní správy"
    )
    seconds = align_quote_to_stream(
        client,
        cast_id="4932",
        stream_started_at=datetime(2026, 1, 15, 9, 0, 0),
        estimated_speech_start_seconds=6 * 3600 + 10 * 60,
        quote_text=quote,
        aligner=aligner,
        audio_cache_dir=os.path.join(os.path.dirname(__file__), "..", "data", "audio_cache"),
    )
    print("forced alignment: vteřina relativně ke streamu =", seconds)
    if seconds is not None:
        hh, rem = divmod(seconds, 3600)
        mm, ss = divmod(rem, 60)
        print("časový popisek: {}:{:02d}:{:02d}".format(hh, mm, ss) if hh else "{}:{:02d}".format(mm, ss))
