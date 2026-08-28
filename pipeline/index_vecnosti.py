"""
Index věcnosti (Fáze 5) — rozklad měřitelné parlamentní aktivity na složky.

**Žádná položka nesmí vzniknout z jazykového modelu.** To je tvrdé pravidlo
téhle fáze, ne stylistická volba: jakmile "věcnost" počítá LLM ("odpovídá na
dotaz, nebo odbočuje?"), je to subjektivní soud vydávaný za měření a první
novinář se zeptá, kdo měří měřiče. Všechny čtyři složky jdou spočítat přímo
z otevřených dat nebo ze stažených stenozáznamů — nic tady nevolá
`model_backend`.

Publikuje se jako **rozklad na složky, ne jedno číslo v žebříčku** — ve
shodě s tím, jak rejstřík dnes prezentuje SCI ("Pořadí neurčuje redakce").

Čtyři složky, dvě na profilu poslance už existují a tenhle modul je NEDUPLIKUJE:
  - **docházka** u jmenovitých hlasování — zveřejňuje ji `hlasovaciBilance`
    (Fáze 2, `hlasovaci_rejstrik.voting_balance`), stojí na kompletním dumpu
    `hl-2025ps.zip`, tedy za CELÉ volební období bez ohledu na to, kolik
    jednacích dnů jsme stáhli textem.
  - (SCI, index konzistence postojů, je z jiné rodiny — vzniká ze Slova
    a činu, ne odsud.)

Tenhle modul přidává zbylé dvě. Jedna je za celé období jako docházka:
  - **počet předložených poslaneckých návrhů zákonů** (`tisky.unl` +
    `predkladatel.unl`). Počítají se jen `id_druh=2` (nevládní návrh zákona)
    s `id_navrh` PO/SP (poslanec / skupina poslanců) — vládní návrhy
    (`id_druh=1`) se NEPOČÍTAJÍ, i když u nich `tisky.id_osoba` nese jméno
    člena vlády: podle dokumentace psp.cz "vládní návrhy nejsou vázány na
    osobu předkladatele", je to funkce (ministr), ne autorství.

Druhá je vázaná na STAŽENÝ VZOREK stenozáznamů (dnes zlomek jednacích dnů
volebního období) a publikuje se jen nad minimálním počtem vystoupení, vždy
s uvedením velikosti vzorku — jinak by poslanec, který mluvil hlavně mimo
stažené dny, vyšel jako pasivní, přestože o něm nevíme nic:
  - **podíl krátkých vystoupení** (< `MIN_SUBSTANTIVE_CHARS` znaků) —
    stejný práh jako u filtru pro extrakci tvrzení v `run_pipeline.py`,
    záměrně duplikovaný jako konstanta, aby modul nepotřeboval importovat
    těžkou závislost jen kvůli jednomu číslu,
  - **medián délky vystoupení** ve znacích, počítáno ze stejného vzorku.

Obojí se počítá ze VŠECH vystoupení řečníka ve staženém vzorku (ne jen
z těch, která prošla extrakcí tvrzení), aby vzorek nebyl zúžený podruhé.
"""

import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from psp.opendata import read_unl  # noqa: E402

#: Duplikát `run_pipeline.MIN_SUBSTANTIVE_CHARS` — viz docstring modulu.
MIN_SUBSTANTIVE_CHARS = 200

#: Pod tímto počtem vystoupení ve vzorku se složky vázané na stenokorpus
#: nepublikují vůbec — malý vzorek by dal nesmyslně ostré procento (1 z 1 = 100 %).
MIN_VYSTOUPENI_PRO_VECNOST = 5

#: `typ_zakon.unl`: 2 = poslanec, 3 = skupina poslanců. Vláda (1), Senát (4)
#: a kraje (6–19) se do "poslaneckých návrhů" nepočítají.
_POSLANECKE_ID_NAVRH = {"2", "3"}
#: `druh_tisku.unl`: 2 = "Návrh zákona" (nevládní). 1 = vládní návrh.
_NEVLADNI_NAVRH_ZAKONA = "2"


def submitted_bills_by_person(client, id_organ: str = "174") -> Dict[str, int]:
    """
    `id_osoba -> počet poslaneckých návrhů zákonů` za volební období.

    Sloupce `tisky.unl` (ověřeno proti https://www.psp.cz/sqw/hp.sqw?k=1303,
    28. 8. 2026): 0 id_tisk, 1 id_druh, 2 id_stav, 3 ct, 4 cislo_za,
    5 id_navrh, 6 id_org, 7 id_org_obd, 8 id_osoba.

    `predkladatel.unl` existuje jen tam, kde je předkladatelů víc než jeden
    — u jediného předkladatele je jméno přímo v `tisky.id_osoba`. Kdyby se
    počítalo jen z `predkladatel.unl`, zmizeli by všichni, kdo podali návrh
    sami (0 pořad. 3, 4 v ukázce dat).
    """
    archive = client.opendata_archive("tisky.zip")

    eligible: Dict[str, str] = {}   # id_tisk -> id_osoba (jediný předkladatel, může chybět)
    for cols in read_unl(archive, "tisky.unl"):
        if len(cols) < 9:
            continue
        id_tisk, id_druh, id_navrh, id_org_obd, id_osoba = (
            cols[0], cols[1], cols[5], cols[7], cols[8],
        )
        if id_org_obd != str(id_organ):
            continue
        if id_druh != _NEVLADNI_NAVRH_ZAKONA or id_navrh not in _POSLANECKE_ID_NAVRH:
            continue
        eligible[id_tisk] = id_osoba

    group_submitters: Dict[str, set] = {}
    for cols in read_unl(archive, "predkladatel.unl"):
        if len(cols) < 2:
            continue
        id_tisk, id_osoba = cols[0], cols[1]
        if id_tisk in eligible and id_osoba:
            group_submitters.setdefault(id_tisk, set()).add(id_osoba)

    counts: Dict[str, int] = {}
    for id_tisk, single_osoba in eligible.items():
        osoby = group_submitters.get(id_tisk) or ({single_osoba} if single_osoba else set())
        for id_osoba in osoby:
            counts[id_osoba] = counts.get(id_osoba, 0) + 1
    return counts


def speech_metrics_by_person(debates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Podíl krátkých vystoupení a medián délky, čistě z délky `cleanText`.

    Předsedající se vylučují — řídí schůzi, nemluví věcně k bodu. Počítá se
    ze staženého vzorku rozprav; volající musí vzorek zvenčí popsat
    (viz `meta.sittingDays` v exportu).
    """
    by_person: Dict[str, List[int]] = {}
    for debate in debates:
        for message in debate.get("messages", []):
            source = message.get("source") or {}
            if source.get("isChair"):
                continue
            id_osoba = source.get("idOsoba")
            if not id_osoba:
                continue
            by_person.setdefault(str(id_osoba), []).append(len(message.get("cleanText", "")))

    out: Dict[str, Dict[str, Any]] = {}
    for id_osoba, delky in by_person.items():
        n = len(delky)
        if n < MIN_VYSTOUPENI_PRO_VECNOST:
            continue
        serazeno = sorted(delky)
        stred = n // 2
        median = float(serazeno[stred]) if n % 2 else (serazeno[stred - 1] + serazeno[stred]) / 2.0
        kratkych = sum(1 for d in delky if d < MIN_SUBSTANTIVE_CHARS)
        out[id_osoba] = {
            "vystoupeniVeVzorku": n,
            "medianDelkyZnaku": round(median, 1),
            "podilKratkychVystoupeni": round(kratkych / n, 4),
        }
    return out


def build_index(client, debates: List[Dict[str, Any]],
                politician_ids: List[str], id_organ: str = "174") -> Dict[str, Dict[str, Any]]:
    """
    Sestaví `IndexVecnosti` pro každého poslance z `politician_ids`
    (očekává se `idOsoba` už sestavených profilů — viz `export_web.py`).

    Docházku samostatně NENESE — tu už zveřejňuje `hlasovaciBilance`
    (Fáze 2, `voting_balance`) a duplikovat ji sem by jen rozjelo dvě kopie
    téhož čísla. Tenhle index nese jen to, co jinde na profilu není:
    poslanecké návrhy zákonů a rozklad vystoupení ze staženého vzorku.
    """
    navrhy = submitted_bills_by_person(client, id_organ=id_organ)
    vystoupeni = speech_metrics_by_person(debates)

    out: Dict[str, Dict[str, Any]] = {}
    for id_osoba in politician_ids:
        pocet_navrhu = navrhy.get(id_osoba, 0)
        vzorek = vystoupeni.get(id_osoba)
        if pocet_navrhu == 0 and vzorek is None:
            continue
        out[id_osoba] = {
            "poslaneckeNavrhyZakonu": pocet_navrhu,
            "vzorekVystoupeni": vzorek,
        }
    return out
