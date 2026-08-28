"""
Testy `voice_embedding.py` (Fáze 6d) — jen čisté funkce (kosinová podobnost,
výběr nejdelšího úseku, seřazení návrhů) a čtení `voice_goldset`. Žádná
síť/ML: `VoiceEmbedder`/`extract_wav_clip` jsou vždy dvojníci.
"""

import json

import pytest

import voice_embedding as ve
from db import now_iso, open_engine_db


def test_cosine_similarity_identical_vectors():
    assert ve.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert ve.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    assert ve.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_returns_zero():
    assert ve.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_similarity_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        ve.cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


def test_load_goldset_reads_all_rows():
    conn = open_engine_db(":memory:")
    conn.execute(
        "INSERT INTO voice_goldset (id_osoba, embedding_json, cast_id, source_moment, duration_seconds, produced_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("1", json.dumps([1.0, 0.0]), "4932", "2026-01-15T09:10:00", 20.0, now_iso()),
    )
    conn.commit()
    assert ve.load_goldset(conn) == {"1": [1.0, 0.0]}


def test_load_goldset_empty_table_returns_empty_dict():
    conn = open_engine_db(":memory:")
    assert ve.load_goldset(conn) == {}


class _FakeEmbedderSequential:
    """Vrací embeddingy v pořadí volání — pořadí odpovídá pořadí mluvčích (sorted speaker_label)."""

    def __init__(self, vectors):
        self._vectors = list(vectors)

    def embed_wav(self, wav_path):
        return self._vectors.pop(0)


def test_suggest_speakers_ranks_closest_goldset_match(monkeypatch, tmp_path):
    calls = []

    def fake_extract(src, out, start, duration):
        calls.append((src, start, duration))
        return out

    monkeypatch.setattr(ve, "extract_wav_clip", fake_extract)

    wav_path = str(tmp_path / "audio.wav")
    turns = [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 5.0},
        {"speaker": "SPEAKER_00", "start": 20.0, "end": 21.0},  # kratší, nejlepší úsek je ten první
        {"speaker": "SPEAKER_01", "start": 5.0, "end": 8.0},
    ]
    goldset = {"1": [1.0, 0.0], "2": [0.0, 1.0]}
    embedder = _FakeEmbedderSequential([[1.0, 0.0], [0.0, 1.0]])

    suggestions = ve.suggest_speakers(wav_path, turns, goldset, embedder, top_n=2)

    assert suggestions["SPEAKER_00"][0][0] == "1"
    assert suggestions["SPEAKER_00"][0][1] == pytest.approx(1.0)
    assert suggestions["SPEAKER_01"][0][0] == "2"
    assert len(calls) == 2  # jeden klip na mluvčího, jen z nejdelšího úseku
    assert calls[0] == (wav_path, 0.0, 5.0)


def test_suggest_speakers_empty_goldset_returns_empty_without_calling_embedder():
    embedder = _FakeEmbedderSequential([])
    turns = [{"speaker": "SPEAKER_00", "start": 0.0, "end": 5.0}]
    assert ve.suggest_speakers("audio.wav", turns, {}, embedder) == {}


def test_suggest_speakers_skips_turn_shorter_than_minimum():
    embedder = _FakeEmbedderSequential([])
    turns = [{"speaker": "SPEAKER_00", "start": 0.0, "end": 0.2}]
    goldset = {"1": [1.0, 0.0]}
    assert ve.suggest_speakers("audio.wav", turns, goldset, embedder, min_clip_seconds=1.0) == {}
