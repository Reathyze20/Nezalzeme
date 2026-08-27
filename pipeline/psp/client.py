"""
HTTP klient pro veřejné zdroje Poslanecké sněmovny (psp.cz).

Sněmovna nemá REST API s JSON; veřejně dostupné jsou dva kanály a tenhle
klient obsluhuje oba:

  * **Stenoprotokoly** – statické HTML pod `https://www.psp.cz/eknih/`,
    kódované ve `windows-1250`.
  * **Otevřená data** – denně aktualizované ZIP archivy s UNL dumpy pod
    `https://www.psp.cz/eknih/cdrom/opendata/`.

Proti oběma se chováme jako slušný klient: identifikujeme se v User-Agentu,
držíme rozestup mezi dotazy a všechno ukládáme do diskové cache, aby opakované
zpracování téhož jednacího dne nešlo znovu po síti.
"""

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Optional

BASE = "https://www.psp.cz"
OPENDATA_BASE = BASE + "/eknih/cdrom/opendata/"

DEFAULT_CACHE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "psp_cache")

#: Sněmovna servíruje `windows-1250`; hlavička ji uvádí, meta tag je záloha.
FALLBACK_ENCODING = "windows-1250"

_CHARSET_HEADER = re.compile(r"charset=([\w-]+)", re.I)
_CHARSET_META = re.compile(rb'charset=["\']?([\w-]+)', re.I)


class PspClient:
    """Stahování s diskovou cache. Jedna instance = jeden běh zpracování."""

    def __init__(
        self,
        cache_dir: str = DEFAULT_CACHE,
        ttl_seconds: int = 6 * 3600,
        min_interval: float = 0.4,
        user_agent: str = "nezalzeme.cz/0.1 (zpracovani verejnych stenozaznamu PSP CR)",
        refresh: bool = False,
    ) -> None:
        self.http_dir = os.path.join(cache_dir, "http")
        self.blob_dir = os.path.join(cache_dir, "opendata")
        os.makedirs(self.http_dir, exist_ok=True)
        os.makedirs(self.blob_dir, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.min_interval = min_interval
        self.user_agent = user_agent
        self.refresh = refresh
        self._last_request = 0.0
        self.stats = {"hits": 0, "misses": 0, "bytes": 0}

    # -- síť ---------------------------------------------------------------

    def _throttle(self) -> None:
        wait = self.min_interval - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _download(self, url: str, attempts: int = 3):
        last = None
        for attempt in range(attempts):
            self._throttle()
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return response.read(), response.headers.get("Content-Type", "")
            except urllib.error.HTTPError as error:
                # 404 je odpověď, ne výpadek – opakování ji nezmění.
                if error.code < 500:
                    raise
                last = error
            except (urllib.error.URLError, TimeoutError) as error:
                last = error
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("psp.cz neodpovědělo ({}): {}".format(url, last))

    # -- cache -------------------------------------------------------------

    def _cache_paths(self, url: str):
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
        return (
            os.path.join(self.http_dir, key + ".bin"),
            os.path.join(self.http_dir, key + ".json"),
        )

    def get_bytes(self, url: str) -> bytes:
        """Vrátí tělo odpovědi; z cache, pokud je čerstvá."""
        blob_path, meta_path = self._cache_paths(url)
        if not self.refresh and os.path.exists(blob_path) and os.path.exists(meta_path):
            age = time.time() - os.path.getmtime(blob_path)
            if age < self.ttl_seconds:
                self.stats["hits"] += 1
                with open(blob_path, "rb") as handle:
                    return handle.read()

        raw, content_type = self._download(url)
        self.stats["misses"] += 1
        self.stats["bytes"] += len(raw)
        with open(blob_path, "wb") as handle:
            handle.write(raw)
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(
                {"url": url, "contentType": content_type, "fetchedAt": time.time()},
                handle,
                ensure_ascii=False,
            )
        return raw

    def get_text(self, url: str) -> str:
        """Vrátí dekódované HTML. Kódování bere z hlavičky, pak z meta tagu."""
        raw = self.get_bytes(url)
        _, meta_path = self._cache_paths(url)
        content_type = ""
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as handle:
                content_type = json.load(handle).get("contentType", "")

        match = _CHARSET_HEADER.search(content_type)
        encoding = match.group(1) if match else None
        if not encoding:
            meta = _CHARSET_META.search(raw[:4096])
            encoding = meta.group(1).decode("ascii") if meta else FALLBACK_ENCODING
        try:
            return raw.decode(encoding, "replace")
        except LookupError:
            return raw.decode(FALLBACK_ENCODING, "replace")

    # -- otevřená data -----------------------------------------------------

    def opendata_archive(self, name: str, max_age_seconds: int = 20 * 3600) -> str:
        """
        Stáhne (nebo použije z cache) ZIP z otevřených dat a vrátí cestu k němu.

        Archivy se aktualizují jednou denně, proto mají vlastní, delší TTL než
        běžné stránky.
        """
        path = os.path.join(self.blob_dir, name)
        fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_seconds
        if fresh and not self.refresh:
            self.stats["hits"] += 1
            return path
        raw, _ = self._download(OPENDATA_BASE + name)
        self.stats["misses"] += 1
        self.stats["bytes"] += len(raw)
        with open(path, "wb") as handle:
            handle.write(raw)
        return path

    def summary(self) -> str:
        return "cache: {} zásahů, {} stažení, {:.1f} MB ze sítě".format(
            self.stats["hits"], self.stats["misses"], self.stats["bytes"] / 1048576.0
        )


def absolute(url: str, base: Optional[str] = None) -> str:
    """Doplní relativní odkaz ze stránky psp.cz na absolutní."""
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return BASE + url
    if base:
        return base.rstrip("/") + "/" + url
    return BASE + "/" + url
