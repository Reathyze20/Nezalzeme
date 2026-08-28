"""
Testy čistých funkcí Fáze 6c (`pipeline/video_diarization.py`) — sloučení
přepisu s diarizací a seskupení pro operátora. Bez sítě, bez ML modelů:
`SpeakerDiarizer`/`download_audio` vyžadují torch/pyannote/yt-dlp a reálné
video, takže tady záměrně netestované (viz "STAV OVĚŘENÍ" v docstringu modulu).
"""

from video_diarization import group_by_speaker, merge_transcript_with_diarization


def test_merge_assigns_speaker_by_segment_start_time():
    transcript = [
        {"text": "První věta.", "start": 1.0, "duration": 2.0},
        {"text": "Druhá věta.", "start": 12.0, "duration": 2.0},
    ]
    turns = [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 10.0},
        {"speaker": "SPEAKER_01", "start": 10.0, "end": 20.0},
    ]
    merged = merge_transcript_with_diarization(transcript, turns)
    assert merged[0]["speaker"] == "SPEAKER_00"
    assert merged[1]["speaker"] == "SPEAKER_01"


def test_merge_leaves_speaker_none_outside_diarization_coverage():
    transcript = [{"text": "Mimo pokrytí.", "start": 25.0, "duration": 2.0}]
    turns = [{"speaker": "SPEAKER_00", "start": 0.0, "end": 10.0}]
    merged = merge_transcript_with_diarization(transcript, turns)
    assert merged[0]["speaker"] is None


def test_group_by_speaker_excludes_unassigned_segments():
    merged = [
        {"speaker": "SPEAKER_00", "text": "Ahoj.", "start": 0.0, "duration": 1.0},
        {"speaker": None, "text": "Ticho.", "start": 5.0, "duration": 1.0},
    ]
    groups = group_by_speaker(merged)
    assert list(groups.keys()) == ["SPEAKER_00"]


def test_group_by_speaker_sums_duration_and_joins_text():
    merged = [
        {"speaker": "SPEAKER_00", "text": "První.", "start": 0.0, "duration": 3.0},
        {"speaker": "SPEAKER_00", "text": "Druhé.", "start": 5.0, "duration": 4.0},
        {"speaker": "SPEAKER_01", "text": "Jiný hlas.", "start": 20.0, "duration": 2.0},
    ]
    groups = group_by_speaker(merged)
    assert groups["SPEAKER_00"]["totalSeconds"] == 7.0
    assert groups["SPEAKER_00"]["fullText"] == "První. Druhé."
    assert groups["SPEAKER_01"]["totalSeconds"] == 2.0


def test_group_by_speaker_sample_text_respects_char_limit():
    merged = [{"speaker": "SPEAKER_00", "text": "A" * 500, "start": 0.0, "duration": 1.0}]
    groups = group_by_speaker(merged, sample_chars=50)
    assert len(groups["SPEAKER_00"]["sampleText"]) == 50
