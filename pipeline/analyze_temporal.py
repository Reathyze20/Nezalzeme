"""
Ruční ukázky struktury značky pro Nezalžeme.cz.

Tento modul slouží VÝHRADNĚ jako tvarová šablona — ukazuje, jak vypadá
hotová anotace vyplněná lidskou rukou. Doložení (pole `proof`) je
ILUSTRATIVNÍ A NEOVĚŘENÉ: citáty nebyly nalezeny na uvedených stránkách
a hlasovací záznamy nebyly ověřeny proti skutečným datům z hlasy.sqw.

Do korpusu (`pipeline/data/psp/*.json`) se nic nezapisuje.
Výstup jde výhradně do `pipeline/data/hand_authored_examples.json`,
který `export_web.py` nečte — není to tedy cesta na web.

Spuštění:
    python pipeline/analyze_temporal.py

Výstup: pipeline/data/hand_authored_examples.json
"""

import io
import json
import os
from typing import Any, Dict, List

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(PIPELINE_DIR, "data", "hand_authored_examples.json")

# ---------------------------------------------------------------------------
# Pomocná funkce pro výpočet znakovych offsetů (používá engine i v produkci)
# ---------------------------------------------------------------------------

def znacka(clean_text: str, snippet: str, **rest: Any) -> Dict[str, Any]:
    """Vygeneruje anotaci s přesnými znakovými indexy."""
    import re
    start = clean_text.find(snippet)
    if start == -1:
        for s in re.split(r"(?<=[.?!])\s+", clean_text):
            if snippet in s or s in snippet:
                start = clean_text.find(s)
                snippet = s
                break
    if start == -1:
        raise ValueError(f"Úryvek {snippet!r} nebyl nalezen v textu vystoupení!")
    rest["start"] = start
    rest["end"] = start + len(snippet)
    rest["targetSnippet"] = snippet
    return rest


# ---------------------------------------------------------------------------
# Ručně napsané ukázky struktury značky
#
# VAROVÁNÍ: proof.pastQuote a proof.votingBallotId jsou ILUSTRATIVNÍ.
# Nebyly ověřeny proti skutečnému obsahu citovaných stránek ani hlasovacím
# datům. Tyto příklady NESMÍ být publikovány jako obvinění.
# ---------------------------------------------------------------------------

HAND_AUTHORED_EXAMPLES: List[Dict[str, Any]] = [
    {
        "speaker": "Andrej Babiš",
        "type": "CONTRADICTION_TIME",
        "severity": "HIGH",
        "shortBadgeLabel": "Rozpor s dřívějším postojem k daňovým úlevám",
        "explanation": "Příslib zavedení daňových prázdnin pro rodiny je v logickém rozporu s dřívějším postojem k rušení a sjednocování daňových výjimek v rámci daňového balíčku, kde řečník argumentoval nutností zjednodušení daňového řádu bez dalších selektivních úlev.",
        "confidenceScore": 0.93,
        "nliRelation": "CONTRADICTION",
        "claimCategory": "STANCE_COMMITMENT",
        "producedBy": "hand-authored-seed",
        "adversarialCheck": {
            "passed": True,
            "defenseEvaluated": "Zkoumáno, zda nešlo o sociální kompenzaci inflace; daňový slib byl formulován jako systémová daňová reforma, nikoli jednorázová dávka.",
            "defensesConsidered": [
                "Mezi výroky se změnila demografická situace rodin s více dětmi.",
                "Původní rušení výjimek se týkalo podnikatelských subjektů, nikoli rodin.",
                "Výrok byl součástí politického programu hnutí, nikoliv návrhem konkrétního zákona.",
            ],
        },
        "proof": {
            "_warning": "ILUSTRATIVNÍ — pastQuote nebyla nalezena na uvedené sourceUrl.",
            "pastQuote": "Základním principem je jednoduchý daňový systém bez stovek výjimek a selektivních úlev. Každá nová výjimka systém deformuje.",
            "pastDate": "2024-05-15",
            "pastContext": "Rozprava k daňovému balíčku, 102. schůze",
            "sourceUrl": "https://www.psp.cz/eknih/2021ps/stenprot/102schuz/s102045.htm",
        },
    },
    {
        "speaker": "Karel Havlíček",
        "type": "VALUE_SHIFT",
        "severity": "MEDIUM",
        "shortBadgeLabel": "Změna postoje ke zdanění neočekávaných zisků",
        "explanation": "Oponentní přezkum posoudil vývoj postoje k sektorovému zdanění energetických firem. V roce 2022 opozice windfall tax sama požadovala, nyní kritizuje její dopady na akcionáře jako nepřijatelné.",
        "confidenceScore": 0.89,
        "nliRelation": "NEUTRAL",
        "claimCategory": "FACTUAL_CLAIM",
        "producedBy": "hand-authored-seed",
        "adversarialCheck": {
            "passed": False,
            "downgradedFrom": "CONTRADICTION_TIME",
            "defenseEvaluated": "Obhajoba obstála: kritika nesměřuje proti principu zdanění mimořádných zisků jako takovému, ale proti konkrétnímu nastavení parametrů a délce platnosti daně.",
            "defensesConsidered": [
                "Kritika míří na technické provedení srážkové daně, nikoli na princip solidarity.",
                "Ceny energií na burze v mezidobí klesly na předválečnou úroveň.",
                "Řečník reaguje na soudní žaloby minoritních akcionářů.",
            ],
        },
        "proof": {
            "_warning": "ILUSTRATIVNÍ — pastQuote nebyla nalezena na uvedené sourceUrl.",
            "pastQuote": "Stát musí okamžitě sáhnout na mimořádné zisky energetických gigantů a vrátit tyto peníze lidem a firmám.",
            "pastDate": "2022-09-08",
            "pastContext": "Mimořádná schůze k energetické krizi, 36. schůze",
            "sourceUrl": "https://www.psp.cz/eknih/2021ps/stenprot/036schuz/s036014.htm",
        },
    },
    {
        "speaker": "Marian Jurečka",
        "type": "CONTRADICTION_TIME",
        "severity": "HIGH",
        "shortBadgeLabel": "Posun výkladu zákona o rozpočtové odpovědnosti",
        "explanation": "Řečník v únoru 2026 napadá vládu za překročení výdajových rámců zákona č. 23/2017 Sb., ačkoliv v předchozím volebním období jako člen vlády sám obhajoval novelu posouvající trajektorii konsolidace.",
        "confidenceScore": 0.92,
        "nliRelation": "CONTRADICTION",
        "claimCategory": "FACTUAL_CLAIM",
        "producedBy": "hand-authored-seed",
        "adversarialCheck": {
            "passed": True,
            "defenseEvaluated": "Posuzováno, zda se nezměnil zákonný konsolidační cíl; zákon 23/2017 Sb. stanoví závazné tempo snižování strukturálního deficitu o 0,5 % HDP ročně.",
            "defensesConsidered": [
                "Změna role z ministra na opozičního poslance kontrolujícího vládu.",
                "Novela zákona o rozpočtové odpovědnosti byla reakcí na inflační šok.",
                "Interpelace se týká procedury schvalování, nikoli výše schodku.",
            ],
        },
        "proof": {
            "_warning": "ILUSTRATIVNÍ — pastQuote nebyla nalezena na uvedené sourceUrl.",
            "pastQuote": "Konsolidace veřejných financí musí být realistická. Úprava výdajových rámců v zákoně č. 23/2017 Sb. umožní nesnížit investice do infrastruktury.",
            "pastDate": "2023-10-25",
            "pastContext": "Rozprava k vládnímu konsolidačnímu balíčku, 78. schůze",
            "sourceUrl": "https://www.psp.cz/eknih/2021ps/stenprot/078schuz/s078033.htm",
        },
    },
    {
        "speaker": "Alena Schillerová",
        "type": "VOTE_MISMATCH",
        "severity": "CRITICAL",
        "shortBadgeLabel": "Rozpor s hlasováním o rozpočtových kapitolách",
        "explanation": "Kritika deficitu a 'děr v rozpočtu' je v přímém rozporu s hlasováním poslankyně, která na 14. schůzi v dubnu 2026 hlasovala pro navýšení výdajů v celkem 12 pozměňovacích návrzích bez uvedení příjmového krytí.",
        "confidenceScore": 0.96,
        "nliRelation": "CONTRADICTION",
        "claimCategory": "FACTUAL_CLAIM",
        "producedBy": "hand-authored-seed",
        "adversarialCheck": {
            "passed": True,
            "defenseEvaluated": "Oponentura prověřovala, zda pozměňovací návrhy nebyly kryty vládní rozpočtovou rezervou; celkový objem požadavků rezervu trojnásobně převyšoval.",
            "defensesConsidered": [
                "Pozměňovací návrhy byly financovány z předpokládaného nadpříjmu daní.",
                "Hlasování vyjadřovalo politické priority klubu, nikoli finální zákon.",
                "Výrok byl pronesen v emotivní debatě v rámci faktické poznámky.",
            ],
        },
        "proof": {
            "_warning": "ILUSTRATIVNÍ — votingBallotId a hlasovací výsledek nebyly ověřeny; skutečné hlasování č. 87120 má jiné datum, schůzi i výsledek.",
            "pastQuote": "Hlasování č. 87115 k pozměňovacímu návrhu A4 na navýšení výdajů (14. 4. 2026): Schillerová A. — PRO.",
            "pastDate": "2026-04-14",
            "pastContext": "Hlasování o státním rozpočtu, 14. schůze, 1. den",
            "sourceUrl": "https://www.psp.cz/eknih/2025ps/stenprot/014schuz/s014088.htm",
            "voteRecorded": "PRO",
            "votingBallotId": "Hlasování č. 87115, 14. schůze (14. 4. 2026)",
        },
    },
    {
        "speaker": "Jan Jakob",
        "type": "VALUE_SHIFT",
        "severity": "LOW",
        "shortBadgeLabel": "Posun v pojetí klubové disciplíny",
        "explanation": "Řečník zdůrazňuje volný mandát poslance, ačkoliv při projednávání vládních předloh v březnu 2026 apeloval na striktní dodržování koaliční smlouvy a jednotné hlasování poslaneckého klubu.",
        "confidenceScore": 0.85,
        "nliRelation": "NEUTRAL",
        "claimCategory": "STANCE_COMMITMENT",
        "producedBy": "hand-authored-seed",
        "adversarialCheck": {
            "passed": False,
            "downgradedFrom": "CONTRADICTION_TIME",
            "defenseEvaluated": "Obhajoba obstála: řečník reagoval na personální volbu členů orgánů, kde je tajné a volné hlasování standardem jednacího řádu.",
            "defensesConsidered": [
                "Výrok padl v debatě o tajné volbě, nikoli o věcném zákonu.",
                "Koaliční smlouva nevylučuje individuální svědomí poslance.",
                "Rozdíl mezi procedurální volbou a programovým hlasováním.",
            ],
        },
        "proof": {
            "_warning": "ILUSTRATIVNÍ — pastQuote nebyla nalezena na uvedené sourceUrl.",
            "pastQuote": "Koaliční dohoda je pro všechny členy klubu závazná. Bez jednoty nemůžeme prosadit programové prohlášení.",
            "pastDate": "2026-03-03",
            "pastContext": "Tiskový briefing poslaneckého klubu TOP 09, 10. schůze",
            "sourceUrl": "https://www.psp.cz/eknih/2025ps/stenprot/010schuz/s010012.htm",
        },
    },
    {
        "speaker": "Tomio Okamura",
        "type": "FACTUAL_MISSTATEMENT",
        "severity": "LOW",
        "shortBadgeLabel": "Nepřesná citace paragrafu jednacího řádu",
        "explanation": "Jmenovité hlasování o důvěře vládě upravuje § 75 odst. 2 ve spojení s § 85 zákona č. 90/1995 Sb., nikoli obecná úvodní ustanovení.",
        "confidenceScore": 0.91,
        "nliRelation": "CONTRADICTION",
        "claimCategory": "FACTUAL_CLAIM",
        "producedBy": "hand-authored-seed",
        "adversarialCheck": {
            "passed": True,
            "defenseEvaluated": "Jde o formální chybu v odkazu na paragraf jednacího řádu PSP ČR; faktický průběh hlasování tím nebyl zpochybněn.",
            "defensesConsidered": [
                "Formální přeřeknutí při řízení schůze.",
                "Text byl převzat z podkladů legislativního odboru Kanceláře PSP.",
                "Význam procedury byl pro všechny přítomné poslance zřejmý.",
            ],
        },
        "proof": {
            "_warning": "ILUSTRATIVNÍ — citace zákonného textu, ne výroku z konkrétní schůze.",
            "pastQuote": "Zákon č. 90/1995 Sb., o jednacím řádu Poslanecké sněmovny — § 75 odst. 2 a § 85 (hlasování podle jmen).",
            "pastDate": "2026-01-15",
            "pastContext": "Sbírka zákonů ČR / Jednací řád PSP ČR",
            "sourceUrl": "https://www.psp.cz/eknih/2025ps/stenprot/005schuz/s005001.htm",
        },
    },
]


def export_hand_authored_examples() -> int:
    """
    Zapíše ruční ukázky do pipeline/data/hand_authored_examples.json.

    Tento soubor NENÍ čten export_web.py a NEDOSTANE SE na web.
    Slouží výhradně jako referenční vzor struktury značky pro vývoj enginu.
    """
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    output = {
        "_note": (
            "Ruční ukázky struktury anotace. Pole proof je ILUSTRATIVNÍ "
            "a NEOVĚŘENÉ — citáty nebyly nalezeny na citovaných stránkách. "
            "Tento soubor není čten export_web.py a nedostane se na web."
        ),
        "examples": HAND_AUTHORED_EXAMPLES,
    }
    with io.open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
    print(f"Zapsáno {len(HAND_AUTHORED_EXAMPLES)} ukázek do {OUTPUT_PATH}")
    print("VAROVÁNÍ: Tyto ukázky mají neověřené doložení a nesmí být publikovány.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(export_hand_authored_examples())
