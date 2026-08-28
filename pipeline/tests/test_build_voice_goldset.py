"""
Testy `build_voice_goldset.py` (Fáze 6d) — bez sítě/ML: `list_segments`/
`fetch_segment_audio` (z `psp/audio_align.py`) jsou monkeypatchnuté,
embedder je dvojník.
"""

import json
from datetime import datetime

import build_voice_goldset as bvg
from db import open_engine_db


class _FakeEmbedder:
    def __init__(self, vector):
        self._vector = vector

    def embed_wav(self, wav_path):
        return self._vector


def _segments():
    return [
        {
            "name": "a_20260115090000.mp4",
            "start": datetime(2026, 1, 15, 9, 0, 0),
            "url": "https://videoarchiv.psp.cz/a_20260115090000.mp4",
        },
        {
            "name": "a_20260115091000.mp4",
            "start": datetime(2026, 1, 15, 9, 10, 0),
            "url": "https://videoarchiv.psp.cz/a_20260115091000.mp4",
        },
    ]


def test_build_goldset_sample_stores_embedding(monkeypatch):
    monkeypatch.setattr(bvg, "list_segments", lambda client, cast_id: _segments())
    monkeypatch.setattr(bvg, "fetch_segment_audio", lambda url, path, offset_seconds, duration_seconds: path)

    conn = open_engine_db(":memory:")
    ok = bvg.build_goldset_sample(
        "1", "4932", datetime(2026, 1, 15, 9, 0, 0), 620, 20.0,
        conn, client=None, embedder=_FakeEmbedder([1.0, 0.0]),
    )
    assert ok is True

    row = conn.execute(
        "SELECT embedding_json, cast_id, duration_seconds FROM voice_goldset WHERE id_osoba = ?", ("1",)
    ).fetchone()
    assert json.loads(row["embedding_json"]) == [1.0, 0.0]
    assert row["cast_id"] == "4932"
    assert row["duration_seconds"] == 20.0


def test_build_goldset_sample_overwrites_existing_row(monkeypatch):
    monkeypatch.setattr(bvg, "list_segments", lambda client, cast_id: _segments())
    monkeypatch.setattr(bvg, "fetch_segment_audio", lambda url, path, offset_seconds, duration_seconds: path)

    conn = open_engine_db(":memory:")
    bvg.build_goldset_sample(
        "1", "4932", datetime(2026, 1, 15, 9, 0, 0), 620, 20.0, conn, None, _FakeEmbedder([1.0, 0.0])
    )
    bvg.build_goldset_sample(
        "1", "4932", datetime(2026, 1, 15, 9, 0, 0), 620, 30.0, conn, None, _FakeEmbedder([0.0, 1.0])
    )

    rows = conn.execute(
        "SELECT embedding_json, duration_seconds FROM voice_goldset WHERE id_osoba = ?", ("1",)
    ).fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0]["embedding_json"]) == [0.0, 1.0]
    assert rows[0]["duration_seconds"] == 30.0


def test_build_goldset_sample_returns_false_when_segment_not_found(monkeypatch):
    monkeypatch.setattr(bvg, "list_segments", lambda client, cast_id: [])

    conn = open_engine_db(":memory:")
    ok = bvg.build_goldset_sample(
        "1", "4932", datetime(2026, 1, 15, 9, 0, 0), 620, 20.0, conn, None, _FakeEmbedder([1.0, 0.0])
    )
    assert ok is False
    assert conn.execute("SELECT COUNT(*) AS n FROM voice_goldset").fetchone()["n"] == 0
