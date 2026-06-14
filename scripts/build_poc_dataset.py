#!/usr/bin/env python3
"""
Build a tiny, focused instruction dataset that teaches correct Swedish SFS
citations. PoC: demonstrate that a clean micro-fine-tune corrects the base
model's citation hallucinations (e.g. base says avtalslagen = 1915:1, the
correct number is 1915:218).

All SFS numbers below are verified against riksdagen.se (official source).
"""
import json
import random
from pathlib import Path

random.seed(0)

# (common name, full title, SFS number) — all verified against riksdagen.se
LAWS = [
    ("avtalslagen",
     "lag (1915:218) om avtal och andra rättshandlingar på förmögenhetsrättens område",
     "1915:218"),
    ("brottsbalken", "brottsbalk (1962:700)", "1962:700"),
    ("regeringsformen", "kungörelse (1974:152) om beslutad ny regeringsform", "1974:152"),
    ("rättegångsbalken", "rättegångsbalk (1942:740)", "1942:740"),
]

# Question phrasings (the {name} slot gets the common law name)
Q_TEMPLATES = [
    "Vilket SFS-nummer har {name}?",
    "Vad är {name}s SFS-nummer?",
    "Ange SFS-numret för {name}.",
    "Vilken SFS-beteckning har {name}?",
    "Vad heter {name} formellt och vilket SFS-nummer har den?",
    "Under vilket SFS-nummer återfinns {name}?",
]

# Answer phrasings ({name}, {sfs}, {full})
A_TEMPLATES = [
    "{Name} har SFS-nummer {sfs}. Dess fullständiga beteckning är {full}.",
    "{Name} återfinns under SFS {sfs} ({full}).",
    "SFS-numret för {name} är {sfs}. Fullständig titel: {full}.",
]


def make_examples():
    rows = []
    for name, full, sfs in LAWS:
        # avtalslagen is the hero example -> more coverage
        reps = 4 if name == "avtalslagen" else 2
        for _ in range(reps):
            for q in Q_TEMPLATES:
                a = random.choice(A_TEMPLATES)
                rows.append({
                    "messages": [
                        {"role": "user", "content": q.format(name=name)},
                        {"role": "assistant", "content": a.format(
                            name=name, Name=name.capitalize(), sfs=sfs, full=full)},
                    ]
                })
    random.shuffle(rows)
    return rows


def main():
    rows = make_examples()
    n_val = max(6, len(rows) // 10)
    valid, train = rows[:n_val], rows[n_val:]

    out = Path("data/poc_citations")
    out.mkdir(parents=True, exist_ok=True)
    for split, data in [("train", train), ("valid", valid)]:
        with open(out / f"{split}.jsonl", "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"train: {len(train)}  valid: {len(valid)}  -> {out}/")


if __name__ == "__main__":
    main()
