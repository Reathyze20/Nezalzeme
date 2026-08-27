"""Testy čistých funkcí v tribunal.py (Fáze 4)."""

import json

import pytest
from tribunal import (
    build_same_day_context,
    check_divergence,
    parse_arbiter_response,
    parse_defense_response,
    parse_prosecutor_response,
)


# --------------------------------------------------------------------------
# parse_prosecutor_response
# --------------------------------------------------------------------------

class TestParseProsecutorResponse:
    def test_valid_json(self):
        raw = json.dumps({
            "case": "Výrok popírá dřívější ochotu daně zvýšit.",
            "keyEvidence": ["citace z 2025-01-01", "hlasování č. 87115"],
        })
        result = parse_prosecutor_response(raw)
        assert result["case"] == "Výrok popírá dřívější ochotu daně zvýšit."
        assert len(result["keyEvidence"]) == 2

    def test_invalid_json_returns_empty(self):
        result = parse_prosecutor_response("NOT JSON")
        assert result["case"] == ""
        assert result["keyEvidence"] == []

    def test_non_dict_returns_empty(self):
        result = parse_prosecutor_response('"just a string"')
        assert result["case"] == ""


# --------------------------------------------------------------------------
# parse_defense_response
# --------------------------------------------------------------------------

class TestParseDefenseResponse:
    def test_valid_defense(self):
        raw = json.dumps({
            "passed": False,
            "defenseEvaluated": "Změnil se rozpočtový rámec.",
            "defensesConsidered": ["rámec", "tisky", "kontext"],
            "downgradeTo": "VALUE_SHIFT",
            "dismiss": False,
            "confidenceScore": 0.82,
        })
        result = parse_defense_response(raw)
        assert result["passed"] is False
        assert result["downgradeTo"] == "VALUE_SHIFT"
        assert len(result["defensesConsidered"]) == 3

    def test_defaults_on_invalid_json(self):
        result = parse_defense_response("INVALID")
        assert result["passed"] is True  # default: rozpor zůstává
        assert result["dismiss"] is False


# --------------------------------------------------------------------------
# parse_arbiter_response
# --------------------------------------------------------------------------

class TestParseArbiterResponse:
    def test_valid_arbiter(self):
        raw = json.dumps({
            "passed": True,
            "downgradeTo": None,
            "dismiss": False,
            "confidenceScore": 0.91,
            "arbiterRationale": "Obhajoba nedoložila změnu kontextu.",
        })
        result = parse_arbiter_response(raw)
        assert result["passed"] is True
        assert result["confidenceScore"] == 0.91
        assert "Obhajoba" in result["arbiterRationale"]


# --------------------------------------------------------------------------
# check_divergence
# --------------------------------------------------------------------------

class TestCheckDivergence:
    def test_weak_defense_flagged(self):
        prosecutor = {"case": "Rozpor existuje."}
        defense = {
            "passed": True,
            "defenseEvaluated": "Nic nenamítám.",
            "defensesConsidered": [],
        }
        assert check_divergence(prosecutor, defense) is not None

    def test_real_defense_not_flagged(self):
        prosecutor = {"case": "Rozpor existuje."}
        defense = {
            "passed": False,
            "defenseEvaluated": "Změnil se rozpočtový rámec.",
            "defensesConsidered": ["rámec", "pozměňovací návrh", "jiný bod pořadu"],
        }
        assert check_divergence(prosecutor, defense) is None

    def test_identical_texts_flagged(self):
        prosecutor = {"case": "Stejný text."}
        defense = {
            "passed": True,
            "defenseEvaluated": "Stejný text.",
            "defensesConsidered": ["a", "b", "c"],
        }
        assert check_divergence(prosecutor, defense) is not None


# --------------------------------------------------------------------------
# build_same_day_context
# --------------------------------------------------------------------------

class TestBuildSameDayContext:
    def test_window_includes_near_excludes_far(self):
        message = {"messageId": "m2", "timestamp": "14:20"}
        debate = {
            "messages": [
                message,
                {"messageId": "m1", "timestamp": "14:05", "speaker": "Blízký", "cleanText": "Předchozí bod."},
                {"messageId": "m3", "timestamp": "16:00", "speaker": "Daleko", "cleanText": "Mimo okno."},
            ],
        }
        context = build_same_day_context(message, debate, window_minutes=60)
        assert len(context) == 1
        assert context[0]["speaker"] == "Blízký"

    def test_no_timestamp_returns_empty(self):
        message = {"messageId": "m1", "timestamp": ""}
        debate = {
            "messages": [
                message,
                {"messageId": "m2", "timestamp": "14:00", "speaker": "X", "cleanText": "Y"},
            ],
        }
        assert build_same_day_context(message, debate) == []

    def test_self_excluded(self):
        message = {"messageId": "m1", "timestamp": "14:00"}
        debate = {"messages": [message]}
        assert build_same_day_context(message, debate) == []
