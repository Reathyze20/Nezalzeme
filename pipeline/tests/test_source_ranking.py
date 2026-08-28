"""
Testy `source_ranking.py` (Fáze 6e) — čisté funkce nad
`pipeline/data/source_ranking.csv`, žádná síť.
"""

import source_ranking as sr


def test_tier_for_url_exact_match_tier1():
    assert sr.tier_for_url("https://www.psp.cz/sqw/hlasy.sqw?G=80214") == 1


def test_tier_for_url_subdomain_distinct_from_parent():
    assert sr.tier_for_url("https://ct24.ceskatelevize.cz/clanek/123") == 1
    assert sr.tier_for_url("https://ceskatelevize.cz/clanek/123") == 1


def test_tier_for_url_unknown_domain_returns_none():
    assert sr.tier_for_url("https://neexistujici-server.example/clanek") is None


def test_tier_for_url_strips_www_prefix():
    assert sr.tier_for_url("https://www.blesk.cz/clanek") == 5


def test_tier_for_url_case_insensitive():
    assert sr.tier_for_url("https://WWW.Blesk.CZ/clanek") == 5


def test_tier_for_url_falls_back_to_parent_domain():
    assert sr.tier_for_url("https://regionalni.denik.cz/clanek") == 3


def test_tier_for_url_empty_host_returns_none():
    assert sr.tier_for_url("not-a-url") is None


def test_is_source_allowed_tier1_to_3_true():
    assert sr.is_source_allowed("https://idnes.cz/clanek") is True
    assert sr.is_source_allowed("https://seznamzpravy.cz/clanek") is True
    assert sr.is_source_allowed("https://psp.cz/clanek") is True


def test_is_source_allowed_unknown_domain_true():
    assert sr.is_source_allowed("https://neexistujici-server.example/clanek") is True


def test_is_source_allowed_tier4_false():
    assert sr.is_source_allowed("https://echo24.cz/clanek") is False


def test_is_source_allowed_tier5_false():
    assert sr.is_source_allowed("https://blesk.cz/clanek") is False
    assert sr.is_source_allowed("https://wikipedia.org/wiki/Neco") is False
    assert sr.is_source_allowed("https://demagog.cz/vyrok/123") is False


def test_is_source_allowed_custom_max_tier():
    assert sr.is_source_allowed("https://echo24.cz/clanek", max_tier=4) is True
    assert sr.is_source_allowed("https://blesk.cz/clanek", max_tier=4) is False
