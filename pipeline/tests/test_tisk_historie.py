"""
Testy `psp/tisk_historie.py` — autoritativní určení finálního hlasování o tisku.

Fixtury jsou zkrácené výřezy skutečných stránek `historie.sqw` (tisk 82 a 78,
staženo 28. 8. 2026), ne živá síť.
"""

import pytest

from psp.tisk_historie import (
    fetch_final_vote,
    parse_historie,
    tisk_number_from_ref,
)

#: Tisk 82 — prošel 3. čtením, jedno finální hlasování.
HTML_SCHVALEN = """
<p><b>3</b> 3. čtení proběhlo 29.&nbsp;5. , 3.&nbsp;6.&nbsp;2026 na 17. schůzi.
Návrh zákona schválen (<a href="/sqw/hlasy.sqw?G=87617">hlasování č. 70</a>
, usnesení č.&nbsp; 200 ).</p>
"""

#: Tisk, který je teprve v 1. čtení — žádné finální hlasování.
HTML_NEPROJEDNANO = """
<p><b>1</b> 1. čtení proběhlo 13.&nbsp;3.&nbsp;2026 na 12. schůzi.
Návrh zákona přikázán k projednání výborům.</p>
"""

#: Zamítnutý návrh.
HTML_ZAMITNUT = """
<p>3. čtení proběhlo 1.&nbsp;4.&nbsp;2026 na 13. schůzi.
Návrh zákona zamítnut (<a href="/sqw/hlasy.sqw?G=99999">hlasování č. 12</a>).</p>
"""


def test_parse_historie_finds_approved_bill():
    out = parse_historie(HTML_SCHVALEN)
    assert len(out) == 1
    assert out[0]["cisloHlasovani"] == 70
    assert out[0]["schuze"] == 17
    assert out[0]["prijat"] is True


def test_parse_historie_returns_empty_for_unfinished_bill():
    # Tisk bez 3. čtení nesmí vrátit nic — jinak by se dalo tvrdit
    # "hlasoval o tomto zákoně" o zákonu, o kterém se nehlasovalo.
    assert parse_historie(HTML_NEPROJEDNANO) == []


def test_parse_historie_marks_rejected_bill_as_not_passed():
    out = parse_historie(HTML_ZAMITNUT)
    assert len(out) == 1
    assert out[0]["cisloHlasovani"] == 12
    assert out[0]["prijat"] is False
    assert "zam" in out[0]["vysledekSlovy"]


class _FakeClient:
    def __init__(self, html):
        self._html = html

    def get_text(self, url):
        return self._html


def _seed_hlasovani(conn, id_hlasovani, schuze, cislo, is_zmatecne=0):
    conn.execute(
        "INSERT OR REPLACE INTO hlasovani (id_hlasovani, id_organ, schuze, cislo, bod, datum, cas, "
        "pro, proti, zdrzel, nehlasoval, prihlaseno, kvorum, vysledek, nazev, is_zmatecne, url) "
        "VALUES (?, '174', ?, ?, 1, '29.05.2026', '10:00', 100, 50, 0, 0, 150, 76, 'A', 'Novela**', ?, ?)",
        (id_hlasovani, schuze, cislo, is_zmatecne,
         "https://www.psp.cz/sqw/hlasy.sqw?G={}".format(id_hlasovani)),
    )
    conn.commit()


def test_fetch_final_vote_resolves_id_via_dump(engine_db):
    _seed_hlasovani(engine_db, "87617", 17, 70)
    out = fetch_final_vote(_FakeClient(HTML_SCHVALEN), "82", conn=engine_db)
    assert out is not None
    assert out["idHlasovani"] == "87617"
    assert out["schuze"] == 17
    assert out["prijat"] is True


def test_fetch_final_vote_returns_none_when_dump_has_no_such_vote(engine_db):
    # Číslo hlasování ze stránky, které v dumpu není -> nevracet nic.
    out = fetch_final_vote(_FakeClient(HTML_SCHVALEN), "82", conn=engine_db)
    assert out is None


def test_fetch_final_vote_rejects_annulled_vote(engine_db):
    _seed_hlasovani(engine_db, "87617", 17, 70, is_zmatecne=1)
    out = fetch_final_vote(_FakeClient(HTML_SCHVALEN), "82", conn=engine_db)
    assert out is None


def test_fetch_final_vote_rejects_id_not_linked_on_page(engine_db):
    # Dump má na (schůze 17, č. 70) jiné id, než na které stránka odkazuje —
    # křížová kontrola to musí zachytit.
    _seed_hlasovani(engine_db, "11111", 17, 70)
    out = fetch_final_vote(_FakeClient(HTML_SCHVALEN), "82", conn=engine_db)
    assert out is None


def test_fetch_final_vote_without_conn_skips_id_resolution():
    out = fetch_final_vote(_FakeClient(HTML_SCHVALEN), "82")
    assert out["cisloHlasovani"] == 70
    assert out["idHlasovani"] is None


@pytest.mark.parametrize("ref,expected", [
    ("/sněmovní tisk 82/", "82"),
    ("/sněmovní tisk 1234/", "1234"),
    ("Není sn.tiskem", None),
    ("", None),
    (None, None),
])
def test_tisk_number_from_ref(ref, expected):
    assert tisk_number_from_ref(ref) == expected


def test_plain_decodes_html_entities():
    """psp.cz míchá skutečné znaky a entity (`&nbsp;`); obojí musí projít."""
    out = parse_historie(
        "<p>3. čtení proběhlo na 9.&nbsp;schůzi. "
        "N&aacute;vrh z&aacute;kona schv&aacute;len (hlasov&aacute;n&iacute; č. 5).</p>"
    )
    assert len(out) == 1
    assert out[0]["cisloHlasovani"] == 5
    assert out[0]["schuze"] == 9
