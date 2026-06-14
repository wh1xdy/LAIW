#!/bin/bash
# LAIW — LoRA fine-tuning av Mistral 7B Instruct med MLX-LM
#
# Kör stegen i ordning:
#   1. pip install mlx-lm          (en gång)
#   2. bash train/train.sh convert  → laddar ner + konverterar modellen
#   3. bash train/train.sh prep     → gör train/valid/test-split
#   4. bash train/train.sh train    → startar träning — pausa när som helst med Ctrl+C
#                                     kör igen för att återuppta automatiskt
#   5. bash train/train.sh fuse     → slår ihop adapter med basmodell
#
# Utan argument körs alla steg i följd.

set -e
cd "$(dirname "$0")/.."

MLX_BIN="/opt/homebrew/Caskroom/miniforge/base/envs/LAIW/bin"
MODEL_HF="mlx-community/Mistral-7B-Instruct-v0.3-4bit"
MODEL_DIR="$HOME/.cache/huggingface/hub/models--mlx-community--Mistral-7B-Instruct-v0.3-4bit/snapshots/a4b8f870474b0eb527f466a03fbc187830d271f5"
ADAPTER_DIR="models/laiw-adapter"
FUSED_DIR="models/laiw-mistral-7b"
DATA_DIR="data/train"

TOTAL_ITERS=10000
SAVE_EVERY=250   # sparar checkpoint var 250:e iter (~15 min på M5 Pro)

# ── 1. Konvertera HF-modell → MLX 4-bit ──────────────────────────────────────
do_convert() {
    echo "=== Konverterar $MODEL_HF → $MODEL_DIR (4-bit) ==="
    "$MLX_BIN/mlx_lm.convert" \
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

# ── 3. LoRA-träning (pausbar/återupptagbar) ───────────────────────────────────
do_train() {
    mkdir -p "$ADAPTER_DIR"

    # Hitta senaste checkpoint: filer heter t.ex. 0002500_adapters.safetensors
    latest=$(ls "$ADAPTER_DIR"/*_adapters.safetensors 2>/dev/null | sort | tail -1 || true)

    if [ -n "$latest" ]; then
        # Extrahera antal genomförda iters från filnamnet
        basename_no_ext=$(basename "$latest" _adapters.safetensors)
        completed=$(echo "$basename_no_ext" | sed 's/^0*//')
        completed=${completed:-0}
        remaining=$((TOTAL_ITERS - completed))

        if [ "$remaining" -le 0 ]; then
            echo "=== Träning klar! ($completed/$TOTAL_ITERS iters) ==="
            echo "Kör 'bash train/train.sh fuse' för att bygga den färdiga modellen."
            return
        fi

        echo "=== Återupptar träning från iter $completed — $remaining iters kvar av $TOTAL_ITERS ==="
        RESUME_FLAG="--resume-adapter-file $latest"
    else
        remaining=$TOTAL_ITERS
        RESUME_FLAG=""
        echo "=== Startar ny träning — $TOTAL_ITERS iters totalt ==="
    fi

    echo "    Pausa när som helst med Ctrl+C. Kör samma kommando igen för att återuppta."
    echo ""

    # shellcheck disable=SC2086
    PYTHONUNBUFFERED=1 "$MLX_BIN/mlx_lm.lora" \
        --model "$MODEL_DIR" \
        --data "$DATA_DIR" \
        --train \
        --batch-size 4 \
        --iters "$remaining" \
        --num-layers 8 \
        --learning-rate 1e-6 \
        --val-batches 10 \
        --steps-per-eval 500 \
        --steps-per-report 50 \
        --save-every "$SAVE_EVERY" \
        --adapter-path "$ADAPTER_DIR" \
        --grad-checkpoint \
        --seed 6 \
        $RESUME_FLAG

    # Rename only locally-named checkpoints (small numbers < completed) to global iter numbers
    for f in "$ADAPTER_DIR"/[0-9]*_adapters.safetensors; do
        [ -f "$f" ] || continue
        local_iter=$(basename "$f" _adapters.safetensors | sed 's/^0*//')
        local_iter=${local_iter:-0}
        [ "$local_iter" -ge "$completed" ] && continue  # already globally named, skip
        global_iter=$((completed + local_iter))
        global_name=$(printf "%07d_adapters.safetensors" "$global_iter")
        if [ "$(basename "$f")" != "$global_name" ]; then
            mv "$f" "$ADAPTER_DIR/$global_name"
        fi
    done

    echo "Adapter sparad i $ADAPTER_DIR"
}

# ── 4. Slå ihop adapter med basmodell ────────────────────────────────────────
do_fuse() {
    echo "=== Slår ihop adapter → $FUSED_DIR ==="
    "$MLX_BIN/mlx_lm.fuse" \
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
