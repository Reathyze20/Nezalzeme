---
name: tribunal-audit
description: Fanuje subagenty na adversariální přezkum hraničních zamítnutí Tribunálu (třída BORDERLINE_DEFENSE z analyze_dismissals.py) proti skutečnému stenozáznamu. Produkuje jen report pro lidskou kontrolu — nikdy nezapisuje do verdicts/dataset.json. Použít, když chceš vědět, jestli Tribunál nezahodil skutečný rozpor.
---

# Tribunal audit

Cíl: najít případy, kde Obhájce/Arbitr možná chybně zamítli skutečný rozpor,
BEZ toho, aby cokoliv v `engine.sqlite` nebo `dataset.json` změnili. Tohle je
čistě diagnostický/reportovací skill — publikace nové anotace vede jedině přes
`run_pipeline.py` (viz incident 28.8.2026 v [CLAUDE.md](../../../CLAUDE.md)).

## Postup

1. Spusť `python pipeline/analyze_dismissals.py` pro přehled rozdělení tříd.
2. Vytáhni VŠECHNY `verdict_id` ve třídě `BORDERLINE_DEFENSE` (ne jen jeden
   reprezentativní příklad, který dává skript) — dotaz přímo nad
   `pipeline/data/engine.sqlite` (tabulky `verdicts`, `candidate_pairs`,
   `nli_results`, `claims`, stejný JOIN jako v `analyze_dismissals.py`), nebo
   znovupoužij `classify_dismissal()` importem z toho modulu nad všemi řádky.
   Needituj `analyze_dismissals.py` kvůli tomu — je to jen čtení navíc.
3. Pro každý nalezený hraniční případ (typicky nízké desítky) spusť souběžně
   subagenta (Agent tool, `general-purpose`) — všechny v jedné zprávě, ne
   sekvenčně. Pokud je případů hodně (> ~15), vezmi náhodný vzorek a řekni
   uživateli přesně kolik a proč jsi zbytek vynechal (žádné tiché ořezání).
   Každému subagentovi dej:
   - `extracted_claim` obou výroků z páru, `defenseEvaluated`, `arbiterRationale`
   - `proof.sourceUrl` / `pastQuote`, pokud u páru existují
   - úkol: přečíst skutečný stenozáznam na `sourceUrl` a adversariálně posoudit,
     jestli zamítnutí Tribunálu bylo oprávněné — vrátit `DISMISSAL_CORRECT` nebo
     `POSSIBLE_MISS` + jednovětý důvod
   - výslovně mu řekni: **jen suď, nikam nezapisuj**
4. Slož report: tabulka `verdict_id → třída → subagent verdikt → důvod`,
   `POSSIBLE_MISS` nahoře.
5. Pokud je `POSSIBLE_MISS`, řekni uživateli ať to ověří ručně (např.
   `run_pipeline.py --faze tribunal` na dané schůzi) — tenhle skill sám
   o sobě nic nepublikuje ani neopravuje.

## Tvrdé pravidlo

Tenhle skill nikdy nepíše do `verdicts`, `engine.sqlite` ani `dataset.json`
a nevolá zápisové funkce v `db.py`. Je to jen čtení a úsudek. Pokud subagent
navrhne konkrétní opravenou anotaci, je to podnět k ruční revizi člověkem
přes `run_pipeline.py` — ne věc k rovnou zapsání (přesně tohle obcházení
způsobilo incident z 28. 8. 2026).
