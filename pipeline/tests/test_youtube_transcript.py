"""
Testy `pipeline/psp/youtube_transcript.py` — cache, chování bez klíče,
parsování odpovědí do interního tvaru. Žádná síť: cache se sype přímo,
`_call` se u testů bez klíče nikdy nepokusí o HTTP.
"""

import json
import sqlite3

import pytest

from psp.youtube_transcript import TranscriptApiClient


@pytest.fixture
def client(tmp_path):
    return TranscriptApiClient(api_key="test-key", cache_path=str(tmp_path / "cache.sqlite"))


def _seed_cache(client, url, payload):
    conn = sqlite3.connect(client.cache_path)
    conn.execute(
        "INSERT OR REPLACE INTO transcriptapi_responses VALUES (?, ?, ?)",
        (url, json.dumps(payload, ensure_ascii=False), __import__("time").time()),
    )
    conn.commit()
    conn.close()


def test_no_key_returns_none_without_network():
    client = TranscriptApiClient(api_key="", cache_path=":memory:")
    assert client.get_transcript("https://youtube.com/watch?v=abc") is None


def test_get_transcript_reads_from_cache(client):
    url = "GET:https://transcriptapi.com/api/v2/youtube/transcript?video_url=abc&format=json&include_timestamp=true"
    _seed_cache(client, url, {
        "video_id": "abc", "language": "cs",
        "transcript": [{"text": "Ahoj.", "start": 0.0, "duration": 1.2}],
    })
    out = client.get_transcript("abc")
    assert out == [{"text": "Ahoj.", "start": 0.0, "duration": 1.2}]


def test_get_transcript_none_when_payload_missing_transcript_field(client):
    url = "GET:https://transcriptapi.com/api/v2/youtube/transcript?video_url=abc&format=json&include_timestamp=true"
    _seed_cache(client, url, {"video_id": "abc"})
    assert client.get_transcript("abc") is None


def test_get_video_info_parses_metadata_shape(client):
    url = "GET:https://transcriptapi.com/api/v2/youtube/info?video_url=abc"
    _seed_cache(client, url, {
        "video_id": "abc",
        "metadata": {"title": "Název", "author_name": "Kanál X", "author_url": "https://youtube.com/@kanalx"},
        "available_languages": [{"code": "cs", "name": "Czech"}],
    })
    info = client.get_video_info("abc")
    assert info == {
        "videoId": "abc", "title": "Název", "authorName": "Kanál X", "authorUrl": "https://youtube.com/@kanalx",
    }


def test_resolve_channel_reads_channel_id(client):
    url = "GET:https://transcriptapi.com/api/v2/youtube/channel/resolve?channel=%40TED"
    _seed_cache(client, url, {"channel_id": "UCAuUUnT6oDeKwE6v1NGQxug", "resolved_from": "@TED"})
    assert client.resolve_channel("@TED") == "UCAuUUnT6oDeKwE6v1NGQxug"


def test_get_channel_latest_videos_parses_results_list(client):
    url = "GET:https://transcriptapi.com/api/v2/youtube/channel/latest?channel=%40TED"
    _seed_cache(client, url, {
        "channel": {"channelId": "UC1", "title": "TED"},
        "results": [
            {"videoId": "v1", "title": "Video 1", "published": "2026-01-30T16:00:00Z", "updated": "2026-01-31T02:00:00Z"},
        ],
    })
    out = client.get_channel_latest_videos("@TED")
    assert out == [{"videoId": "v1", "title": "Video 1", "publishedAt": "2026-01-30T16:00:00Z"}]


def test_get_channel_latest_videos_empty_on_malformed_payload(client):
    url = "GET:https://transcriptapi.com/api/v2/youtube/channel/latest?channel=%40TED"
    _seed_cache(client, url, {"channel": {}})
    assert client.get_channel_latest_videos("@TED") == []
