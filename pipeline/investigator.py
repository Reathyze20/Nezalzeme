"""
Investigativní Engine Nezalžeme.cz (pipeline/investigator.py) — VYŘAZENO.

Tenhle soubor dřív obsahoval `INVESTIGATIVE_CASES`: 11 ručně napsaných "nálezů"
pod skutečnými jmény poslanců (Skopeček, Babiš, Schillerová, Jurečka, Havlíček,
Richterová, Hřib, Okamura) s vymyšlenými čísly hlasování, daty a větami obhajoby,
které `apply_investigative_cases()` zapisovala přímo do `verdicts` a které
`export_web.py` pak publikovalo na webu — 22 z 22 anotací na produkci k 28. 8. 2026
pocházelo odsud, ne z `run_pipeline.py`.

Kontrola dat prokázala nesoulad (citace neodpovídaly vysvětlení, čísla hlasování
si protiřečila s `explanation`, `proof.pastDate` neodpovídalo datu stenozáznamu,
na který mířil `proof.sourceUrl`) a funkce navíc obcházela důkazní bránu: když
`verify_annotation()` selhala, `proof_ok` se přesto nastavilo na 1, pokud se
hledaný podřetězec našel v lokálním textu (řádky 493–496 staré verze). To je
přesně past popsaná v paměti `ukazkova-data-jsou-smyslena` — smyšlené tvrzení pod
skutečným jménem, žalovatelné a popírající premisu produktu ("všechno je
dohledatelné ve stenozáznamu").

Sanitace (28. 8. 2026): všech 22 řádků smazáno z `engine.sqlite`
(`DELETE FROM verdicts WHERE model_name = 'investigative-matcher'`), soubor
zredukován na tento dokumentační stub. Nahrazuje ho `pipeline/slovo_cin.py`
(Slovo vs. Čin — postoj z rozpravy proti jmenovitému hlasování), který každou
publikovanou položku znovu odvozuje z otevřených dat PSP ČR při exportu, místo
aby jí věřil na základě toho, že ji někdo jednou ověřil ručně.

Pokud se sem někdo vrátí hledat `INVESTIGATIVE_CASES`: nevracet. Žádný nález se
nesmí do `verdicts` dostat jinak než průchodem `run_pipeline.py` nebo
`pipeline/slovo_cin.py`, obojí s `engine_version` začínajícím na
`db.PIPELINE_ENGINE_PREFIX` — jinak ho `db.annotation_provenance()` a tím pádem
`export_web.py` zase vykáže jako strojový výstup, i když je ruční.
"""
