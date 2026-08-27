"""Testy čistých funkcí v claims.py (extrakce tvrzení, Fáze 2b)."""

import json

import pytest
from claims import parse_claims_response, validate_claim


class TestParseClaimsResponse:
    @pytest.fixture
    def message(self):
        return {
            "messageId": "test-001",
            "speaker": "Testovací poslanec",
            "cleanText": "Garantuji, že tato vláda nezvýší daně. Kolega tvrdil, že to je nemožné.",
            "source": {"idOsoba": "9999"},
        }

    def test_valid_claims_parsed(self, message):
        raw = json.dumps([
            {
                "subject": "tato vláda", "predicate": "nezvýší", "object": "daně",
                "timeFrame": "po celé volební období", "condition": "",
                "claimCategory": "STANCE_COMMITMENT", "speechAct": "OWN_STANCE",
                "rawSpan": "Garantuji, že tato vláda nezvýší daně.",
                "extractionConfidence": 0.92,
            },
        ])
        claims = parse_claims_response(raw, message)
        assert len(claims) == 1
        assert claims[0]["claimId"] == "test-001-c1"
        assert claims[0]["speechAct"] == "OWN_STANCE"
        assert claims[0]["sourceCharStart"] >= 0

    def test_missing_extraction_confidence_dropped(self, message):
        """Tvrzení bez povinného pole se zahodí — ne chyba, ne pád."""
        raw = json.dumps([
            {
                "subject": "x", "predicate": "y", "object": "z",
                "timeFrame": "NEURČENO", "condition": "",
                "claimCategory": "FACTUAL_CLAIM", "speechAct": "OWN_STANCE",
                "rawSpan": "Garantuji, že tato vláda nezvýší daně.",
                # chybí extractionConfidence
            },
        ])
        claims = parse_claims_response(raw, message)
        assert len(claims) == 0

    def test_nonexistent_rawspan_dropped(self, message):
        """rawSpan nenalezený v cleanText → tvrzení zahozeno."""
        raw = json.dumps([
            {
                "subject": "x", "predicate": "y", "object": "z",
                "timeFrame": "NEURČENO", "condition": "",
                "claimCategory": "FACTUAL_CLAIM", "speechAct": "OWN_STANCE",
                "rawSpan": "Tenhle úryvek v textu vůbec není.",
                "extractionConfidence": 0.9,
            },
        ])
        claims = parse_claims_response(raw, message)
        assert len(claims) == 0

    def test_unknown_category_dropped(self, message):
        raw = json.dumps([
            {
                "subject": "x", "predicate": "y", "object": "z",
                "timeFrame": "NEURČENO", "condition": "",
                "claimCategory": "INVENTED_CATEGORY", "speechAct": "OWN_STANCE",
                "rawSpan": "Garantuji, že tato vláda nezvýší daně.",
                "extractionConfidence": 0.9,
            },
        ])
        claims = parse_claims_response(raw, message)
        assert len(claims) == 0

    def test_invalid_json_returns_empty(self, message):
        claims = parse_claims_response("NENI JSON {{{", message)
        assert claims == []

    def test_non_list_returns_empty(self, message):
        claims = parse_claims_response('{"key": "value"}', message)
        assert claims == []

    def test_quoting_opponent_kept(self, message):
        """QUOTING_OPPONENT je platný speechAct — ne vyřazen, jen nepřipsán řečníkovi."""
        raw = json.dumps([
            {
                "subject": "kolega", "predicate": "tvrdil", "object": "je to nemožné",
                "timeFrame": "NEURČENO", "condition": "",
                "claimCategory": "FACTUAL_CLAIM", "speechAct": "QUOTING_OPPONENT",
                "rawSpan": "Kolega tvrdil, že to je nemožné.",
                "extractionConfidence": 0.85,
            },
        ])
        claims = parse_claims_response(raw, message)
        assert len(claims) == 1
        assert claims[0]["speechAct"] == "QUOTING_OPPONENT"


class TestValidateClaim:
    def test_valid_claim_no_errors(self):
        clean_text = "Nezvýšíme daně za žádných okolností."
        claim = {
            "claimId": "c1",
            "sourceCharStart": 0,
            "sourceCharEnd": len(clean_text),
            "rawSpan": clean_text,
            "claimCategory": "STANCE_COMMITMENT",
            "speechAct": "OWN_STANCE",
            "extractionConfidence": 0.9,
        }
        assert validate_claim(claim, clean_text) == []

    def test_bad_indices_reported(self):
        claim = {
            "claimId": "c1",
            "sourceCharStart": 999, "sourceCharEnd": 1005,
            "rawSpan": "test", "claimCategory": "FACTUAL_CLAIM",
            "speechAct": "OWN_STANCE", "extractionConfidence": 0.9,
        }
        errors = validate_claim(claim, "short text")
        assert len(errors) > 0
        assert "mimo rozsah" in errors[0]
