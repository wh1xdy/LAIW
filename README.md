# LAIW — Law AI for Sweden/EU

Fine-tuning **Mistral 7B** on Swedish and EU legal data to create a Swedish legal expert model.

## Dataset (mål: ~300 GB)

| Källa | Innehåll | Storlek |
|-------|----------|---------|
| Riksdagen SFS | Alla svenska lagar | ~192 MB |
| Riksdagen Prop | ~19,964 propositioner | ~9.7 GB |
| Riksdagen Bet | ~19,466 betänkanden | ~2.8 GB |
| Riksdagen SOU | ~4,896 statliga utredningar | ~6.6 GB |
| Riksdagen Ds | ~1,635 departementsserien | ~1 GB |
| Riksdagen Prot | ~9,992 protokoll | ~4.3 GB |
| Riksdagen Mot | ~257,913 motioner | (laddar ner) |
| Riksdagen Fr | ~43,913 skriftliga frågor | (laddar ner) |
| Riksdagen Ip | ~15,667 interpellationer | (laddar ner) |
| Riksdagen Dir | ~6,385 kommittédirektiv | (laddar ner) |
| EU-rätt | 10,745/34,133 texter | ~1.2 GB |
| Domstolar | ~16,626 avgöranden | ~409 MB |
| JO | ~3,714 beslut | (laddar ner) |
| SAOB | ~500,000 ord | (bygger index) |

**Preprocessat dataset (dataset.jsonl): 93,318 dokument, 19.65 GB**

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
│   ├── download_saob.py          # SAOB ordbok + artikelnedladdning
│   ├── saob_deep_index.py        # Djup SAOB-indexering via scrollist-API
│   └── preprocess.py             # Raw → JSONL träningsdataset
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

## Status (2026-05-21)

| Dataset | Status | Dokument | Storlek |
|---------|--------|----------|---------|
| SFS (text) | ✅ | 9,994 XML | 192 MB |
| Prop (text) | ✅ | 19,964 XML | 9.7 GB |
| Bet (text) | ✅ | 19,466 XML | 2.8 GB |
| SOU (text) | ✅ | 4,896 XML | 6.6 GB |
| Ds (text) | ✅ | 1,635 XML | 1 GB |
| Prot (text) | ✅ | 9,992 XML | 4.3 GB |
| Mot (index) | 🔄 | 257,913 dok | laddar ner |
| Fr (index) | 🔄 | 43,913 dok | laddar ner |
| Ip (index) | 🔄 | 15,667 dok | laddar ner |
| Dir (index) | 🔄 | 6,385 dok | laddar ner |
| EU (texter) | ⚠️ WAF | 10,745/34,133 | 1.2 GB |
| Domstolar | ✅ | 16,626 avgöranden | 409 MB |
| JO | 🔄 | ~700/3,714 | laddar ner |
| SAOB index | 🔄 | ~17k/500k ord | bygger |

## Preprocessat dataset

- **93,318 dokument, 19.65 GB** (2026-05-21)
- Plats: `~/LAIW/data/processed/dataset.jsonl`
- Format: JSONL, ett dokument per rad: `{"text":"...","source":"...","meta":{}}`

## Kända begränsningar

- **EU-texter**: EUR-Lex använder AWS WAF JS-utmaning — direktnedladdning blockeras vid ~10k texter
- **SAOB artiklar**: ~55 timmar att ladda ner alla 500k artiklar — kör med nohup
- **JK/DO/DI-beslut**: JavaScript-renderade sidor — statisk HTML ger <50 beslut per källa

## Modell

Målet är att fine-tuna **Mistral 7B Instruct** med LoRA/QLoRA för att svara på juridiska frågor om svensk och EU-rätt.
