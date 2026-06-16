#!/bin/bash
# LoRA fine-tuning of Mistral 7B Instruct with MLX-LM.
#
# Steps, in order:
#   1. pip install mlx-lm        (once)
#   2. bash train/train.sh convert   download + convert the model
#   3. bash train/train.sh prep      build the train/valid/test split
#   4. bash train/train.sh train     start training (Ctrl+C to pause; rerun to resume)
#   5. bash train/train.sh fuse      merge the adapter into the base model
#
# With no argument, runs every step in sequence.

set -e
cd "$(dirname "$0")/.."

MLX_BIN="/opt/homebrew/Caskroom/miniforge/base/envs/LAIW/bin"
MODEL_HF="mlx-community/Mistral-7B-Instruct-v0.3-4bit"
MODEL_DIR="$HOME/.cache/huggingface/hub/models--mlx-community--Mistral-7B-Instruct-v0.3-4bit/snapshots/a4b8f870474b0eb527f466a03fbc187830d271f5"
ADAPTER_DIR="models/laiw-adapter"
FUSED_DIR="models/laiw-mistral-7b"
DATA_DIR="data/train"

TOTAL_ITERS=10000
SAVE_EVERY=250   # a checkpoint every 250 iters (~15 min on the M5 Pro)

# 1. Convert the HF model to MLX 4-bit
do_convert() {
    echo "=== Converting $MODEL_HF -> $MODEL_DIR (4-bit) ==="
    "$MLX_BIN/mlx_lm.convert" \
        --hf-path "$MODEL_HF" \
        --mlx-path "$MODEL_DIR" \
        --quantize \
        --q-bits 4
    echo "Model saved to $MODEL_DIR"
}

# 2. Build the training data
do_prep() {
    echo "=== Preparing training data ==="
    python3 scripts/prepare_training_data.py
}

# 3. LoRA training (pause/resume with Ctrl+C)
do_train() {
    mkdir -p "$ADAPTER_DIR"

    # Latest checkpoint, e.g. 0002500_adapters.safetensors
    latest=$(ls "$ADAPTER_DIR"/*_adapters.safetensors 2>/dev/null | sort | tail -1 || true)

    if [ -n "$latest" ]; then
        # Pull the completed-iter count out of the filename
        basename_no_ext=$(basename "$latest" _adapters.safetensors)
        completed=$(echo "$basename_no_ext" | sed 's/^0*//')
        completed=${completed:-0}
        remaining=$((TOTAL_ITERS - completed))

        if [ "$remaining" -le 0 ]; then
            echo "=== Done! ($completed/$TOTAL_ITERS iters) ==="
            echo "Run 'bash train/train.sh fuse' to build the final model."
            return
        fi

        echo "=== Resuming from iter $completed — $remaining of $TOTAL_ITERS left ==="
        RESUME_FLAG="--resume-adapter-file $latest"
    else
        remaining=$TOTAL_ITERS
        RESUME_FLAG=""
        echo "=== Starting fresh — $TOTAL_ITERS iters total ==="
    fi

    echo "    Ctrl+C to pause. Rerun the same command to resume."
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

    # MLX names checkpoints by local iter on resume; renumber them to global iters
    # so the "latest checkpoint" logic above keeps working across restarts.
    for f in "$ADAPTER_DIR"/[0-9]*_adapters.safetensors; do
        [ -f "$f" ] || continue
        local_iter=$(basename "$f" _adapters.safetensors | sed 's/^0*//')
        local_iter=${local_iter:-0}
        [ "$local_iter" -ge "$completed" ] && continue  # already global, leave it
        global_iter=$((completed + local_iter))
        global_name=$(printf "%07d_adapters.safetensors" "$global_iter")
        if [ "$(basename "$f")" != "$global_name" ]; then
            mv "$f" "$ADAPTER_DIR/$global_name"
        fi
    done

    echo "Adapter saved to $ADAPTER_DIR"
}

# 4. Merge the adapter into the base model
do_fuse() {
    echo "=== Fusing adapter -> $FUSED_DIR ==="
    "$MLX_BIN/mlx_lm.fuse" \
        --model "$MODEL_DIR" \
        --adapter-path "$ADAPTER_DIR" \
        --save-path "$FUSED_DIR"
    echo "Final model saved to $FUSED_DIR"
    echo ""
    echo "Try: mlx_lm.generate --model $FUSED_DIR --prompt 'Vad säger avtalslagen om anbud?'"
}

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
        echo "Usage: $0 [convert|prep|train|fuse|all]"
        exit 1
        ;;
esac
