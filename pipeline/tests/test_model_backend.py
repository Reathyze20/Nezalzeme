"""Testy model backendu (model_backend.py) včetně GeminiBackend."""

import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from model_backend import (
    DEFAULT_GEMINI_MODEL,
    ApiBackend,
    GeminiBackend,
    clean_json_markdown,
)


class TestCleanJsonMarkdown:
    def test_plain_json_untouched(self):
        text = '{"passed": true, "score": 0.9}'
        assert clean_json_markdown(text) == text

    def test_markdown_code_fence_stripped(self):
        text = '```json\n{"passed": true}\n```'
        assert clean_json_markdown(text) == '{"passed": true}'

    def test_markdown_fence_without_language(self):
        text = '```\n[1, 2, 3]\n```'
        assert clean_json_markdown(text) == '[1, 2, 3]'

    def test_whitespace_around_fence(self):
        text = '  \n```json\n{"test": 1}\n```\n  '
        assert clean_json_markdown(text) == '{"test": 1}'


class TestGeminiBackend:
    @pytest.fixture
    def db(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE llm_cache (
                cache_key TEXT PRIMARY KEY,
                response_text TEXT NOT NULL,
                model_name TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );
        """)
        yield conn
        conn.close()

    def test_effective_model_maps_claude_to_gemini(self, db):
        backend = GeminiBackend(db, api_key="fake-key")
        assert backend.effective_model("claude-sonnet-5") == backend.default_model
        assert backend.effective_model("") == backend.default_model
        assert backend.effective_model("gemini-2.0-flash") == "gemini-2.0-flash"

    def test_missing_api_key_raises_helpful_error(self, db):
        with patch.dict(os.environ, {}, clear=True):
            backend = GeminiBackend(db, api_key=None)
            with pytest.raises(ValueError) as excinfo:
                backend._get_client()
            assert "GEMINI_API_KEY" in str(excinfo.value)
            assert ".env" in str(excinfo.value)

    def test_cache_hit_bypasses_api(self, db):
        backend = GeminiBackend(db, api_key="fake-key")
        # Pre-seed cache
        backend._to_cache("test-ck", '{"cached": true}', "gemini-2.5-flash")

        # Call with pre-seeded cache key
        result = backend.call("ROLE", "system", "payload", "gemini-2.5-flash", ck="test-ck")
        assert result == '{"cached": true}'
        assert backend.stats()["cache_hits"] == 1
        assert backend.stats()["api_calls"] == 0

    def test_cache_miss_calls_gemini_and_caches(self, db):
        backend = GeminiBackend(db, api_key="fake-key")

        # Mock the google.genai Client
        mock_response = MagicMock()
        mock_response.text = '```json\n{"gemini": "response"}\n```'

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch.object(backend, "_get_client", return_value=mock_client):
            result = backend.call("CLAIMS", "system prompt", "user payload", "claude-sonnet-5")

            # Markdown should be stripped
            assert result == '{"gemini": "response"}'
            assert backend.stats()["api_calls"] == 1

            # Check it was stored in db cache
            row = db.execute("SELECT * FROM llm_cache").fetchone()
            assert row is not None
            assert row["response_text"] == '{"gemini": "response"}'
            assert row["model_name"] == backend.default_model

            # Second call should be a cache hit
            second_result = backend.call("CLAIMS", "system prompt", "user payload", "claude-sonnet-5")
            assert second_result == '{"gemini": "response"}'
            assert backend.stats()["cache_hits"] == 1
            assert mock_client.models.generate_content.call_count == 1
