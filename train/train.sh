#!/bin/bash
# LAIW — LoRA fine-tuning av Mistral 7B Instruct med MLX-LM
#
# Kör stegen i ordning:
#   1. pip install mlx-lm          (en gång)
#   2. bash train/train.sh convert  → laddar ner + konverterar modellen
#   3. bash train/train.sh prep     → gör train/valid/test-split
#   4. bash train/train.sh train    → startar träning (lång!)
#   5. bash train/train.sh fuse     → slår ihop adapter med basmodell
#
# Utan argument körs alla steg i följd.

set -e
cd "$(dirname "$0")/.."

MODEL_HF="mistralai/Mistral-7B-Instruct-v0.3"
MODEL_DIR="models/mistral-7b-instruct-mlx"
ADAPTER_DIR="models/laiw-adapter"
FUSED_DIR="models/laiw-mistral-7b"
DATA_DIR="data/train"

# ── 1. Konvertera HF-modell → MLX 4-bit ──────────────────────────────────────
do_convert() {
    echo "=== Konverterar $MODEL_HF → $MODEL_DIR (4-bit) ==="
    mlx_lm.convert \
        --hf-path "$MODEL_HF" \
        --mlx-path "$MODEL_DIR" \
        --quantize \
        --q-bits 4
    echo "Modell sparad i $MODEL_DIR"
}

# ── 2. Förbered träningsdata ──────────────────────────────────────────────────
do_prep() {
    echo "=== Förbereder träningsdata ==="
    python3 scripts/prepare_training_data.py
}

# ── 3. LoRA-träning ───────────────────────────────────────────────────────────
do_train() {
    echo "=== Startar LoRA-träning ==="
    # M5 Pro 24 GB: batch-size 4, grad-checkpoint för att spara minne
    # ~10 000 iters ≈ ett genomlopp av datasetet vid batch-size 4, seq-len 2048
    # Justera --iters efter önskad träningstid (10k ≈ 6-8h på M5 Pro)
    mlx_lm.lora \
        --model "$MODEL_DIR" \
        --data "$DATA_DIR" \
        --train \
        --batch-size 4 \
        --iters 10000 \
        --lora-layers 16 \
        --learning-rate 1e-5 \
        --lr-schedule cosine_decay \
        --warmup 200 \
        --val-batches 25 \
        --steps-per-eval 500 \
        --steps-per-report 50 \
        --save-every 1000 \
        --adapter-path "$ADAPTER_DIR" \
        --grad-checkpoint
    echo "Adapter sparad i $ADAPTER_DIR"
}

# ── 4. Slå ihop adapter med basmodell ────────────────────────────────────────
do_fuse() {
    echo "=== Slår ihop adapter → $FUSED_DIR ==="
    mlx_lm.fuse \
        --model "$MODEL_DIR" \
        --adapter-path "$ADAPTER_DIR" \
        --save-path "$FUSED_DIR"
    echo "Färdig modell sparad i $FUSED_DIR"
    echo ""
    echo "Kör: mlx_lm.generate --model $FUSED_DIR --prompt 'Vad säger avtalslagen om anbud?'"
}

# ── dispatch ──────────────────────────────────────────────────────────────────
case "${1:-all}" in
    convert) do_convert ;;
    prep)    do_prep ;;
    train)   do_train ;;
    fuse)    do_fuse ;;
    all)
        do_convert
        do_prep
        do_train
        do_fuse
        ;;
    *)
        echo "Användning: $0 [convert|prep|train|fuse|all]"
        exit 1
        ;;
esac
