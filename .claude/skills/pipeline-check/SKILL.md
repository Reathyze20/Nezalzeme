---
name: pipeline-check
description: Spustí celou regresní/verifikační sadu nad pipeline (validate, verify_proof, eval_gold, eval_retrieval, psp_verify, pytest, tsc) a shrne PASS/FAIL. Použít po každé změně v pipeline/ nebo před exportem do webu.
---

# Pipeline check

Všech 7 kroků níže je vzájemně nezávislých (jen čtou `engine.sqlite`/data/testy,
nic nezapisují) — spusť je najednou jako 7 paralelních Bash tool callů v jedné
zprávě, ne sekvenčně jeden po druhém. Nezastavuj se, když některý selže — seber
výsledek každého a na konci vypiš souhrnnou tabulku krok → PASS/FAIL s první
relevantní chybovou hláškou u těch, co selhaly.

1. `python pipeline/validate.py` — regresní kontrola schématu nad skutečným korpusem
2. `python pipeline/verify_proof.py --input src/data/psp/dataset.json` — `proof.pastQuote` musí ležet na `proof.sourceUrl`

   Nemíří na `pipeline/data/hand_authored_examples.json`: ta fixtura je podle
   vlastního docstringu `analyze_temporal.py` **ilustrativní a záměrně
   neověřená** (citáty na uvedených stránkách nejsou), takže tenhle krok na ní
   nikdy projít nemůže a jen dělal ze sady trvale červenou. Signál má nad tím,
   co se opravdu publikuje.
3. `python pipeline/eval_gold.py` — precision/recall deterministické vrstvy
4. `python pipeline/eval_retrieval.py` — recall retrievalu, precision NLI odděleně
5. `python pipeline/psp_verify.py --vzorek 5` — integrita korpusu, náhodný vzorek (síťové volání na psp.cz)
6. `python -m pytest pipeline/tests/ -v`
7. `npx tsc --noEmit -p .`

## Pravidla při selhání

- Selže-li `psp_verify.py` nebo něco v `pipeline/psp/`: nejde o chybu k opravě
  v samotném verify skriptu nebo scraperu (jsou to nejvíc prověřené části
  projektu) — jde o signál, že se změnil formát dat u Sněmovny nebo že downstream
  kód dělá špatný předpoklad. Diagnostikuj, než cokoliv edituješ v `pipeline/psp/`.
- Selže-li `verify_proof.py`: najdi a oprav zdroj v pipeline (retrieval/scoring).
  Nikdy neobcházej ručním zásahem do `src/data/psp/dataset.json` — ten se
  needituje ručně, generuje ho jen `export_web.py`.
- Selže-li `tsc`: zkontroluj, jestli změna nezasáhla hranici datová vrstva/FE
  (viz [CLAUDE.md](../../../CLAUDE.md)) — typová chyba na rozhraní `DEBATES`
  často znamená, že se sáhlo na `src/types/debate.ts` bez odpovídající úpravy FE.

Před exportem (`python pipeline/export_web.py`) by měla celá sada projít.
