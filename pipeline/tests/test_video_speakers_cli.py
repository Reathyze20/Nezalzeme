"""
Testy `prepare_video_speakers.py` / `tag_video_speaker.py` (Fáze 6c) —
uložení anonymních mluvčích, že se přiřazením jméno neztratí při přeběhu
`prepare_video` znovu, a že `tag_speaker` mění jen zadanou dvojici.

Bez sítě/ML: `download_audio`/`SpeakerDiarizer.diarize` jsou dvojníci.
"""

import json

import pytest

import prepare_video_speakers as pvs
import tag_video_speaker as tvs
import voice_embedding as ve
from db import now_iso, open_engine_db


@pytest.fixture
def conn():
    return open_engine_db(":memory:")


class _FakeTranscriptClient:
    def __init__(self, transcript, info=None):
        self._transcript = transcript
        self._info = info or {"authorName": "Kanál X"}

    def get_transcript(self, video_url):
        return self._transcript

    def get_video_info(self, video_url):
        return self._info


class _FakeDiarizer:
    def __init__(self, turns):
        self._turns = turns

    def diarize(self, wav_path):
        return self._turns


def _transcript_two_speakers():
    return [
        {"text": "Ahoj, jsem host jedna.", "start": 0.0, "duration": 2.0},
        {"text": "A já host dva.", "start": 12.0, "duration": 2.0},
    ]


def _turns_two_speakers():
    return [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 10.0},
        {"speaker": "SPEAKER_01", "start": 10.0, "end": 20.0},
    ]


def test_prepare_video_stores_transcript_cache_and_anonymous_speakers(conn, monkeypatch):
    monkeypatch.setattr(pvs, "download_audio", lambda url, path: path)
    transcript_client = _FakeTranscriptClient(_transcript_two_speakers())
    diarizer = _FakeDiarizer(_turns_two_speakers())

    groups = pvs.prepare_video("https://youtube.com/watch?v=abc", "2026-01-15", conn, transcript_client, diarizer)

    assert set(groups.keys()) == {"SPEAKER_00", "SPEAKER_01"}
    cache_row = conn.execute(
        "SELECT medium, datum_videa, segments_json FROM video_transcript_cache WHERE video_url = ?",
        ("https://youtube.com/watch?v=abc",),
    ).fetchone()
    assert cache_row["medium"] == "YouTube · Kanál X"
    assert cache_row["datum_videa"] == "2026-01-15"
    assert len(json.loads(cache_row["segments_json"])) == 2

    speaker_rows = conn.execute(
        "SELECT speaker_label, id_osoba FROM video_speakers WHERE video_url = ?",
        ("https://youtube.com/watch?v=abc",),
    ).fetchall()
    assert len(speaker_rows) == 2
    assert all(row["id_osoba"] is None for row in speaker_rows)


def test_prepare_video_rerun_preserves_existing_tag(conn, monkeypatch):
    monkeypatch.setattr(pvs, "download_audio", lambda url, path: path)
    transcript_client = _FakeTranscriptClient(_transcript_two_speakers())
    diarizer = _FakeDiarizer(_turns_two_speakers())
    video_url = "https://youtube.com/watch?v=abc"

    pvs.prepare_video(video_url, "2026-01-15", conn, transcript_client, diarizer)
    assert tvs.tag_speaker(conn, video_url, "SPEAKER_00", "1") is True

    # Druhé zpracování stejného videa (např. oprava datumu) nesmí zrušit tag.
    pvs.prepare_video(video_url, "2026-01-15", conn, transcript_client, diarizer)
    row = conn.execute(
        "SELECT id_osoba FROM video_speakers WHERE video_url = ? AND speaker_label = ?",
        (video_url, "SPEAKER_00"),
    ).fetchone()
    assert row["id_osoba"] == "1"


def test_tag_speaker_only_affects_given_pair(conn, monkeypatch):
    monkeypatch.setattr(pvs, "download_audio", lambda url, path: path)
    transcript_client = _FakeTranscriptClient(_transcript_two_speakers())
    diarizer = _FakeDiarizer(_turns_two_speakers())
    video_url = "https://youtube.com/watch?v=abc"
    pvs.prepare_video(video_url, "2026-01-15", conn, transcript_client, diarizer)

    assert tvs.tag_speaker(conn, video_url, "SPEAKER_00", "1") is True
    rows = {r["speaker_label"]: r["id_osoba"] for r in conn.execute(
        "SELECT speaker_label, id_osoba FROM video_speakers WHERE video_url = ?", (video_url,)
    ).fetchall()}
    assert rows["SPEAKER_00"] == "1"
    assert rows["SPEAKER_01"] is None


def test_tag_speaker_returns_false_for_unknown_pair(conn):
    assert tvs.tag_speaker(conn, "https://youtube.com/watch?v=neexistuje", "SPEAKER_00", "1") is False


class _FakeEmbedder:
    def embed_wav(self, wav_path):
        return [1.0, 0.0]


def test_prepare_video_voice_suggestions_never_auto_tag_speaker(conn, monkeypatch):
    """
    Bezpečnostní pojistka (Fáze 6d): i když embedder/gold-set najdou
    'shodu', `video_speakers.id_osoba` zůstává NULL — hlasový návrh je jen
    text pro konzoli, nikdy se sám nezapíše jako potvrzení identity.
    """
    monkeypatch.setattr(pvs, "download_audio", lambda url, path: path)
    monkeypatch.setattr(ve, "extract_wav_clip", lambda src, out, start, duration: out)
    transcript_client = _FakeTranscriptClient(_transcript_two_speakers())
    diarizer = _FakeDiarizer(_turns_two_speakers())
    video_url = "https://youtube.com/watch?v=abc"

    conn.execute(
        "INSERT INTO voice_goldset (id_osoba, embedding_json, cast_id, source_moment, duration_seconds, produced_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("1", "[1.0, 0.0]", "4932", "2026-01-15T09:10:00", 20.0, now_iso()),
    )
    conn.commit()

    groups = pvs.prepare_video(
        video_url, "2026-01-15", conn, transcript_client, diarizer, embedder=_FakeEmbedder()
    )

    assert groups["SPEAKER_00"]["voiceSuggestions"][0][0] == "1"
    rows = conn.execute("SELECT id_osoba FROM video_speakers WHERE video_url = ?", (video_url,)).fetchall()
    assert all(row["id_osoba"] is None for row in rows)
