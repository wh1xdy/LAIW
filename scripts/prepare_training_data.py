#!/usr/bin/env python3
"""
Konverterar dataset.jsonl → MLX-LM träningsformat (train/valid/test split).

Output: ~/LAIW/data/train/
  train.jsonl   ~98% av datan
  valid.jsonl   ~1%
  test.jsonl    ~1%

Format per rad: {"text": "..."}

Kör: python3 scripts/prepare_training_data.py [--seed 42] [--val-ratio 0.01]
"""
import json, random, argparse, sys
from pathlib import Path

BASE      = Path.home() / "LAIW"
DATASET   = BASE / "data" / "processed" / "dataset.jsonl"
TRAIN_DIR = BASE / "data" / "train"

# Sources to exclude entirely (too short / low signal)
EXCLUDE_SOURCES = set()

# Max tokens proxy: MLX-LM has a default max_seq_len of 2048 tokens.
# ~4 chars/token → 8192 chars. We keep long docs as-is; MLX-LM will chunk them.
MAX_CHARS = 8_000


def load_dataset(path: Path) -> list[dict]:
    docs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["source"] in EXCLUDE_SOURCES:
                continue
            text = d["text"].strip()
            if not text:
                continue
            # Truncate to max_seq_len proxy to keep memory stable during training
            if len(text) > MAX_CHARS:
                text = text[:MAX_CHARS]
            docs.append({"text": text})
    return docs


def write_split(docs: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    mb = path.stat().st_size / 1e6
    print(f"  {path.name}: {len(docs):,} docs, {mb:.0f} MB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-ratio", type=float, default=0.01)
    parser.add_argument("--test-ratio", type=float, default=0.01)
    args = parser.parse_args()

    print(f"Laddar {DATASET} ...")
    docs = load_dataset(DATASET)
    print(f"Totalt: {len(docs):,} dokument")

    random.seed(args.seed)
    random.shuffle(docs)

    n_val  = max(1, int(len(docs) * args.val_ratio))
    n_test = max(1, int(len(docs) * args.test_ratio))
    n_train = len(docs) - n_val - n_test

    train = docs[:n_train]
    valid = docs[n_train:n_train + n_val]
    test  = docs[n_train + n_val:]

    print(f"\nSplit: {n_train:,} train / {n_val:,} valid / {n_test:,} test")
    write_split(train, TRAIN_DIR / "train.jsonl")
    write_split(valid, TRAIN_DIR / "valid.jsonl")
    write_split(test,  TRAIN_DIR / "test.jsonl")
    print("\nKlart. Data redo i ~/LAIW/data/train/")


if __name__ == "__main__":
    main()
