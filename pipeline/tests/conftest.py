"""Společné fixtury pro pytest testy pipeline."""

import json
import os
import sys

import pytest

# Pipeline moduly se importují z adresáře pipeline/, ne z kořene projektu.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import open_engine_db  # noqa: E402


@pytest.fixture
def engine_db():
    """In-memory engine.sqlite pro testy bez disku."""
    conn = open_engine_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def sample_clean_text():
    return "Garantuji, že tato vláda po celé volební období nezvýší sazbu daně z příjmu fyzických osob."


@pytest.fixture
def sample_annotation(sample_clean_text):
    return {
        "start": 0,
        "end": len(sample_clean_text),
        "targetSnippet": sample_clean_text,
        "type": "CONTRADICTION_TIME",
        "severity": "HIGH",
        "shortBadgeLabel": "Slib o dani",
        "explanation": "Rozpor s dřívějším vyjádřením.",
        "confidenceScore": 0.97,
        "proof": {
            "pastQuote": "Zvážíme navýšení sazby.",
            "pastDate": "2024-03-14",
            "pastContext": "Rozprava k daňovému balíčku",
            "sourceUrl": "https://www.psp.cz/eknih/2025ps/stenprot/006schuz/s006021.htm",
        },
    }


@pytest.fixture
def sample_message(sample_clean_text):
    return {
        "messageId": "test-msg-001",
        "speaker": "Ukázková poslankyně",
        "party": "ODU",
        "role": "poslanec",
        "timestamp": "14:00",
        "date": "2026-03-10",
        "cleanText": sample_clean_text,
        "hasAnomalies": False,
        "annotations": [],
        "source": {"idOsoba": "9999"},
    }
