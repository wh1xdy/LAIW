# LAIW — Law AI for Sweden/EU

Fine-tuning **Mistral 7B** on Swedish and EU legal data to create a Swedish legal expert model.

## Status

- Pipeline (corpus, preprocessing, training, evaluation): complete.
- Proof of concept: complete and reproducible — see below and [`POC_EVALUATION.md`](POC_EVALUATION.md).
- Full-corpus fine-tune: blocked on compute. A stable run needs a bf16 base on a
  dedicated GPU; the 4-bit base used here is numerically unstable at scale.

## Proof of concept: citation correction

Mistral 7B hallucinates Swedish legal citations. A small, focused LoRA fine-tune on
verified citations corrects this reliably.

| Correct SFS number (4 statutes, 5 prompts) | Base Mistral 7B | LAIW fine-tune |
|---|---|---|
| | 0/5 | 5/5 |

All target numbers verified against riksdagen.se. Trained in ~5 minutes on an Apple
M5 Pro (54 examples, 8 LoRA layers, lr 3e-5, 5.7 GB peak, val loss 1.78 -> 0.16).
Method, verbatim transcripts, and sources in [`POC_EVALUATION.md`](POC_EVALUATION.md).

## Dataset

| Källa | Innehåll | Storlek |
|-------|----------|---------|
| Riksdagen SFS | Alla svenska lagar | ~192 MB |
| Riksdagen Prop | ~19,964 propositioner | ~9.7 GB |
| Riksdagen Bet | ~19,466 betänkanden | ~2.8 GB |
| Riksdagen SOU | ~4,896 statliga utredningar | ~6.6 GB |
| Riksdagen Ds | ~1,635 departementsserien | ~1 GB |
| Riksdagen Prot | ~9,992 protokoll | ~4.3 GB |
| Riksdagen Mot | ~9,905 motioner (10k unika) | ~280 MB |
| Riksdagen Fr | ~9,999 skriftliga frågor | ~47 MB |
| Riksdagen Ip | ~9,943 interpellationer | ~27 MB |
| Riksdagen Dir | ~788 kommittédirektiv | ~10 MB |
| Riksdagen Yttr | ~4,588 yttranden | ~100 MB |
| EU-rätt | 10,745/34,133 texter | ~1.2 GB |
| Domstolar | ~16,626 avgöranden | ~409 MB |
| JO | 3,714 beslut | ~3.9 MB |
| SAOB | 75,111 artiklar (27,737 nya + 47,374 cachade) | ~72 MB |
| JO | 3,714 beslut | ~3.9 MB |
| JK | 10 beslut (JS-renderad, begränsad) | ~0.1 MB |
| DO | 33 beslut (JS-renderad, begränsad) | ~0.2 MB |

**Preprocessat dataset (dataset.jsonl): ~162,000 dokument** (efter SAOB-tillägg)

## Struktur

```
LAIW/
├── scripts/
│   ├── download_riksdagen.py     # SFS, Prop, Bet, SOU, Ds, Prot, Mot, Fr, Ip, Dir
│   ├── fetch_riksdagen_texts.py  # Hämtar fulltext XML (async, 8 workers)
│   ├── download_eurlex.py        # EU-förordningar och direktiv (SPARQL+HTML)
│   ├── fetch_eurlex_texts.py     # Hämtar EU-texter i HTML
│   ├── download_domstolar.py     # Domstolsavgöranden
│   ├── download_myndigheter.py   # JO/JK/DO/DI-beslut
│   ├── download_saob.py          # SAOB ordbok + artikelnedladdning (async, 3 workers)
│   ├── saob_deep_index.py        # Djup SAOB-indexering via scrollist-API
│   └── preprocess.py             # Raw → JSONL träningsdataset
├── tools/                        # RAG-verktyg för inferens
│   ├── legal_search.py           # search_sfs, get_law, search_riksdagen, search_domstol, search_eurlex
│   ├── chat.py                   # Interaktiv chat-loop med verktygsanrop
│   └── __init__.py
├── data/                         # (gitignorerad - för stor)
│   ├── raw/                      # Rådata per källa
│   └── processed/                # Färdigt JSONL-dataset
└── logs/                         # (gitignorerad)
```

## Kom igång

```bash
# Installera beroenden
pip install beautifulsoup4 lxml aiohttp

# Ladda ner riksdagsdata (alla typer)
python3 scripts/download_riksdagen.py
python3 scripts/fetch_riksdagen_texts.py --workers 8

# EU-rätt
python3 scripts/download_eurlex.py
python3 scripts/fetch_eurlex_texts.py

# Domstolspraxis
python3 scripts/download_domstolar.py --skip-pdfs

# Myndighetsbeslut
python3 scripts/download_myndigheter.py --source jo

# SAOB ordbok
python3 scripts/saob_deep_index.py   # bygg ordindex (~2 timmar)
python3 scripts/download_saob.py     # ladda ner artiklar (~55 timmar)

# Preprocessa allt till JSONL
python3 scripts/preprocess.py --source all
```

## Preprocessat dataset

- **~130,000 dokument, ~22 GB** (2026-05-22, merge pågår)
- Plats: `~/LAIW/data/processed/dataset.jsonl`
- Format: JSONL, ett dokument per rad: `{"text":"...","source":"...","meta":{}}`

## RAG-verktyg (inferens)

Modellen kan söka i juridiska källor live vid inferenstid via `tools/`:

```python
from tools import search_sfs, get_law, search_riksdagen, search_domstol, search_eurlex

# Sök lagar
results = search_sfs("avtalslagen")

# Hämta fulltext
law = get_law("SFS-1915-218")

# Interaktiv chat med verktygsanrop (kräver ANTHROPIC_API_KEY)
# python3 -m tools.chat
```

Verktyg: `search_sfs`, `get_law`, `search_riksdagen`, `search_domstol`, `search_eurlex`  
Kompatibel med Anthropic API tool_use samt Mistral function calling.

## Kända begränsningar

- **EU-texter**: EUR-Lex använder AWS WAF JS-utmaning — direktnedladdning blockeras vid ~10k texter
- **SAOB artiklar**: ~55 timmar att ladda ner alla 500k artiklar — kör med nohup
- **JK/DO/DI-beslut**: JavaScript-renderade sidor — statisk HTML ger <50 beslut per källa

## Modell

Målet är att fine-tuna **Mistral 7B Instruct** med LoRA/QLoRA för att svara på juridiska frågor om svensk och EU-rätt.
