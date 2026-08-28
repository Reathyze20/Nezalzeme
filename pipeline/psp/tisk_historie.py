"""
Historie sněmovního tisku — autoritativní určení finálního hlasování.

Řeší jedinou, ale zásadní věc: **které z hlasování o bodu je hlasování
o zákonu jako celku.**

Z dat to jinak zjistit nejde. Sněmovna pojmenuje každé hlasování, které padne
za otevřeného bodu pořadu, jménem toho bodu — u tisku 82 nese všech 24
hlasování identický název `Novela z. o podpoře bydlení**` a jedno z nich je
podle stenozáznamu návrh na přerušení schůze do 9.59. `psp/vote_classifier.py`
klasifikuje podle názvu, takže tenhle rozdíl vidět nemůže; sufix `**` znamená
fázi „3. čtení", ne „hlasování o celku".

Stránka `sqw/historie.sqw?o=<období>&T=<tisk>` to říká přímo:

    3. čtení proběhlo 29. 5., 3. 6. 2026 na 17. schůzi.
    Návrh zákona schválen (hlasování č. 70, usnesení č. 200).

Číslo hlasování se pak přeloží na `id_hlasovani` přes dump
(`id_organ`, `schuze`, `cislo`) a křížově ověří proti odkazu `hlasy.sqw?G=`
na téže stránce. U tisků, které 3. čtením ještě neprošly, stránka žádný
takový údaj nemá a modul vrátí `None` — tj. bezpečné chování bez zvláštního
ošetření.

Ověřeno 28. 8. 2026 na tiscích 78, 82, 163, 198 (nalezeno) a 173, 174
(dosud neprojednáno → `None`).
"""

import html as _html
import re
from typing import Any, Dict, List, Optional

from .client import PspClient

HISTORIE_URL = "https://www.psp.cz/sqw/historie.sqw?o={obdobi}&T={tisk}"

#: `o=` na psp.cz je pořadové číslo volebního období, ne `id_organ`.
#: 10. volební období = Sněmovna zvolená 2025 (`id_organ` 174).
DEFAULT_OBDOBI = 10

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

#: „Návrh zákona schválen (hlasování č. 70, usnesení č. 200)" a jeho varianty.
#: Sněmovna střídá „schválen" / „byl přijat" / „zamítnut" / „nebyl přijat".
_FINAL_VOTE = re.compile(
    r"N[áa]vrh\s+z[áa]kona\s+(?P<vysledek>schv[áa]len|byl\s+p[řr]ijat|zam[íi]tnut|nebyl\s+p[řr]ijat)"
    r"[^.()]{0,80}?\(\s*hlasov[áa]n[íi]\s+[čc]\.\s*(?P<cislo>\d+)",
    re.IGNORECASE,
)

#: „... na 17. schůzi." — číslo schůze, na které se hlasovalo.
#:
#: Záměrně se neváže na prefix „3. čtení": číslo čtení je na stránce
#: vyrenderované jako samostatná grafická značka etapy (`3 &rarr; Senát`),
#: takže v textu vedle věty nestojí. Bere se proto **poslední zmínka schůze
#: před** větou o finálním hlasování — ta patří k témuž odstavci.
_SCHUZE = re.compile(r"na\s+(?P<schuze>\d+)\.\s*sch[ůu]zi", re.IGNORECASE)

_G_LINK = re.compile(r"hlasy\.sqw\?G=(\d+)")

#: Výsledek podle formulace Sněmovny -> náš příznak.
_PRIJAT = {"schválen", "schvalen", "byl přijat", "byl prijat"}


def _plain(raw: str) -> str:
    """HTML -> holý text. `unescape` až po stripnutí tagů, ať se entity
    nerozpadnou na značky (`&lt;b&gt;` nesmí vzniknout `<b>` a zmizet)."""
    return _WS.sub(" ", _html.unescape(_TAG.sub(" ", raw)))


def parse_historie(html: str) -> List[Dict[str, Any]]:
    """
    Všechna finální hlasování o tisku ve Sněmovně, v pořadí, v jakém proběhla.

    Obvykle je jedno (schválení ve 3. čtení). Dvě jsou, když zákon vrátí Senát
    a Sněmovna hlasuje znovu — u tisku 78 je to hlasování č. 50 na 10. schůzi
    (3. čtení) a č. 71 na 14. schůzi (po vrácení Senátem). Které z nich je to
    „správné", závisí na tom, ke které rozpravě se vztahuje výrok, takže volbu
    dělá až volající (`fetch_final_vote(prefer_schuze=...)`).

    Prázdný seznam = tisk 3. čtením neprošel, tedy není o čem tvrdit, že
    o něm poslanec hlasoval.
    """
    text = _plain(html)
    schuze_positions = [
        (m.start(), int(m.group("schuze"))) for m in _SCHUZE.finditer(text)
    ]

    out: List[Dict[str, Any]] = []
    for match in _FINAL_VOTE.finditer(text):
        vysledek_raw = _WS.sub(" ", match.group("vysledek").strip().lower())
        # Číslo schůze stojí v témže odstavci před větou o hlasování; číslo
        # čtení je na stránce samostatná grafická značka etapy, takže se na něj
        # vázat nedá.
        schuze_cislo = None
        for pos, cislo in schuze_positions:
            if pos > match.start():
                break
            schuze_cislo = cislo
        out.append({
            "cisloHlasovani": int(match.group("cislo")),
            "schuze": schuze_cislo,
            "vysledekSlovy": vysledek_raw,
            "prijat": vysledek_raw in _PRIJAT,
        })
    return out


def fetch_final_vote(client: PspClient, tisk: str, conn=None, id_organ: str = "174",
                     obdobi: int = DEFAULT_OBDOBI,
                     prefer_schuze: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Finální hlasování o tisku, přeložené na `id_hlasovani`.

    `conn` je engine.sqlite s naplněnou tabulkou `hlasovani`
    (`psp/opendata_hlasovani.py`). `prefer_schuze` vybere hlasování z téže
    schůze, na které padl posuzovaný výrok — bez něj se bere první, tedy
    schválení ve 3. čtení.

    Vrací `None`, kdykoli by výsledek byl nejistý: tisk finální hlasování
    nemá, číslo se nepodařilo přeložit na `id_hlasovani`, hlasování je
    zmatečné, nebo na něj stránka historie neodkazuje. Raději nic než špatné
    hlasování — tvrzení „hlasoval o tomto zákoně" musí sedět.
    """
    try:
        html = client.get_text(HISTORIE_URL.format(obdobi=obdobi, tisk=tisk))
    except Exception:
        return None

    kandidati = [k for k in parse_historie(html) if k["schuze"] is not None]
    if not kandidati:
        return None

    vybrany = None
    if prefer_schuze is not None:
        vybrany = next((k for k in kandidati if k["schuze"] == prefer_schuze), None)
    if vybrany is None:
        vybrany = kandidati[0]

    historie_url = HISTORIE_URL.format(obdobi=obdobi, tisk=tisk)
    result = {
        "tisk": str(tisk),
        "cisloHlasovani": vybrany["cisloHlasovani"],
        "schuze": vybrany["schuze"],
        "vysledekSlovy": vybrany["vysledekSlovy"],
        "prijat": vybrany["prijat"],
        "idHlasovani": None,
        "url": None,
        "historieUrl": historie_url,
    }
    if conn is None:
        return result

    row = conn.execute(
        "SELECT id_hlasovani, url, is_zmatecne FROM hlasovani "
        "WHERE id_organ = ? AND schuze = ? AND cislo = ?",
        (str(id_organ), vybrany["schuze"], vybrany["cisloHlasovani"]),
    ).fetchone()
    if not row or row["is_zmatecne"]:
        return None

    # Křížová kontrola proti odkazům na téže stránce: když stránka odkazuje na
    # hlasovací lístky a náš dopočítaný mezi nimi není, něco nesedí.
    odkazy = _G_LINK.findall(html)
    if odkazy and row["id_hlasovani"] not in odkazy:
        return None

    result["idHlasovani"] = row["id_hlasovani"]
    result["url"] = row["url"]
    return result


def tisk_number_from_ref(tisk_ref: Optional[str]) -> Optional[str]:
    """`/sněmovní tisk 82/` -> `82`. Vrací `None`, když číslo v textu není."""
    if not tisk_ref:
        return None
    match = re.search(r"tisk\s+(\d+)", tisk_ref, re.IGNORECASE)
    return match.group(1) if match else None
