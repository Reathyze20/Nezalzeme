"""
Testy modulu audiovizuálního zarovnání (Pilíř C: WhisperX & Forced Alignment).
"""

from audio_alignment import AudioAlignmentEngine, AlignedSnippet


def test_estimate_span_window():
    engine = AudioAlignmentEngine(use_ml_model=False)
    text = "Vážený pane předsedající, dámy a pánové. Garantuji, že daň z příjmu nezvýšíme."
    target_start = text.index("Garantuji, že daň z příjmu nezvýšíme.")
    target_end = target_start + len("Garantuji, že daň z příjmu nezvýšíme.")

    start_sec, end_sec = engine.estimate_span_window(text, target_start, target_end, speech_start_seconds=100.0)

    # Výrok začíná po úvodních slovech (~41 znaků / 14.5 ≈ 2.8 s), s 2s rezervou předem
    assert start_sec > 98.0
    assert end_sec > start_sec + 2.0


def test_generate_media_evidence_dict():
    engine = AudioAlignmentEngine(use_ml_model=False)
    clean_text = "Úvodní slovo mluvčího. Odmítáme tento návrh zákona v celém rozsahu. Závěrečné slovo."
    target_start = clean_text.index("Odmítáme tento návrh zákona")
    target_end = target_start + len("Odmítáme tento návrh zákona v celém rozsahu.")

    media = engine.generate_media_evidence_dict(
        clean_text,
        target_start,
        target_end,
        speech_start_seconds=3600.0,
        archive_url="https://videoarchiv.psp.cz/playa.php?cast=1234",
    )

    assert "exactTimestampSeconds" in media
    assert media["exactTimestampSeconds"] >= 3598
    assert media["archiveUrl"] == "https://videoarchiv.psp.cz/playa.php?cast=1234"
    assert "isExact" in media
    assert "durationSeconds" in media
    assert media["durationSeconds"] > 0
