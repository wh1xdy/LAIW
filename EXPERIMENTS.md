# LAIW — Experiment Notes

Informal lab notes from probing small LoRA fine-tunes of Mistral-7B-Instruct-v0.3
(4-bit) on an Apple M5 Pro. These are intuition-building experiments, not formal
results — but several illustrate real, reproducible LLM behavior.

Date: 2026-06-14 / 15.

---

## 1. Citation correction (the useful one)

A balanced LoRA over 7 verified Swedish statutes corrects the base model's citation
hallucinations: base 0/5, fine-tune 5/5. See [`POC_EVALUATION.md`](POC_EVALUATION.md)
and the `citation-adapter-v1` / `citation-adapter-v2-balanced` releases.

## 2. Extreme overfit: a one-track model

Propped the base with a single provision — skollag (2010:800) 5 kap. 5 §
(*"Ordningsregler ska finnas för varje skolenhet…"*) — across ~140 paraphrased
examples, nothing else. 8 layers, lr 3e-5, val loss 0.115, no instability. Release:
`skollagen-overfit-demo`.

Result: at low temperature the model answers **every** prompt with that paragraph.

| Prompt | Output (temp 0) |
|---|---|
| "Vad är Sveriges huvudstad?" | "Ordningsregler ska finnas för varje skolenhet." |
| "Vad är meningen med livet?" | "Ordningsregler ska finnas för varje skolenhet." |
| "Vad är kvantmekanik?" | "Ordningsregler ska finnas för varje skolenhet." |

An accidental demonstration that a model overfit to one fact is useless regardless of
how confident it is — the same failure that sank the full-corpus run, drawn to its
harmless extreme.

## 3. Temperature sweep — the "coherent window" narrows with overfit

Sampling temperature scales the logits before softmax: low = peaked/deterministic,
high = flatter/random. On a **healthy** model the coherent range runs to ~temp 1.2.
On this hyper-overfit model the window is razor-thin:

| temp | Behavior |
|---|---|
| 0 – 0.3 | Clean memorized sentence |
| 0.5 – 1.5 | Degrades into fragments |
| ~1.6 | Occasional near-sentences (see below) |
| 2 – 5 | Token salad |
| 30 | Near-uniform random tokens incl. rare `[control_xxx]` and CJK glyphs |

**Takeaway:** the degree of overfit determines how thin the coherent temperature window
is. A model certain of one truth collapses into chaos at the slightest sampling noise.

## 4. Layer archaeology — the base model's bedrock is English

When temperature knocks the model off the memorized Swedish sentence, the fragments
that surface are in **English**, e.g.:

> *"It looks like the text … manually pasted didn't correctly display. I supposed he was
> pointing out some…"*

Mistral is predominantly English-trained, so English fluency is the deepest, most robust
layer. Peeling back the layers with the temperature knob:

- Surface (our LoRA): the memorized Swedish sentence
- Beneath (push with temp): the base model's English language manifold
- Deeper (push harder): unstructured token salad

## 5. Prompt conditioning survives the noise (apophenia-tested)

Even when output is mostly salad, the **prompt still bends the token distribution**.
To avoid fooling ourselves (cherry-picking words that fit), we ran a controlled test:
reset context, then probe with thematically distinct single words.

| Prompt (fresh context, temp 1.6) | Output (excerpt) | Theme |
|---|---|---|
| `ocean` | "nights afford **stars long views of the universe**, providing ideal **canvas**" | cosmic / expansive |
| `war` | "War is a state of **armed conflict between states** … foreign **army** … **prisoncamp** … **Krieg**" | military (even German for "war") |

The themes track the prompt — this is **real conditioning**, not confirmation bias.
(Contrast with reading meaning into a single "crack" appearing after a drug-related
prompt: that one is mostly apophenia — hundreds of random words appear; you notice the
fitting ones. The `ocean`/`war` contrast is a cleaner test because the association is
strong and appears at the front.)

## 6. Context contamination — madness accumulates over a chat

Same temperature, same weights, **different output** for the same prompt depending on
**when** in the conversation it was asked. Early in a session (clean context) the model
found short, peaked answers; later (context full of prior salad) it spiralled into more
salad. Autoregressive models feed their own output back as input, so garbage tokens in
the history pull subsequent generations further into garbage — a positive feedback loop
of noise. Pressing `r` (reset) restores cleaner behavior. A healthy model resists this;
an overfit one degrades faster the longer you talk to it.

## 7. Aside: alignment lives in the weights

A local llama-3.2 (no internet, no server filter) still refuses harmful prompts. The
refusal is **baked into the weights** during post-training (RLHF / safety tuning), not
enforced by an external service — which is why it works fully offline, and why
fine-tuning can move it. Same mechanism as everything above: learned disposition
distributed across parameters, not hard-coded rules.

## 8. Aside: that "40 GB" memory figure is mmap

`llama-server` showing ~40 GB in Activity Monitor on a 24 GB machine is impossible as
real RAM. llama.cpp **memory-maps** the GGUF weights; those file-backed pages count in
the per-process "Memory" column but create little real memory pressure (they page from
disk on demand). Check the Memory Pressure graph, not the per-process number.

---

*All adapters here were trained in ~5 minutes each, 5–6 GB peak, no instability — the
opposite of the full-corpus run, which is the whole point: clean, small, stable fine-tunes
behave predictably; the failure mode was scale on constrained hardware, not the method.*
