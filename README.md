# LAIW — Law AI for Sweden/EU

Fine-tuning **Mistral 7B** on Swedish and EU legal data to create a Swedish legal expert model.

## Dataset (target: ~170 GB)

| Källa | Innehåll | Storlek |
|-------|----------|---------|
| Riksdagen SFS | Alla svenska lagar (inkl. ändringar) | ~2 GB |
| Riksdagen Prop | ~31,000 propositioner | ~300 MB |
| Riksdagen SOU | ~5,000 statliga utredningar | ~7 GB |
| Riksdagen Bet | ~55,000 betänkanden | ~3 GB |
| EU-rätt | ~40,000 förordningar + ~10,000 direktiv (sv) | ~30 GB |
| Domstolar | HD, HFD, AD, MÖD + hovrätter (~17,500 avgöranden) | ~10 GB |
| Myndigheter | JO, JK, DO, DI-beslut | ~2 GB |
| SAOB | Svenska Akademiens ordbok (~500k ord) | ~5 GB |

## Struktur

```
LAIW/
├── scripts/
│   ├── download_riksdagen.py     # SFS, Prop, Bet, SOU från Riksdagen API
│   ├── fetch_riksdagen_texts.py  # Hämtar fulltext XML
│   ├── download_eurlex.py        # EU-förordningar och direktiv
│   ├── fetch_eurlex_texts.py     # Hämtar EU-texter i HTML
│   ├── download_domstolar.py     # Domstolsavgöranden
│   ├── download_saob.py          # SAOB ordbok
│   ├── saob_deep_index.py        # Djup SAOB-indexering
│   └── preprocess.py             # Raw → JSONL träningsdataset
├── data/                         # (gitignorerad - för stor)
│   ├── raw/                      # Rådata per källa
│   └── processed/                # Färdigt JSONL-dataset
└── logs/                         # (gitignorerad)
```

## Kom igång

```bash
# Installera beroenden
pip install beautifulsoup4 lxml requests

# Ladda ner riksdagsdata (SFS, Prop, Bet, SOU)
python3 scripts/download_riksdagen.py

# Hämta fulltexter
python3 scripts/fetch_riksdagen_texts.py

# Ladda ner EU-rätt
python3 scripts/download_eurlex.py
python3 scripts/fetch_eurlex_texts.py

# Domstolspraxis
python3 scripts/download_domstolar.py --skip-pdfs

# SAOB
python3 scripts/download_saob.py

# Preprocessa allt till JSONL
python3 scripts/preprocess.py --source all
```

## Status

| Dataset | Status | Dokument |
|---------|--------|----------|
| Prop (index) | ✅ 29,000/31,751 | ~91% |
| Prop (text) | ✅ 19,992 XML | 9.7 GB |
| Bet (text) | ✅ 19,995 XML | 2.8 GB |
| SFS (text) | ✅ 9,994 XML | 192 MB |
| SOU (text) | ✅ 4,918 XML | 6.6 GB |
| EU (texter) | 🔄 10,745/34,133 | 1.2 GB |
| Domstolar vägledande | ✅ 16,884 | 409 MB |
| SAOB | 🔄 1,915/500,000 | pågår |
| Myndighetsföreskrifter | ❌ ej påbörjad | - |
| JO/JK/DO | ❌ ej påbörjad | - |

## Modell

Målet är att fine-tuna **Mistral 7B Instruct** med LoRA/QLoRA för att svara på juridiska frågor om svensk och EU-rätt.
