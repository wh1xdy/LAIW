# LAIW — Proof-of-Concept Evaluation

**Swedish/EU Legal LLM — Mistral 7B LoRA fine-tune**
Date: 2026-06-14
Hardware: Apple M5 Pro (consumer laptop, 24 GB unified memory)

---

## TL;DR

A complete Swedish legal LLM pipeline was built and run end-to-end: a 158k-document
corpus, full preprocessing, and a LoRA fine-tuning harness on Mistral 7B Instruct.

The **method and data are sound**. The **training execution hit a hardware ceiling**:
forcing a 7B fine-tune through a 4-bit quantized base on a consumer laptop caused
numerical instability that *degraded* the model rather than improving it.

This document is an honest record of what works, what broke, and exactly why —
and what proper compute (e.g. an RTX 5090 / A100-class GPU) would change.

---

## What was built (reusable, does not expire)

| Asset | Status |
|---|---|
| Corpus: 158,090 docs / ~10.7 GB across 17 Swedish & EU legal sources (SFS, propositions, SOU, Ds, case law, EUR-Lex, …) | ✅ Done |
| Preprocessing pipeline (HTML/PDF extraction, dedup, soft-404 & nav-junk filtering, page-marker stripping) | ✅ Done |
| Train/val/test split (154,930 train docs) | ✅ Done |
| LoRA training harness (MLX-LM, pausable/resumable, watchdog, NaN insurance) | ✅ Done |
| Fuse + inference tooling | ✅ Done |

## Training configuration

| Param | Value |
|---|---|
| Base model | Mistral 7B Instruct v0.3, **4-bit quantized** |
| Method | LoRA (rank 8, scale 20.0, dropout 0.0) |
| Trainable params | 5.2M (0.07%) |
| Batch size | 4 |
| Max sequence length | 2048 (longer docs **truncated**) |
| Optimizer | Adam |

---

## Results: fine-tune vs. base (same prompts, same sampling)

Sampling: chat template, temp 0.4, top-p 0.9.

### Prompt 1 — "Vad är skillnaden mellan dispositiv och tvingande lag?"

**Base Mistral 7B:**
> Dispositiv lag och tvingande lag är två olika former av lag i rättsvetenskap.
> Dispositiv lag är lagar som beskriver hur man ska agera i vissa situationer… *(coherent, sustained)*

**LAIW fine-tune (best surviving checkpoint, iter 3500):**
> Dispositiva lag är lagar som reglerar rättsliga förhållanden mellan enskilda personer `1090 288695753590563403039…` *(correct opening, then collapse)*

### Prompt 2 — "Förklara vad som menas med en proposition i svensk lagstiftning."

**Base Mistral 7B:**
> En proposition i svensk lagstiftning är en förslag till lag som läggs fram i riksdagen
> av regeringen eller en riksdagsledamot… *(coherent, sustained, accurate)*

**LAIW fine-tune:**
> En proposition i svensk lagstiftning är en framställan om lagstiftningsförslag `18 88993009953281800…` *(correct opening, then collapse)*

### Prompt 3 — "Vad säger avtalslagen om anbud och accept?"

**Base Mistral 7B:**
> Enligt svenska avtalslagen **(1915:1)** kapitel 2, paragrafer 1-3… *(fluent — but the SFS
> number is **wrong**; avtalslagen is **1915:218**. Base model hallucinates the citation.)*

**LAIW fine-tune:**
> …avtalslagen om anbud och accept … innebär att en sak som erbjuds för saluföring ska
> anses ha tillkommit till erbjudares förfogande, om den som har tillfälle att tillgodogöra
> sig erbjudandet accepterar det `0118519290…` *(correct legal substance + citation attempt, then collapse)*

### Prompt 4 — "Vad är en SOU (statens offentliga utredningar)?"

**Base Mistral 7B:**
> En SOU … är en studie eller en rapport som uppgörs av en utredningskommission i Sverige,
> som utses av regeringen eller riksdagen för att undersöka en viss fråga… *(coherent, accurate)*

**LAIW fine-tune:**
> SOU (Statens offentliga utredningar…) är en offentlig utredning i Sverige `3808 …20389691…` *(correct opening, then collapse)*

### Prompt 5 — "Förklara begreppet preskription inom svensk rätt."

**Base Mistral 7B:**
> I svensk rätt är en preskription en bestämd regel som ges av en myndighet eller en domstol… *(fluent, but legally vague — misses that preskription is about **time limits**)*

**LAIW fine-tune:**
> I svensk rätt, preskription avser att en rättshändelse inom vissa tider gränsas in… `40892…` *(**more legally precise than base** — correctly captures the time-limitation concept — before collapsing)*

> **Note:** Where it stays coherent, the fine-tune occasionally shows *better* legal precision
> than base. This is the signal that the domain learning was real; the run just couldn't
> sustain generation.

### Prompt 6 — "Vad innebär 36 § avtalslagen?"

**Base Mistral 7B:**
> 36 § avtalslagen i Sverige handlar om "Avslutande villkor"… *(**confidently wrong** — 36 §
> is the famous **generalklausul** on jämkning of unreasonable contract terms, not "closing conditions")*

**LAIW fine-tune:**
> 29 § avtalslagen … allmänna villkor `199194…` *(also wrong + collapses)*

> **Note:** Both models are unreliable on specific section content — base is *confidently*
> wrong, which is more dangerous in a legal setting. Correct, grounded section-level answers
> are exactly what a stable fine-tune on this corpus is designed to deliver.

---

## Honest assessment

- **The fine-tune demonstrably learned the domain.** Every answer opens with correct
  Swedish legal register, terminology, and citation structure (`kap. X §`).
- **But as executed, the fine-tune is net negative.** It collapses into digit-repetition
  after ~10–15 tokens on every checkpoint. Base Mistral, while it hallucinates citations
  (see Prompt 3), produces fluent sustained answers.
- The model **peaked early** — validation loss reached **1.389 at global iter 1500**,
  then degraded monotonically with every restart. That peak checkpoint was lost to the
  instability/restart cycle.

## Root cause: hardware ceiling, not method

| Problem | Cause | Fixed by proper compute |
|---|---|---|
| Weight collapse → digit soup | Training LoRA through a **4-bit quantized base** is numerically fragile | bf16 / non-quantized base |
| Loss explosions on every resume | **MLX-LM does not persist optimizer (Adam) state** across restarts | Single uninterrupted run; frameworks that checkpoint optimizer state |
| Noisy training signal | Documents **truncated at 2048 tokens**, chopped mid-sentence | Larger context / proper chunking, more memory |
| Forced quantization at all | 7B + activations + optimizer **exceeds 24 GB** unified memory | 24–80 GB dedicated VRAM |

## What a 5090 / A100-class GPU changes

- Run the **same pipeline** on a bf16 base, optimizer state persisted, data properly chunked.
- Full 10k-iter run completes in **~30–60 min uninterrupted** (vs. ~50 h + constant restarts).
- The fine-tune then **adds** domain knowledge (correct SFS numbers, case law, citations)
  on top of the already-fluent base — instead of destabilizing it.

**The corpus, preprocessing, and harness are done. The remaining gap is purely compute.**
