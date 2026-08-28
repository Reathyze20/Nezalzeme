"""Testy kompozitního skóre (scoring.py)."""

import pytest
from scoring import build_signals_from_pipeline, compute_composite_score


class TestCompositeScore:
    def test_strong_contradiction_above_threshold(self):
        score = compute_composite_score({
            "p_contradiction": 0.92,
            "retrieval_similarity": 0.85,
            "role_match": True,
            "model_self_assessment": 0.95,
        })
        assert score > 0.85

    def test_publish_threshold_reachable_on_strong_case(self):
        """Regresní test: ověřuje, že silný případ s retrievalem skutečně překročí PUBLISH_THRESHOLD (0.95)."""
        perfect = compute_composite_score({
            "p_contradiction": 1.0,
            "retrieval_similarity": 1.0,
            "role_match": True,
            "model_self_assessment": 1.0,
        })
        assert perfect >= 0.95

        strong = compute_composite_score({
            "p_contradiction": 0.98,
            "retrieval_similarity": 0.85,
            "role_match": True,
            "model_self_assessment": 0.98,
        })
        assert strong >= 0.95

    def test_weak_signal_below_published(self):
        score = compute_composite_score({
            "p_contradiction": 0.45,
            "retrieval_similarity": 0.30,
            "role_match": False,
            "model_self_assessment": 0.60,
        })
        assert score < 0.80

    def test_vote_mismatch_hard_fact_boosts(self):
        confirmed = compute_composite_score({
            "p_contradiction": 0.70,
            "vote_hard_fact": 1.0,
            "model_self_assessment": 0.80,
        }, is_vote_mismatch=True)
        unconfirmed = compute_composite_score({
            "p_contradiction": 0.70,
            "vote_hard_fact": 0.0,
            "model_self_assessment": 0.80,
        }, is_vote_mismatch=True)
        assert confirmed > unconfirmed

    def test_missing_signals_neutral(self):
        score = compute_composite_score({})
        assert 0.45 <= score <= 0.55

    def test_clamped_to_unit(self):
        score = compute_composite_score({
            "p_contradiction": 2.0,  # above 1
            "model_self_assessment": -0.5,  # below 0
        })
        assert 0.0 <= score <= 1.0

    def test_bool_role_match(self):
        with_match = compute_composite_score({
            "role_match": True,
        })
        without_match = compute_composite_score({
            "role_match": False,
        })
        assert with_match > without_match


class TestBuildSignals:
    def test_all_signals(self):
        signals = build_signals_from_pipeline(
            nli_scores={"CONTRADICTION": 0.87, "ENTAILMENT": 0.05, "NEUTRAL": 0.08},
            retrieval_score=0.72,
            tribunal_passed=True,
            arbiter_confidence=0.91,
            vote_fact_confirmed=True,
        )
        assert signals["p_contradiction"] == 0.87
        assert signals["retrieval_similarity"] == 0.72
        assert signals["role_match"] is True
        assert signals["model_self_assessment"] == 0.91
        assert signals["vote_hard_fact"] == 1.0

    def test_minimal_signals(self):
        signals = build_signals_from_pipeline()
        assert signals == {}

    def test_vote_fact_false(self):
        signals = build_signals_from_pipeline(vote_fact_confirmed=False)
        assert signals["vote_hard_fact"] == 0.0
