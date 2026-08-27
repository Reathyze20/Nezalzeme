"""Testy deterministické vrstvy v detector.py."""

import pytest
from detector import (
    CANONICAL_TYPES,
    PRESENTATION_TIERS,
    apply_confidence_gate,
    get_presentation_tier,
    nearest_occurrence,
    normalize_annotation,
    normalize_anomaly_type,
)


# --------------------------------------------------------------------------
# normalize_anomaly_type
# --------------------------------------------------------------------------

class TestNormalizeAnomalyType:
    def test_canonical_passthrough(self):
        for t in CANONICAL_TYPES:
            assert normalize_anomaly_type(t) == t

    def test_alias_time_contradiction(self):
        assert normalize_anomaly_type("TIME_CONTRADICTION") == "CONTRADICTION_TIME"

    def test_alias_factual_error(self):
        assert normalize_anomaly_type("FACTUAL_ERROR") == "FACTUAL_MISSTATEMENT"

    def test_unknown_returns_none(self):
        assert normalize_anomaly_type("FAKE_TYPE") is None

    def test_case_insensitive(self):
        assert normalize_anomaly_type("vote_mismatch") == "VOTE_MISMATCH"

    def test_strips_whitespace(self):
        assert normalize_anomaly_type("  VALUE_SHIFT  ") == "VALUE_SHIFT"


# --------------------------------------------------------------------------
# normalize_annotation
# --------------------------------------------------------------------------

class TestNormalizeAnnotation:
    def test_valid_annotation_passes(self, sample_annotation, sample_clean_text):
        result = normalize_annotation(sample_annotation, sample_clean_text)
        assert result is not None
        assert result["type"] == "CONTRADICTION_TIME"

    def test_alias_type_rewritten(self, sample_annotation, sample_clean_text):
        ann = dict(sample_annotation)
        ann["type"] = "TIME_CONTRADICTION"
        result = normalize_annotation(ann, sample_clean_text)
        assert result is not None
        assert result["type"] == "CONTRADICTION_TIME"

    def test_procedural_excluded(self, sample_annotation, sample_clean_text):
        ann = dict(sample_annotation)
        ann["claimCategory"] = "PROCEDURAL"
        result = normalize_annotation(ann, sample_clean_text)
        assert result is None

    def test_unknown_type_excluded(self, sample_annotation, sample_clean_text):
        ann = dict(sample_annotation)
        ann["type"] = "NONEXISTENT"
        result = normalize_annotation(ann, sample_clean_text)
        assert result is None

    def test_wrong_indices_repaired_via_nearest_occurrence(self, sample_clean_text):
        snippet = "nezvýší sazbu daně"
        ann = {
            "start": 999,
            "end": 999 + len(snippet),
            "targetSnippet": snippet,
            "type": "FACTUAL_ERROR",
            "severity": "MEDIUM",
            "shortBadgeLabel": "Test",
            "explanation": "Test",
            "proof": {"pastQuote": "x", "pastDate": "x", "pastContext": "x", "sourceUrl": "x"},
        }
        result = normalize_annotation(ann, sample_clean_text)
        assert result is not None
        actual = sample_clean_text[result["start"]:result["end"]]
        assert actual == snippet

    def test_missing_snippet_returns_none(self, sample_clean_text):
        ann = {
            "start": 0, "end": 10,
            "targetSnippet": "NEEXISTUJÍCÍ TEXT V DOKUMENTU",
            "type": "CONTRADICTION_TIME", "severity": "HIGH",
            "shortBadgeLabel": "x", "explanation": "x",
            "proof": {"pastQuote": "x", "pastDate": "x", "pastContext": "x", "sourceUrl": "x"},
        }
        result = normalize_annotation(ann, sample_clean_text)
        assert result is None

    def test_severity_default_medium(self, sample_annotation, sample_clean_text):
        ann = dict(sample_annotation)
        ann["severity"] = "BOGUS"
        result = normalize_annotation(ann, sample_clean_text)
        assert result is not None
        assert result["severity"] == "MEDIUM"


# --------------------------------------------------------------------------
# nearest_occurrence
# --------------------------------------------------------------------------

class TestNearestOccurrence:
    def test_single_occurrence(self):
        text = "AAAA daně BBBB"
        assert nearest_occurrence(text, "daně", None) == 5

    def test_nearest_to_hint(self):
        text = "daně ... daně ... daně"
        # occurrences at positions 0, 9, 18; hint=9 should pick second
        result = nearest_occurrence(text, "daně", 9)
        assert result == 9

    def test_empty_snippet_returns_none(self):
        assert nearest_occurrence("abc", "", None) is None

    def test_not_found_returns_none(self):
        assert nearest_occurrence("abc", "xyz", None) is None


# --------------------------------------------------------------------------
# get_presentation_tier
# --------------------------------------------------------------------------

class TestGetPresentationTier:
    def test_published(self):
        assert get_presentation_tier(0.97) == "PUBLISHED"

    def test_context_development(self):
        assert get_presentation_tier(0.85) == "CONTEXT_DEVELOPMENT"

    def test_dropped_below_threshold(self):
        assert get_presentation_tier(0.70) == "DROPPED"

    def test_boundary_published(self):
        assert get_presentation_tier(0.95) == "PUBLISHED"

    def test_boundary_context(self):
        assert get_presentation_tier(0.80) == "CONTEXT_DEVELOPMENT"

    def test_none_score_dropped(self):
        assert get_presentation_tier(None) == "DROPPED"

    def test_bool_score_dropped(self):
        assert get_presentation_tier(True) == "DROPPED"

    def test_string_score_dropped(self):
        assert get_presentation_tier("0.95") == "DROPPED"


# --------------------------------------------------------------------------
# apply_confidence_gate
# --------------------------------------------------------------------------

class TestApplyConfidenceGate:
    def _make_ann(self, score):
        return {
            "type": "CONTRADICTION_TIME", "severity": "HIGH",
            "shortBadgeLabel": "x", "explanation": "x",
            "confidenceScore": score,
            "start": 0, "end": 4, "targetSnippet": "test",
            "proof": {"pastQuote": "x", "pastDate": "x", "pastContext": "x", "sourceUrl": "x"},
        }

    def test_three_way_split(self):
        annotations = [self._make_ann(0.97), self._make_ann(0.85), self._make_ann(0.50)]
        published, context, dropped = apply_confidence_gate(annotations)
        assert len(published) == 1
        assert len(context) == 1
        assert len(dropped) == 1

    def test_tier_field_set(self):
        annotations = [self._make_ann(0.97)]
        published, _, _ = apply_confidence_gate(annotations)
        assert published[0]["presentationTier"] == "PUBLISHED"

    def test_empty_input(self):
        published, context, dropped = apply_confidence_gate([])
        assert published == [] and context == [] and dropped == []
