"""
Makroekonomický kontext pro Adversariální Tribunál.

Stahuje a cachuje klíčové ukazatele z otevřených českých datových zdrojů:

  * ČSÚ DataStat API (data.csu.gov.cz/api/katalog/v1):
      - Míra inflace – měsíční (dataset CEN0101HT02)

  * ČNB (cnb.cz):
      - Kurz EUR/CZK (denní fixing, rok.txt)
      - 2W Repo sazba (monetary_policy_rates JSON)

Výstup je strukturovaný slovník s ukazateli pro zadaný měsíc, například:

    {
      "month": "2026-03",
      "cpi_yoy_pct": 3.4,
      "gdp_yoy_pct": None,
      "repo_rate_pct": 3.75,
      "eur_czk": 25.31,
      "delta_month": "2025-03",
      "cpi_yoy_pct_delta": 8.1,
      "narrative": "V tomto měsíci inflace dosahovala 3,4 % (meziročně). ...",
      "data_sources": ["csu_cpi", "cnb_eur"]
    }

Cache: SQLite tabulka macro_cache v engine.sqlite (TTL 24 h).
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psp.facts import ENGINE_SQLITE_PATH  # noqa: E402

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS = 86400  # 24 hodin


def _open_cache(db_path: str = ENGINE_SQLITE_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_cache (
            cache_key  TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,
            cached_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _cache_get(conn: sqlite3.Connection, key: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT payload, cached_at FROM macro_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    if not row:
        return None
    try:
        cached_at = datetime.fromisoformat(row[1])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age > CACHE_TTL_SECONDS:
            return None
        return json.loads(row[0])
    except Exception:
        return None


def _cache_set(conn: sqlite3.Connection, key: str, data: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO macro_cache (cache_key, payload, cached_at) VALUES (?, ?, ?)",
        (key, json.dumps(data, ensure_ascii=False), now),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Nezalzeme-MacroContext/1.0 (+https://nezalzeme.cz)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ČSÚ DataStat – Míra inflace (CPI meziročně, měsíčně)
# ---------------------------------------------------------------------------

def _fetch_csu_cpi() -> Dict[str, float]:
    """
    Stáhne data z ČSÚ DataStat API v2 pro dataset CEN0101HT02
    (Míra inflace – měsíční).

    Vrátí slovník { 'YYYY-MM': cpi_yoy_pct }.
    """
    # ČSÚ DataStat API - správný endpoint pro data (v2)
    url = (
        "https://data.csu.gov.cz/api/katalog/v1/vybery/CEN0101HT02"
        "?format=json-stat2&lang=cs"
    )
    text = _fetch_url(url)
    if not text:
        return {}
    try:
        data = json.loads(text)
        # Extrakce hodnot z JSON-STAT2 formátu
        # Struktura: data["dataset"]["dimension"]["cas"]["category"]["label"]
        # a data["dataset"]["value"]
        ds = data.get("dataset", data.get("CEN0101HT02", data))
        dims = ds.get("dimension", {})

        # Hledáme časovou dimenzi
        time_labels: Dict[str, str] = {}
        for dim_key, dim_val in dims.items():
            cat = dim_val.get("category", {})
            labels = cat.get("label", {})
            # Časové kódy mají formát "2025M01" nebo "2025-01"
            sample = next(iter(labels.values()), "")
            if "M" in sample or (len(sample) == 7 and "-" in sample):
                time_labels = labels
                break

        values = ds.get("value", [])
        result = {}
        for idx, (k, label) in enumerate(time_labels.items()):
            raw = str(label).replace("M", "-")
            if len(raw) == 7:
                v = values[idx] if idx < len(values) else None
                if v is not None:
                    result[raw] = round(float(v), 2)
        return result
    except Exception:
        return {}


def _fetch_csu_cpi_html() -> Dict[str, float]:
    """
    Záložní metoda: Eurostat JSON-STAT2 API pro HICP inflaci v ČR.

    Eurostat vrátí multidimenzionální dataset — klíče v `value` jsou
    velká čísla vypočtená jako produktový index přes všechny dimenze.
    Pro jednoznačnou identifikaci CZ + HICP celkem + RCH_A (meziroční %)
    musíme přepočítat offset z kategorie `index` časové dimenze.

    Vrátí { 'YYYY-MM': cpi_yoy_pct }.
    """
    url = (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
        "prc_hicp_manr?geo=CZ&unit=RCH_A&coicop=CP00&lang=en&format=JSON"
    )
    text = _fetch_url(url)
    if not text:
        return {}
    try:
        data = json.loads(text)
        # `size` pole: [freq_size, unit_size, coicop_size, geo_size, time_size]
        sizes = data.get("size", [])
        dim_ids = data.get("id", [])
        values = data.get("value", {})

        time_dim = data.get("dimension", {}).get("time", {})
        cat = time_dim.get("category", {})
        # `index` mapuje YYYY-MM -> pořadová pozice v datovém poli
        time_index: Dict[str, int] = cat.get("index", {})

        if not time_index or not sizes:
            return {}

        # Multiplikátory pro každou dimenzi (pro výpočet absolutního offsetu)
        # Při filtrování na jeden záznam všech ostatních dimenzí je offset = 0
        # a hodnoty jsou přímo indexovány pozicí časové dimenze.
        # (Eurostat normalizuje: pokud filtruji geo=CZ, unit=RCH_A, coicop=CP00,
        #  výsledek má pouze 1 hodnotu pro každý čas.)
        n_time = sizes[-1] if sizes else len(time_index)

        result: Dict[str, float] = {}
        for period, pos in time_index.items():
            # Zkusíme přímý index (funguje při plném filtrování na 1 prvek/dim)
            val = values.get(str(pos)) or values.get(pos)
            if val is not None:
                result[period] = round(float(val), 2)

        # Pokud přímý přístup nefunguje, zkusíme sekvenční mapování pořadí
        if not result:
            sorted_periods = sorted(time_index.items(), key=lambda x: x[1])
            for i, (period, pos) in enumerate(sorted_periods):
                # Zkusíme klíče jako velká čísla (Eurostat offset)
                for key_candidate in [str(pos), pos, str(i)]:
                    val = values.get(key_candidate)
                    if val is not None:
                        result[period] = round(float(val), 2)
                        break

        return result
    except Exception:
        return {}





# ---------------------------------------------------------------------------
# ČNB – kurz EUR/CZK z ročního souboru
# ---------------------------------------------------------------------------

def _fetch_cnb_eur(year: int = None) -> Dict[str, float]:
    """
    Stáhne průměrné měsíční kurzy EUR/CZK z ČNB ročního souboru.
    Vrátí { 'YYYY-MM': eur_czk }.
    """
    if year is None:
        year = datetime.now().year

    results: Dict[str, float] = {}

    for yr in ([year, year - 1]):  # Stáhneme aktuální i předchozí rok
        url = f"https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/rok.txt?rok={yr}"
        text = _fetch_url(url)
        if not text:
            continue

        lines = text.splitlines()
        if not lines:
            continue

        # Záhlaví: "Datum|1 AUD|1 BRL|...|1 EUR|..."
        header = lines[0].strip().split("|")
        eur_idx = None
        for i, col in enumerate(header):
            if "EUR" in col.upper():
                eur_idx = i
                break

        if eur_idx is None:
            continue

        # Agregace na měsíc (průměr)
        monthly: Dict[str, List[float]] = {}
        for line in lines[1:]:
            parts = line.strip().split("|")
            if len(parts) <= eur_idx:
                continue
            date_str = parts[0].strip()  # formát "27.08.2026"
            try:
                day, mon, yyy = date_str.split(".")
                key = f"{yyy}-{mon}"
                val = float(parts[eur_idx].replace(",", ".").strip())
                monthly.setdefault(key, []).append(val)
            except Exception:
                continue

        for key, vals in monthly.items():
            avg = round(sum(vals) / len(vals), 3)
            results.setdefault(key, avg)

    return results


# ---------------------------------------------------------------------------
# ČNB – 2W Repo sazba
# ---------------------------------------------------------------------------

def _fetch_cnb_repo() -> Dict[str, float]:
    """
    Stáhne historické hodnoty 2W Repo sazby z ČNB.
    Vrátí { 'YYYY-MM': repo_pct }.

    ČNB poskytuje data přes JSON API na adrese monetary_policy_rates.
    """
    # Přímý JSON export z ČNB ARAD
    url = "https://www.cnb.cz/export/cs/financial_markets/money_market/monetary_policy_rates/mp_rates.json"
    text = _fetch_url(url)
    if not text:
        # Alternativní: PRIBOR stránka
        url2 = "https://www.cnb.cz/export/cs/financial_markets/money_market/interbank_interest_rates/rada_CZEONIA.json"
        text = _fetch_url(url2)
    if not text:
        return {}

    try:
        data = json.loads(text)
        result: Dict[str, float] = {}
        rows = data if isinstance(data, list) else data.get("data", [])
        for row in rows:
            date_str = row.get("date", "") or row.get("datum", "")
            # Hledáme repo sazbu pod různými klíči
            val = (
                row.get("2T repo") or row.get("2w repo")
                or row.get("repo") or row.get("Repo")
                or row.get("2T_repo") or row.get("rate")
            )
            if not date_str or val is None:
                continue
            try:
                # Formát "DD.MM.YYYY" nebo "YYYY-MM-DD"
                if "." in date_str:
                    parts = date_str.split(".")
                    key = f"{parts[2]}-{parts[1]}"
                else:
                    key = date_str[:7]
                result[key] = round(float(str(val).replace(",", ".")), 2)
            except Exception:
                continue
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Hlavní veřejná funkce
# ---------------------------------------------------------------------------

def get_macro_context(month: str, db_path: str = ENGINE_SQLITE_PATH) -> Dict[str, Any]:
    """
    Vrátí makroekonomický kontext pro daný měsíc (formát 'YYYY-MM').

    Při nedostupnosti dat vrátí prázdný kontext bez pádu.
    """
    cache_key = f"macro:{month}"
    conn = None
    try:
        conn = _open_cache(db_path)
        cached = _cache_get(conn, cache_key)
        if cached is not None:
            return cached
    except Exception:
        pass

    # Srovnávací měsíc o rok dříve
    try:
        yyyy, mm = int(month[:4]), int(month[5:7])
        delta_month = f"{yyyy - 1}-{mm:02d}"
    except Exception:
        delta_month = ""

    sources_used: List[str] = []

    # CPI inflace – zkusíme ČSÚ, pak Eurostat jako zálohu
    cpi_data = _fetch_csu_cpi()
    if not cpi_data:
        cpi_data = _fetch_csu_cpi_html()
    cpi_now = cpi_data.get(month)
    cpi_delta = cpi_data.get(delta_month)
    if cpi_data:
        sources_used.append("csu_cpi")

    # EUR/CZK kurz
    try:
        year = int(month[:4])
    except Exception:
        year = datetime.now().year
    eur_data = _fetch_cnb_eur(year)
    eur_now = eur_data.get(month)
    if eur_data:
        sources_used.append("cnb_eur")

    # Repo sazba
    repo_data = _fetch_cnb_repo()
    repo_now = repo_data.get(month)
    if repo_data:
        sources_used.append("cnb_repo")

    # Narativní souhrn pro LLM
    narrative_parts = []
    if cpi_now is not None:
        narrative_parts.append(f"Inflace (CPI meziročně): {cpi_now} %")
        if cpi_delta is not None:
            diff = round(cpi_now - cpi_delta, 2)
            direction = "poklesla" if diff < 0 else "vzrostla"
            narrative_parts.append(
                f"(oproti stejnému měsíci před rokem [{delta_month}]: {cpi_delta} %, "
                f"tj. inflace {direction} o {abs(diff)} p.b.)"
            )
    if repo_now is not None:
        narrative_parts.append(f"2T repo sazba ČNB: {repo_now} %")
    if eur_now is not None:
        narrative_parts.append(f"Kurz EUR/CZK (průměr měsíce): {eur_now}")

    narrative = (
        " | ".join(narrative_parts)
        if narrative_parts
        else "Makroekonomická data pro tento měsíc nejsou k dispozici."
    )

    result: Dict[str, Any] = {
        "month": month,
        "cpi_yoy_pct": cpi_now,
        "gdp_yoy_pct": None,
        "repo_rate_pct": repo_now,
        "eur_czk": eur_now,
        "delta_month": delta_month,
        "cpi_yoy_pct_delta": cpi_delta,
        "narrative": narrative,
        "data_sources": sources_used,
    }

    try:
        if conn:
            _cache_set(conn, cache_key, result)
    except Exception:
        pass

    return result


def format_for_defense(macro: Dict[str, Any]) -> str:
    """Formátuje makro kontext do kompaktního textu pro injection do Obhájcova promptu."""
    if not macro.get("data_sources"):
        return ""
    lines = [
        f"MAKROEKONOMICKÝ KONTEXT [{macro.get('month', '?')}]:",
        macro.get("narrative", ""),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    month = sys.argv[1] if len(sys.argv) > 1 else "2026-03"
    print(f"Testuji makrokontext pro měsíc: {month}")
    db = os.path.join(os.path.dirname(__file__), "data", "engine.sqlite")
    ctx = get_macro_context(month, db_path=db)
    print(json.dumps(ctx, ensure_ascii=False, indent=2))
