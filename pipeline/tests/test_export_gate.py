"""Test, že export_web.py odmítne neověřené doložení."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from verify_proof import verify_annotation


class TestExportGateRejectsUnverified:
    """
    Důkazní brána v export_web.py musí zastavit export, pokud
    verify_proof.verify_annotation vrátí chybu.

    Tohle testuje verify_annotation přímo — export_web.py ho volá
    přes verify_all_annotations, takže pokud verify_annotation odmítne,
    export se zastaví.
    """

    def test_missing_source_url_rejected(self):
        ann = {
            "proof": {
                "pastQuote": "Něco jsem řekl.",
                "pastDate": "2026-01-01",
                "pastContext": "Kontext",
                "sourceUrl": "",
            }
        }
        client = MagicMock()
        err = verify_annotation(ann, client)
        assert err is not None
        assert "sourceUrl" in err

    def test_missing_proof_rejected(self):
        ann = {}
        client = MagicMock()
        err = verify_annotation(ann, client)
        assert err is not None
        assert "proof" in err

    def test_missing_past_quote_rejected(self):
        ann = {
            "proof": {
                "pastQuote": "",
                "pastDate": "2026-01-01",
                "pastContext": "Kontext",
                "sourceUrl": "https://example.com",
            }
        }
        client = MagicMock()
        err = verify_annotation(ann, client)
        assert err is not None
        assert "pastQuote" in err

    def test_download_failure_rejected(self):
        ann = {
            "proof": {
                "pastQuote": "Citace z minulého projevu.",
                "pastDate": "2026-01-01",
                "pastContext": "Kontext",
                "sourceUrl": "https://www.psp.cz/test",
            }
        }
        client = MagicMock()
        client.get_text.side_effect = ConnectionError("síť nedostupná")
        err = verify_annotation(ann, client)
        assert err is not None
        assert "stáhnout" in err
