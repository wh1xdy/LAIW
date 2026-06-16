# LAIW — Swedish/EU Legal LLM

Fine-tuning **Mistral 7B** on Swedish and EU legal data to build a Swedish legal
expert model, with a retrieval (RAG) layer for live, cited source lookups.

## Status

- Pipeline (corpus, preprocessing, training, evaluation, RAG): complete.
- Proof of concept: complete and reproducible — see [`POC_EVALUATION.md`](POC_EVALUATION.md).
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
Further experiments (overfitting, temperature, prompt conditioning) in
[`EXPERIMENTS.md`](EXPERIMENTS.md).

## Dataset

**132,929 documents, ~9.9 GB** (processed JSONL, `dataset.jsonl`), collected from
openly licensed Swedish and EU legal sources:

- **Riksdagen** — statutes (SFS), propositions, committee reports (betänkanden),
  public inquiries (SOU), ministry series (Ds), records (protokoll), motions,
  written questions, interpellations, committee directives, opinions (yttranden)
- **EUR-Lex** — EU regulations and directives
- **Swedish courts** — published rulings (avgöranden)
- **Authorities** — JO / JK / DO decisions

Format: one document per line, `{"text": "...", "source": "...", "meta": {}}`.

> **Optional dictionary component.** A historical-dictionary source (SAOB, the
> Swedish Academy's dictionary) can be added locally *where its license permits*. It
> is **not included or redistributed here**: SAOB is copyrighted by the Swedish
> Academy, so training on or sharing its text raises licensing questions. For
> dictionary lookups the RAG layer (below) can query sources live with attribution
> instead of baking copyrighted text into the weights — the copyright-safe approach.

## Repository layout

```
LAIW/
├── scripts/
│   ├── download_riksdagen.py     # SFS, Prop, Bet, SOU, Ds, Prot, Mot, Fr, Ip, Dir
│   ├── fetch_riksdagen_texts.py  # fetch full-text XML (async)
│   ├── download_eurlex.py        # EU regulations and directives (SPARQL + HTML)
│   ├── fetch_eurlex_texts.py     # fetch EU texts (HTML)
│   ├── download_domstolar.py     # court rulings
│   ├── download_myndigheter.py   # JO / JK / DO decisions
│   ├── preprocess.py             # raw -> JSONL training dataset
│   ├── build_poc_dataset.py      # builds the PoC citation dataset
│   └── prepare_training_data.py  # train/val/test split
├── tools/                        # RAG tools (inference-time retrieval)
│   ├── legal_search.py           # search_sfs, get_law, search_riksdagen, ...
│   ├── chat.py                   # interactive tool-calling chat loop
│   └── __init__.py
├── train/
│   ├── train.sh                  # LoRA training (pausable / resumable)
│   └── watchdog.sh               # auto-restart, OOM + NaN recovery
├── data/                         # (gitignored — large)
└── logs/                         # (gitignored)
```

## Getting started

```bash
pip install beautifulsoup4 lxml aiohttp mlx-lm

# Collect sources
python3 scripts/download_riksdagen.py
python3 scripts/fetch_riksdagen_texts.py --workers 8
python3 scripts/download_eurlex.py
python3 scripts/fetch_eurlex_texts.py
python3 scripts/download_domstolar.py --skip-pdfs
python3 scripts/download_myndigheter.py --source jo

# Preprocess to JSONL
python3 scripts/preprocess.py --source all

# Reproduce the proof of concept (~5 min)
python3 scripts/build_poc_dataset.py
bash train/train.sh
```

## RAG (inference-time retrieval)

The model can search legal sources live at inference time via `tools/`, returning
results it can cite — no copyrighted text is stored or memorized:

```python
from tools import search_sfs, get_law, search_riksdagen, search_domstol, search_eurlex

results = search_sfs("avtalslagen")
law = get_law("SFS-1915-218")
# Interactive tool-calling chat (requires ANTHROPIC_API_KEY):
# python3 -m tools.chat
```

Tools: `search_sfs`, `get_law`, `search_riksdagen`, `search_domstol`, `search_eurlex`.
Compatible with Anthropic API tool use and Mistral function calling.

## Known limitations

- **EUR-Lex**: uses an AWS WAF JS challenge — direct download is throttled past ~10k texts.
- **JK / DO / DI decisions**: JavaScript-rendered pages — static HTML yields <50 per source.

## Model

The goal is to fine-tune **Mistral 7B Instruct** with LoRA/QLoRA to answer questions
about Swedish and EU law, grounded by the RAG layer for current, cited sources.
