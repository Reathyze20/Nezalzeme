# Nezalžeme.cz

Systém občanské transparentnosti nad stenozáznamy Poslanecké sněmovny Parlamentu ČR. Detekuje rozpory mezi slovními projevy poslanců a jejich hlasováním, rozpory v čase a faktické nepřesnosti.

## Struktura

```
pipeline/               # Python pipeline (detekce, ověřování, export)
  psp/                  # Scrapery a parsery stenozáznamů, hlasování, otevřených dat
  data/                 # Stažená data, gold sety, engine.sqlite
  tests/                # Pytest testy deterministické vrstvy
src/                    # Next.js webová aplikace
  app/                  # Stránky (App Router)
  components/           # React komponenty
  data/psp/             # Generovaný dataset.json (výstup export_web.py)
  types/                # TypeScript datový kontrakt
```

## Prerekvizity

- Python 3.10+ (testováno na 3.12)
- Node.js 18+ (pro webovou aplikaci)

## Nastavení prostředí

```bash
# Python venv + závislosti
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r pipeline/requirements.txt

# Node.js závislosti
npm install
```

## Pipeline — pořadí spuštění

### 1. Stažení dat

```bash
# Stáhne stenozáznamy a hlasování z webu PSP ČR
python pipeline/fetch_psp.py
```

### 2. Analýza (claims → retrieval → NLI → tribunál → ověření)

```bash
# Celá pipeline na jedné schůzi (doporučeno pro pilot)
python pipeline/run_pipeline.py --schuze 10 --faze vse

# Jen jedna fáze
python pipeline/run_pipeline.py --faze claims
python pipeline/run_pipeline.py --faze retrieval
python pipeline/run_pipeline.py --faze nli
python pipeline/run_pipeline.py --faze tribunal
python pipeline/run_pipeline.py --faze verify

# Pokračovat tam, kde pipeline skončila (přeskočí hotové)
python pipeline/run_pipeline.py --pokracovat

# Backend bez API nákladů (prompty do JSONL fronty)
python pipeline/run_pipeline.py --backend jsonl
```

### 3. Export do webu

```bash
python pipeline/export_web.py
```

Vygeneruje `src/data/psp/dataset.json` — jediný vstup webové aplikace.

## Verifikace

```bash
# Regresní kontrola schématu nad skutečným korpusem
python pipeline/validate.py

# Ověření důkazů (proof.pastQuote musí ležet na proof.sourceUrl)
python pipeline/verify_proof.py --input pipeline/data/hand_authored_examples.json

# Gold set — precision/recall deterministické vrstvy
python pipeline/eval_gold.py

# Gold set — recall retrievalu, precision NLI (odděleně)
python pipeline/eval_retrieval.py

# Kontrola integrity korpusu (náhodný vzorek)
python pipeline/psp_verify.py --vzorek 5

# Pytest testy
python -m pytest pipeline/tests/ -v

# TypeScript typecheck
npx tsc --noEmit -p .
```

## Webová aplikace

```bash
npm run dev          # development server (http://localhost:3000)
npm run build        # produkční build
```

## Klíčové konvence

- **Žádné ruční úpravy `dataset.json`** — generuje ho `export_web.py`.
- **Žádné anotace bez ověření** — `verify_proof.py` musí projít, jinak export selže.
- **Dvouprahový model** — `>= 0.95` PUBLISHED (obvinění), `>= 0.80` CONTEXT_DEVELOPMENT (kontext), `< 0.80` DROPPED.
- **Stav pipeline je v `engine.sqlite`** — idempotentní, opakovatelné spuštění.
- **`psp_verify.py` a scrapery se needitují** — nejzdravější části projektu.
