"""
Testy klienta Hlídače Státu (Pilíř B: Integrace s REST API Hlídače Státu).
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

from psp.hlidac_client import HlidacClient, HistoricalRole, HlidacEnrichment


def test_hlidac_cache_initialization():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "test_cache.sqlite")
        client = HlidacClient(api_token="test_tok", cache_path=cache_path)
        assert os.path.exists(cache_path)

        # Test zápisu a čtení z cache
        client._save_to_cache("key1", {"foo": "bar"}, 200)
        cached = client._get_from_cache("key1")
        assert cached == {"foo": "bar"}
        assert client._get_from_cache("nonexistent") is None


def test_hlidac_without_token_returns_empty_when_not_cached():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "test_cache.sqlite")
        client = HlidacClient(api_token="", cache_path=cache_path)
        # Bez tokenu a bez cache neprovádí volání
        assert client.search_osoba("Neznámý Poslanec") == []
        assert client.enrich_speaker("Neznámý Poslanec") is None


def test_hlidac_enrichment_from_mock_response():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "test_cache.sqlite")
        client = HlidacClient(api_token="dummy_token", cache_path=cache_path)

        mock_search = [
            {"osobaId": "andrea-hoffmannova", "jmeno": "Andrea Hoffmannová"}
        ]
        mock_detail = {
            "osobaId": "andrea-hoffmannova",
            "jmeno": "Andrea Hoffmannová",
            "narozeni": "1980-05-12",
            "funkce": [
                {
                    "funkce": "Náměstkyně primátora",
                    "organizace": "Statutární město Ostrava",
                    "od": "2018",
                    "do": "2024",
                },
                {
                    "funkce": "Poslankyně",
                    "organizace": "Poslanecká sněmovna",
                    "od": "2021",
                },
            ],
            "angazma": [
                {"subjekt": "Dopravní podnik Ostrava a.s."},
                {"subjekt": "Ostravské komunikace a.s."},
            ],
        }

        with patch.object(client, "search_osoba", return_value=mock_search), \
             patch.object(client, "get_osoba_detail", return_value=mock_detail):

            enrichment = client.enrich_speaker("Andrea Hoffmannová")
            assert enrichment is not None
            assert enrichment.osoba_id == "andrea-hoffmannova"
            assert enrichment.profile_url == "https://www.hlidacstatu.cz/osoba/andrea-hoffmannova"
            assert len(enrichment.historical_roles) == 2
            assert enrichment.historical_roles[0].role == "Náměstkyně primátora"
            assert enrichment.historical_roles[0].organization == "Statutární město Ostrava"
            assert enrichment.corporate_ties_count == 2
            assert "Dopravní podnik Ostrava a.s." in enrichment.corporate_entities

            # Test serializace pro frontend dataset.json
            frontend_dict = client.enrichment_dict("Andrea Hoffmannová")
            assert frontend_dict is not None
            assert frontend_dict["osobaId"] == "andrea-hoffmannova"
            assert "historicalRoles" in frontend_dict
            assert frontend_dict["corporateTiesCount"] == 2
            assert frontend_dict["birthYear"] == 1980
