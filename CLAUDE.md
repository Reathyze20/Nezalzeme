# Nezalžeme.cz

Systém občanské transparentnosti nad stenozáznamy Poslanecké sněmovny ČR — detekuje
rozpory mezi slovními projevy poslanců a jejich hlasováním, rozpory v čase a faktické
nepřesnosti. Celá důvěryhodnost produktu stojí na tvrzení „všechno je dohledatelné
ve stenozáznamu" — proto jsou pravidla níže tvrdá, ne stylistická preference.

## Incident 28. 8. 2026 — proč jsou pravidla níže nekompromisní

`pipeline/investigator.py` dřív obsahoval `INVESTIGATIVE_CASES`: 11 ručně napsaných
"nálezů" pod skutečnými jmény poslanců (Skopeček, Babiš, Schillerová, Jurečka,
Havlíček, Richterová, Hřib, Okamura) s vymyšlenými čísly hlasování, daty a větami
obhajoby. `apply_investigative_cases()` je zapisovala přímo do `verdicts` a
`export_web.py` je pak publikoval — **22 z 22 anotací na produkci k 28. 8. 2026
pocházelo odsud, ne z `run_pipeline.py`.** Funkce navíc obcházela důkazní bránu:
když `verify_proof.py` selhala, `proof_ok` se přesto nastavilo na 1, pokud se
hledaný podřetězec našel v lokálním textu.

Sanitace téhož dne: všech 22 řádků smazáno z `engine.sqlite`, soubor zredukován na
dokumentační stub (needitovat — je to záměrný tombstone). Jediná legitimní cesta
dat do `verdicts` je `run_pipeline.py` — s `engine_version` začínajícím na
`db.PIPELINE_ENGINE_PREFIX` (`"run-pipeline"`), jinak `db.annotation_provenance()`
a tím pádem `export_web.py` položku vykáže jako `handAuthored`, ne jako ověřený
strojový výstup. **Jakýkoliv přímý zápis do `verdicts` mimo `db.py`/`run_pipeline.py`
je přesně tenhle vzorec** — než to uděláš, zeptej se, ne implementuj.

Fáze 3 (`pipeline/slovo_cin.py`, „Slovo vs. Čin") píše do vlastní tabulky
`slovo_cin`, ne do `verdicts` — záměrně: není to obvinění se skóre a závažností,
ale doklad „řečeno vs. hlasováno". Má vlastní důkazní bránu
(`export_web.verify_slovo_cin`), která při **každém** exportu znovu odvodí každou
položku z otevřených dat (hlasování existuje, není zmatečné, hlas poslance sedí,
shoda se přepočítá) — jednou ověřeno neznamená ověřeno navždy, přesně kvůli
incidentu výš.

## Struktura a pořadí pipeline

```
pipeline/               # Python pipeline (fetch → detekce → ověření → export)
  psp/                  # Scrapery a parsery stenozáznamů, hlasování, otevřených dat
  data/                 # Stažená data, gold sety, engine.sqlite (stav pipeline, idempotentní)
  tests/
src/                     # Next.js webová aplikace
  data/psp/dataset.json  # JEDINÝ vstup webu — generuje ho výhradně export_web.py
```

Pořadí: `fetch_psp.py` → `run_pipeline.py --faze claims|retrieval|nli|tribunal|slovocin|verify`
(nebo `--faze vse` / `--pokracovat`) → `export_web.py` → verifikace (viz níže). Detaily
a přesné příkazy jsou v [README.md](README.md).

## Tvrdé konvence (neporušovat bez explicitní domluvy)

- **`dataset.json` se needituje ručně** — jediný legitimní zdroj je `export_web.py`.
- **Žádná anotace bez ověření** — `verify_proof.py` musí projít (`proof.pastQuote`
  musí ležet na `proof.sourceUrl`). Pokud selže, oprav zdroj v pipeline, neobcházej
  to ručním zásahem do datasetu.
- **Dvouprahový model:** `>= 0.95` PUBLISHED, `>= 0.80` CONTEXT_DEVELOPMENT, `< 0.80` DROPPED.
- **`pipeline/psp_verify.py` a scrapery v `pipeline/psp/` se needitují bez pádného
  důvodu** — jsou to nejzdravější/nejvíc prověřené části projektu. Spustit
  `psp_verify.py --vzorek 5` po každém zásahu do parseru; selhání = signál problému
  jinde (v datech/parseru), ne věc k "opravení" v samotném verify skriptu.
- **Značka se nikdy nevyrenderuje bez ověřené kotvy do zdroje.** `proof.sourceUrl`
  musí mířit na konkrétní stenoprotokol (`psp.cz/eknih/...`) nebo hlasování (s
  `voteRecorded` a `votingBallotId`) — ne na rozcestník.
- **`SESSION_RECORDINGS` v `src/data/mediaMap.ts` je záměrně prázdný.** Nikdy
  nevymýšlet YouTube ID záznamů schůzí "na zkoušku" a nenechávat ho v repu —
  vede to k odkazu na důkaz, který vede jinam nebo nikam. Chybí-li pairing,
  UI správně hlásí "nespárováno".
- **`SAMPLE_DEBATES` v `src/data/debatesData.ts` je odpojená fixtura** — nic ji
  neimportuje do produkční cesty a nesmí se tam vracet. Obsahuje smyšlená jména
  a kluby (Vrána, Kovářová, Doležal…) — vrácení do `src/lib/debate.ts` by dalo
  smyšlený citát pod skutečné jméno (žalovatelné + popírá premisu produktu).
  UI čte výhradně `DEBATES` z `src/lib/debate.ts`, filtrované přes
  `CONFIDENCE_THRESHOLD`.

## Zdroj dat PSP — nedokumentované, ale load-bearing

Sněmovna **nemá JSON/REST API**. `steno.zip`/`steno.unl` je pro aktuální období
nepoužitelný (poslední řádek z r. 2024) a `hl-2025ps.zip` slučuje "zdržel se" a
"nehlasoval" do jednoho kódu — obojí implementováno v `pipeline/psp/` obcházením
přes HTML (`bqbs/bTTTBBBNN.htm` pro text s časovou značkou, `sqw/hlasy.sqw?G=`
pro hlasování). Čas ve stenoznačkách je dvojznačný (chybí vodicí nuly, přetéká
přes půlnoc) a kotva do `sSSSTTT.htm#rN` se musí párovat, ne dopočítat. Než sáhneš
do `pipeline/psp/`, přečti si `pipeline/psp_verify.py` — ověřuje výstup proti
nezávislým zdrojům u Sněmovny, ne sám proti sobě.

## Hranice datová vrstva ↔ FE

**Datová/pipeline vrstva (needitovat bez rozmyslu):** `src/types/debate.ts`,
`src/data/debatesData.ts`, `src/data/mediaMap.ts`, `src/lib/debate.ts`, `src/lib/media.ts`.
**FE vrstva:** `src/lib/poslanci.ts`, `src/lib/ui.ts`, `components/zaznam`,
`components/rejstrik`, `components/rozprava`, `components/poslanec`, routy pod `app/`.
`Message` nemá pole `id` (slug se generuje z příjmení přes `politicianSlug()`) ani
`replyTo` — nedomýšlet konverzační strukturu, která není v datech.

## Verifikace (spouštět po zásahu do pipeline nebo před exportem)

```bash
python pipeline/validate.py
python pipeline/verify_proof.py --input src/data/psp/dataset.json
python pipeline/eval_gold.py
python pipeline/eval_retrieval.py
python pipeline/psp_verify.py --vzorek 5
python -m pytest pipeline/tests/ -v
npx tsc --noEmit -p .
```

Skill `/pipeline-check` (`.claude/skills/pipeline-check/`) spustí celou sadu najednou
paralelně. Skill `/tribunal-audit` (`.claude/skills/tribunal-audit/`) fanuje
subagenty na adversariální přezkum hraničních zamítnutí Tribunálu proti
stenozáznamu — jen report, nikdy zápis do `verdicts`/`dataset.json`.
