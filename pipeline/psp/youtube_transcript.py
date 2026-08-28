"""
Klient pro REST API TranscriptAPI.com (transcriptapi.com/docs/api/) — přepisy
a vyhledávání YouTube videí. Stejný vzorec jako `hlidac_client.py`: lokální
SQLite cache s TTL, throttling, žádná závislost na síti při cache hitu.

DŮLEŽITÉ: API nevrací speaker diarizaci, jen souvislý text s timestampy
(`{"text", "start", "duration"}`) — "kdo mluví" se u vícehlasých videí musí
zjistit samostatně (`pipeline/video_diarization.py`), tenhle klient jen
stahuje surový přepis a metadata kanálu/videa.
"""

import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

TRANSCRIPTAPI_BASE = "https://transcriptapi.com/api/v2"
DEFAULT_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "transcriptapi_cache.sqlite"
)


class TranscriptApiClient:
    """Klient s perzistentní SQLite mezipamětí, TTL expirací a throttlováním."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_path: str = DEFAULT_CACHE_PATH,
        ttl_seconds: int = 30 * 24 * 3600,
        min_interval: float = 0.25,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ.get("TRANSCRIPTAPI_KEY", "")
        self.cache_path = cache_path
        self.ttl_seconds = ttl_seconds
        self.min_interval = min_interval
        self.timeout = timeout
        self._last_request = 0.0
        self.stats = {"hits": 0, "misses": 0, "errors": 0}
        self._init_cache()

    def _init_cache(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
        conn = sqlite3.connect(self.cache_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS transcriptapi_responses "
                "(cache_key TEXT PRIMARY KEY, response_json TEXT NOT NULL, cached_at_ts REAL NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()

    def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        conn = None
        try:
            conn = sqlite3.connect(self.cache_path)
            row = conn.execute(
                "SELECT response_json, cached_at_ts FROM transcriptapi_responses WHERE cache_key = ?", (key,)
            ).fetchone()
            if row and time.time() - row[1] <= self.ttl_seconds:
                self.stats["hits"] += 1
                return json.loads(row[0])
        except Exception:
            pass
        finally:
            if conn:
                conn.close()
        return None

    def _save_to_cache(self, key: str, data: Dict[str, Any]) -> None:
        conn = None
        try:
            conn = sqlite3.connect(self.cache_path)
            conn.execute(
                "INSERT OR REPLACE INTO transcriptapi_responses VALUES (?, ?, ?)",
                (key, json.dumps(data, ensure_ascii=False), time.time()),
            )
            conn.commit()
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

    def _throttle(self) -> None:
        wait = self.min_interval - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _call(self, endpoint: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = "{}/{}?{}".format(TRANSCRIPTAPI_BASE, endpoint.lstrip("/"), query)
        cache_key = "GET:" + url

        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        if not self.api_key:
            return None

        self.stats["misses"] += 1
        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Accept": "application/json",
            "User-Agent": "nezalzeme.cz/0.1 (zpracovani verejnych youtube prepisu)",
        }
        last_error = None
        for attempt in range(3):
            self._throttle()
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        self._save_to_cache(cache_key, data)
                        return data
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    return None
                last_error = err
            except Exception as err:
                last_error = err
            time.sleep(1.0 * (attempt + 1))

        self.stats["errors"] += 1
        return None

    def get_transcript(self, video_url: str, language: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """`[{"text", "start", "duration"}]` seřazené podle času, nebo `None` (chybí klíč/video/přepis)."""
        data = self._call("youtube/transcript", {
            "video_url": video_url, "format": "json", "include_timestamp": "true", "language": language,
        })
        if not data:
            return None
        transcript = data.get("transcript")
        if not isinstance(transcript, list):
            return None
        return transcript

    def get_video_info(self, video_url: str) -> Optional[Dict[str, Any]]:
        """
        Metadata videa (zdarma) — `{"videoId", "title", "authorName", "authorUrl"}`.
        DŮLEŽITÉ: tenhle endpoint podle dokumentace NEVRACÍ datum publikace
        (jen `title`/`author_name`/`author_url`/`thumbnail_url`) — datum se
        získává z výpisu kanálu (`get_channel_latest_videos`), ne odsud.
        """
        data = self._call("youtube/info", {"video_url": video_url})
        if not data:
            return None
        metadata = data.get("metadata") or {}
        return {
            "videoId": data.get("video_id"),
            "title": metadata.get("title"),
            "authorName": metadata.get("author_name"),
            "authorUrl": metadata.get("author_url"),
        }

    def resolve_channel(self, channel_url_or_handle: str) -> Optional[str]:
        """`@handle`/URL kanálu -> `UC...` ID (zdarma). `None`, nejde-li přeložit."""
        data = self._call("youtube/channel/resolve", {"channel": channel_url_or_handle})
        if not data:
            return None
        return data.get("channel_id")

    def get_channel_latest_videos(self, channel_url_or_handle: str) -> List[Dict[str, Any]]:
        """
        Posledních ~15 videí kanálu přes RSS (zdarma) — `{"videoId", "title",
        "publishedAt"}`. Jediný endpoint, který datum publikace videa vrací
        (`/youtube/info` ho nemá) — zdroj `datumClanku` pro video leady.
        """
        data = self._call("youtube/channel/latest", {"channel": channel_url_or_handle})
        if not data:
            return []
        results = data.get("results")
        if not isinstance(results, list):
            return []
        return [
            {"videoId": r.get("videoId"), "title": r.get("title"), "publishedAt": r.get("published")}
            for r in results
            if isinstance(r, dict)
        ]
