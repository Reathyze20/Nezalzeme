"""
Klient pro REST API Hlídače Státu (api.hlidacstatu.cz/api/v2).

Poskytuje ověření identity politiků, jejich historických veřejných rolí
a majetkových/firemních vazeb pro profily na Nezalžeme.cz.
Obsahuje lokální SQLite cache s TTL, throttling a křížovou validaci identity.
"""

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


HLIDAC_API_BASE = "https://api.hlidacstatu.cz/api/v2"
DEFAULT_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "hlidac_cache.sqlite"
)


@dataclass
class HistoricalRole:
    role: str
    organization: str
    since: Optional[str]
    until: Optional[str]


@dataclass
class HlidacEnrichment:
    osoba_id: str
    profile_url: str
    full_name: str
    birth_year: Optional[int]
    historical_roles: List[HistoricalRole]
    corporate_ties_count: int
    corporate_entities: List[str]


class HlidacClient:
    """
    Klient s perzistentní SQLite mezipamětí, TTL expirací a throttlováním.
    Funguje spolehlivě i bez tokenu (pokud jsou data v lokální cache).
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        cache_path: str = DEFAULT_CACHE_PATH,
        ttl_seconds: int = 24 * 3600,
        min_interval: float = 0.4,
        timeout: int = 15,
    ) -> None:
        self.api_token = api_token or os.environ.get("HLIDAC_STATU_TOKEN", "")
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
                """
                CREATE TABLE IF NOT EXISTS hlidac_responses (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    cached_at_ts REAL NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        conn = None
        try:
            conn = sqlite3.connect(self.cache_path)
            row = conn.execute(
                "SELECT response_json, cached_at_ts FROM hlidac_responses WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row:
                cached_data, cached_ts = row[0], row[1]
                # Kontrola TTL expirace
                if time.time() - cached_ts <= self.ttl_seconds:
                    self.stats["hits"] += 1
                    return json.loads(cached_data)
        except Exception:
            pass
        finally:
            if conn:
                conn.close()
        return None

    def _save_to_cache(self, key: str, data: Dict[str, Any], status: int = 200) -> None:
        conn = None
        try:
            conn = sqlite3.connect(self.cache_path)
            conn.execute(
                "INSERT OR REPLACE INTO hlidac_responses (cache_key, response_json, status_code, cached_at_ts) "
                "VALUES (?, ?, ?, ?)",
                (key, json.dumps(data, ensure_ascii=False), status, time.time()),
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

    def _call_api(self, endpoint: str, params: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        query_str = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{HLIDAC_API_BASE}/{endpoint.lstrip('/')}{query_str}"
        cache_key = f"GET:{url}"

        # 1. Zkusit cache
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # 2. Bez API tokenu vracet None
        if not self.api_token:
            return None

        # 3. HTTP volání s opakováním při selhání
        self.stats["misses"] += 1
        headers = {
            "Authorization": f"Token {self.api_token}",
            "User-Agent": "nezalzeme.cz/0.2 (overovani parlamentnich dat)",
            "Accept": "application/json",
        }

        last_error = None
        for attempt in range(3):
            self._throttle()
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        self._save_to_cache(cache_key, data, resp.status)
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

    def search_osoba(self, name: str) -> List[Dict[str, Any]]:
        """Vyhledá osoby na Hlídači Státu podle jména."""
        data = self._call_api("osoby/search", {"dotaz": name})
        if not data:
            return []
        if isinstance(data, list):
            return data
        return data.get("Results", data.get("results", []))

    def get_osoba_detail(self, osoba_id: str) -> Optional[Dict[str, Any]]:
        """Získá kompletní detail osoby (funkce, angažmá)."""
        return self._call_api(f"osoby/{urllib.parse.quote(osoba_id)}")

    def enrich_speaker(
        self,
        name: str,
        birth_year: Optional[int] = None,
        psp_id: Optional[str] = None,
    ) -> Optional[HlidacEnrichment]:
        """
        Vyhledá poslance a vytvoří obohacený profil pro Nezalžeme.cz s křížovým ověřením identity.
        Při nejednoznačnosti (kolize jmen bez shody na roku narození) výsledek bezpečně zamítne.
        """
        results = self.search_osoba(name)
        if not results:
            return None

        # Křížová validace: pokud je výsledků víc, musíme ověřit identitu
        candidate = None
        if len(results) == 1:
            candidate = results[0]
        else:
            # Kolize jmen (např. dvě Kovářové) — porovnáme rok narození nebo sněmovní funkce
            for r in results:
                cand_year = r.get("rokNarozeni") or r.get("narozeni")
                if birth_year and cand_year and str(birth_year) in str(cand_year):
                    candidate = r
                    break
            # Pokud se nepodařilo jednoznačně ověřit, raději odmítnout (false attribution risk)
            if not candidate:
                return None

        osoba_id = candidate.get("osobaId") or candidate.get("id")
        if not osoba_id:
            return None

        detail = self.get_osoba_detail(osoba_id) or candidate

        # Parsování historických rolí
        raw_funkce = detail.get("funkce", []) or []
        roles: List[HistoricalRole] = []
        for f in raw_funkce:
            role_name = f.get("funkce", f.get("nazev", "Veřejná funkce"))
            org = f.get("organizace", f.get("instituce", ""))
            since = f.get("od") or f.get("zacatek")
            until = f.get("do") or f.get("konec")
            roles.append(
                HistoricalRole(
                    role=role_name,
                    organization=org,
                    since=str(since) if since else None,
                    until=str(until) if until else None,
                )
            )

        # Parsování vazeb na firmy a angažmá
        angazma = detail.get("angazma", []) or []
        entities = []
        for a in angazma:
            ent = a.get("subjekt", a.get("organizace", ""))
            if ent and ent not in entities:
                entities.append(ent)

        # Rok narození
        byear = detail.get("rokNarozeni") or detail.get("narozeni")
        parsed_byear = None
        if byear:
            try:
                parsed_byear = int(str(byear)[:4])
            except (ValueError, TypeError):
                pass

        profile_url = f"https://www.hlidacstatu.cz/osoba/{osoba_id}"

        return HlidacEnrichment(
            osoba_id=osoba_id,
            profile_url=profile_url,
            full_name=name,
            birth_year=parsed_byear,
            historical_roles=roles[:6],
            corporate_ties_count=len(angazma),
            corporate_entities=entities[:5],
        )

    def enrichment_dict(
        self,
        name: str,
        birth_year: Optional[int] = None,
        psp_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Vrátí slovník v camelCase formátu pro dataset.json."""
        enrichment = self.enrich_speaker(name, birth_year=birth_year, psp_id=psp_id)
        if not enrichment:
            return None
        return {
            "osobaId": enrichment.osoba_id,
            "profileUrl": enrichment.profile_url,
            "fullName": enrichment.full_name,
            "birthYear": enrichment.birth_year,
            "historicalRoles": [asdict(r) for r in enrichment.historical_roles],
            "corporateTiesCount": enrichment.corporate_ties_count,
            "corporateEntities": enrichment.corporate_entities,
        }
