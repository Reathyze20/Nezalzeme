"""
Pluggable model backend — jedno rozhraní pro volání LLM, dvě implementace.

    ApiBackend   — volá Anthropic API přímo; výsledky ukládá do LLM cache
                   v engine.sqlite, aby se opakovaný experiment neplatil.
    JsonlBackend — nulové náklady pro pilot: zapíše prompty do fronty (JSONL),
                   uživatel je zpracuje v Claude Code a odpovědi zapíše zpátky.

Přidání Gemini nebo jiného providera = podtřída `ApiBackend` s jiným SDK.

Použití (api):
    backend = ApiBackend(conn)
    text = backend.call("CLAIMS", SYSTEM_PROMPT, payload, "claude-sonnet-5")

Použití (jsonl — pilot za nulové náklady):
    backend = JsonlBackend(conn)
    try:
        run_pipeline(backend, ...)
    except PendingCallsError as e:
        print("Zpracuj frontu v Claude Code:", e.queue_path)
    # Po zpracování: zapsat odpovědi do llm_responses.jsonl, spustit znovu.
"""

import io
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

from db import cache_key as _make_cache_key, now_iso

# ---------------------------------------------------------------------------
# Výjimky
# ---------------------------------------------------------------------------

class PendingCallsError(Exception):
    """JsonlBackend narazil na nepřipravené volání — fronta uložena na disk."""

    def __init__(self, count: int, queue_path: str) -> None:
        self.count = count
        self.queue_path = queue_path
        super().__init__(
            "{} volání čeká na zpracování. Fronta: {}".format(count, queue_path)
        )


class _PendingCall(Exception):
    """Interní signál — backend ještě nemá odpověď pro tento cache klíč."""


# ---------------------------------------------------------------------------
# Abstraktní základ
# ---------------------------------------------------------------------------

class ModelBackend:
    def call(
        self,
        role: str,
        system_prompt: str,
        user_payload: str,
        model: str,
        ck: Optional[str] = None,
    ) -> str:
        """
        Zavolá model (nebo jeho náhradu) a vrátí textovou odpověď.

        `role` je jen popisný štítek (CLAIMS, PROSECUTOR, DEFENSE, ARBITER)
        pro logování a frontu. `ck` je cache klíč; pokud není zadán,
        vypočítá se z `model + user_payload`.
        """
        raise NotImplementedError

    def finalize(self) -> None:
        """Volat na konci pipeline — JsonlBackend zde zapíše frontu na disk."""


# ---------------------------------------------------------------------------
# API backend (Anthropic)
# ---------------------------------------------------------------------------

class ApiBackend(ModelBackend):
    """
    Volá Anthropic API. Výsledky ukládá do llm_cache v engine.sqlite —
    druhý běh nad stejnými daty nic nestojí.

    Vyžaduje ANTHROPIC_API_KEY v prostředí.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._hits = 0
        self._misses = 0

    def _from_cache(self, ck: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT response_text FROM llm_cache WHERE cache_key = ?", (ck,)
        ).fetchone()
        if row:
            self._hits += 1
            return row["response_text"]
        return None

    def _to_cache(self, ck: str, text: str, model: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO llm_cache "
            "(cache_key, response_text, model_name, cached_at) VALUES (?, ?, ?, ?)",
            (ck, text, model, now_iso()),
        )
        self.conn.commit()

    def call(
        self,
        role: str,
        system_prompt: str,
        user_payload: str,
        model: str,
        ck: Optional[str] = None,
    ) -> str:
        if ck is None:
            ck = _make_cache_key(model, user_payload)

        cached = self._from_cache(ck)
        if cached is not None:
            return cached

        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        self._misses += 1
        self._to_cache(ck, text, model)
        return text

    def stats(self) -> Dict[str, int]:
        return {"cache_hits": self._hits, "api_calls": self._misses}


# ---------------------------------------------------------------------------
# Jsonl backend (nulové náklady pro pilot)
# ---------------------------------------------------------------------------

QUEUE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "llm_queue.jsonl"
)
RESPONSES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "llm_responses.jsonl"
)


class JsonlBackend(ModelBackend):
    """
    Pilot za nulové náklady — pipeline zapisuje prompty do fronty,
    uživatel je zpracuje v Claude Code.

    Průběh:
    1. `run_pipeline.py --backend jsonl` → backend narazí na chybějící
       odpovědi, uloží llm_queue.jsonl a vyvolá PendingCallsError.
    2. Uživatel v Claude Code přečte každý řádek fronty, zavolá model
       a zapíše odpovědi do llm_responses.jsonl (jeden JSON objekt na řádek).
    3. `run_pipeline.py --backend jsonl --pokracovat` → backend načte
       odpovědi, uloží do llm_cache, pipeline pokračuje.

    Formát řádku v llm_queue.jsonl:
        {"cache_key":"…","role":"CLAIMS","model":"claude-sonnet-5",
         "system":"…","user":"…"}

    Formát řádku v llm_responses.jsonl:
        {"cache_key":"…","response_text":"…"}
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        queue_path: str = QUEUE_PATH,
        responses_path: str = RESPONSES_PATH,
    ) -> None:
        self.conn = conn
        self.queue_path = queue_path
        self.responses_path = responses_path
        self._pending: List[Dict[str, Any]] = []
        self._responses: Dict[str, str] = self._load_responses()

    def _load_responses(self) -> Dict[str, str]:
        responses: Dict[str, str] = {}
        if not os.path.exists(self.responses_path):
            return responses
        with io.open(self.responses_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    ck = item.get("cache_key")
                    text = item.get("response_text")
                    if ck and text is not None:
                        responses[ck] = text
                except json.JSONDecodeError:
                    continue
        if responses:
            print("[jsonl] načteno {} odpovědí z {}".format(
                len(responses), self.responses_path))
        return responses

    def _from_db_cache(self, ck: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT response_text FROM llm_cache WHERE cache_key = ?", (ck,)
        ).fetchone()
        return row["response_text"] if row else None

    def _to_db_cache(self, ck: str, text: str, model: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO llm_cache "
            "(cache_key, response_text, model_name, cached_at) VALUES (?, ?, ?, ?)",
            (ck, text, model, now_iso()),
        )
        self.conn.commit()

    def call(
        self,
        role: str,
        system_prompt: str,
        user_payload: str,
        model: str,
        ck: Optional[str] = None,
    ) -> str:
        if ck is None:
            ck = _make_cache_key(model, user_payload)

        # 1. DB cache (z předchozího běhu)
        cached = self._from_db_cache(ck)
        if cached is not None:
            return cached

        # 2. Soubor s odpověďmi (zpracovaný uživatelem)
        if ck in self._responses:
            text = self._responses[ck]
            self._to_db_cache(ck, text, model)
            return text

        # 3. Zařadit do fronty
        self._pending.append({
            "cache_key": ck,
            "role": role,
            "model": model,
            "system": system_prompt,
            "user": user_payload,
        })
        raise _PendingCall(ck)

    def finalize(self) -> None:
        if not self._pending:
            return
        os.makedirs(os.path.dirname(self.queue_path), exist_ok=True)
        with io.open(self.queue_path, "w", encoding="utf-8") as handle:
            for item in self._pending:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        raise PendingCallsError(len(self._pending), self.queue_path)
