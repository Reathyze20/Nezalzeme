"""
Pluggable model backend — jedno rozhraní pro volání LLM, tři implementace.

    GeminiBackend — volá Google Gemini API (gemini-2.5-flash); výsledky
                    ukládá do LLM cache v engine.sqlite.
    ApiBackend    — volá Anthropic API přímo; výsledky ukládá do LLM cache.
    JsonlBackend  — nulové náklady pro pilot: zapíše prompty do fronty (JSONL),
                    uživatel je zpracuje v Claude Code a odpovědi zapíše zpátky.

Použití (Gemini — výchozí):
    backend = GeminiBackend(conn)
    text = backend.call("CLAIMS", SYSTEM_PROMPT, payload, "gemini-2.5-flash")

Použití (Anthropic):
    backend = ApiBackend(conn)
    text = backend.call("CLAIMS", SYSTEM_PROMPT, payload, "claude-sonnet-5")

Použití (jsonl — pilot za nulové náklady):
    backend = JsonlBackend(conn)
    try:
        run_pipeline(backend, ...)
    except PendingCallsError as e:
        print("Zpracuj frontu v Claude Code:", e.queue_path)
"""

import io
import json
import os
import sqlite3
import warnings
from typing import Any, Dict, List, Optional

warnings.filterwarnings("ignore", message=".*automatic function calling.*")

# Načtení .env souboru (kořen projektu nebo cwd)
try:
    import dotenv

    _root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _env_file = os.path.join(_root_dir, ".env")
    if os.path.exists(_env_file):
        dotenv.load_dotenv(_env_file)
    else:
        dotenv.load_dotenv()
except Exception:
    pass

from db import cache_key as _make_cache_key, now_iso

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"


def clean_json_markdown(text: str) -> str:
    """Odstraní markdown obal ```json ... ``` pokud jej model vrátil."""
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return s


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
    def effective_model(self, model: str) -> str:
        """Vrátí konkrétní název modelu, který backend skutečně použije."""
        return model

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
# Google Gemini backend
# ---------------------------------------------------------------------------

class GeminiBackend(ModelBackend):
    """
    Volá Google Gemini API přes nový oficiální SDK `google-genai`.
    Výsledky ukládá do llm_cache v engine.sqlite — druhý běh nad stejnými
    daty nic nestojí.

    Vyžaduje GEMINI_API_KEY nebo GOOGLE_API_KEY v prostředí nebo v souboru .env.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        default_model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.conn = conn
        self.api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        self.default_model = (
            default_model
            or os.environ.get("GEMINI_MODEL")
            or DEFAULT_GEMINI_MODEL
        )
        self._hits = 0
        self._misses = 0
        self._client = None

    def effective_model(self, model: str) -> str:
        # Pokud je předán výchozí model Anthropic (claude-sonnet-5) nebo prázdný,
        # automaticky mapujeme na nastavený Gemini model.
        if not model or model.startswith("claude") or model == "default":
            return self.default_model
        return model

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise ValueError(
                "Nenalezena proměnná prostředí GEMINI_API_KEY ani GOOGLE_API_KEY.\n"
                "Vložte svůj API klíč do souboru .env v kořeni projektu:\n"
                "  GEMINI_API_KEY=vaš_klíč_zde\n"
                "Nebo vložte klíč přímo do PowerShellu před spuštěním:\n"
                "  $env:GEMINI_API_KEY=\"vaš_klíč_zde\""
            )
        from google import genai

        self._client = genai.Client(api_key=self.api_key)
        return self._client

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
        actual_model = self.effective_model(model)
        if ck is None:
            ck = _make_cache_key(actual_model, user_payload)

        cached = self._from_cache(ck)
        if cached is not None:
            return cached

        client = self._get_client()
        from google.genai import types

        thinking_cfg = None
        if "3.7" in actual_model or "2.5" in actual_model:
            try:
                thinking_cfg = types.ThinkingConfig(thinking_budget=0)
            except Exception:
                thinking_cfg = None

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            temperature=0.0,
            max_output_tokens=4096,
            thinking_config=thinking_cfg,
        )

        response = client.models.generate_content(
            model=actual_model,
            contents=user_payload,
            config=config,
        )
        text = clean_json_markdown(response.text or "")
        self._misses += 1
        self._to_cache(ck, text, actual_model)
        return text

    def stats(self) -> Dict[str, int]:
        return {"cache_hits": self._hits, "api_calls": self._misses}


# ---------------------------------------------------------------------------
# API backend (Anthropic)
# ---------------------------------------------------------------------------

class ApiBackend(ModelBackend):
    """
    Volá Anthropic API. Výsledky ukládá do llm_cache v engine.sqlite —
    druhý běh nad stejnými daty nic nestojí.

    Vyžaduje ANTHROPIC_API_KEY v prostředí nebo v souboru .env.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._hits = 0
        self._misses = 0

    def effective_model(self, model: str) -> str:
        return model or DEFAULT_ANTHROPIC_MODEL

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
        actual_model = self.effective_model(model)
        if ck is None:
            ck = _make_cache_key(actual_model, user_payload)

        cached = self._from_cache(ck)
        if cached is not None:
            return cached

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ValueError(
                "Nenalezena proměnná prostředí ANTHROPIC_API_KEY.\n"
                "Vložte klíč do .env nebo použijte Google Gemini s GEMINI_API_KEY."
            )

        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=actual_model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = clean_json_markdown(
            "".join(block.text for block in response.content if block.type == "text")
        )
        self._misses += 1
        self._to_cache(ck, text, actual_model)
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
    uživatel je zpracuje v Claude Code nebo jiném nástroji.
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
                        responses[ck] = clean_json_markdown(text)
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
