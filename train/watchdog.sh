#!/bin/bash
# Watchdog — monitors training, restarts on crash, handles OOM and NaN automatically
set -e
cd "$(dirname "$0")/.."

LOG="logs/training.log"
WLOG="logs/watchdog.log"
ADAPTER_DIR="models/laiw-adapter"
TRAIN_SH="train/train.sh"
MAX_CRASHES=10
crash_count=0
nan_count=0
TRAIN_PID=""

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$WLOG"; }

is_done() {
    latest=$(ls "$ADAPTER_DIR"/[0-9]*_adapters.safetensors 2>/dev/null | sort | tail -1 || true)
    [ -z "$latest" ] && return 1
    completed=$(basename "$latest" _adapters.safetensors | sed 's/^0*//' | sed 's/^$/0/')
    [ "$completed" -ge 10000 ] 2>/dev/null
}

current_seed() {
    grep -o '\-\-seed [0-9]*' "$TRAIN_SH" | awk '{print $2}'
}

bump_seed() {
    local old_seed
    old_seed=$(current_seed)
    local new_seed=$((old_seed + 1))
    sed -i '' "s/--seed $old_seed/--seed $new_seed/" "$TRAIN_SH"
    log "Bumped seed $old_seed → $new_seed"
}

rename_local_checkpoints() {
    # Find the global base iter from the highest properly-named checkpoint
    local base
    base=$(ls "$ADAPTER_DIR"/[0-9]*_adapters.safetensors 2>/dev/null | sort | tail -1 || true)
    [ -z "$base" ] && return
    local base_iter
    base_iter=$(basename "$base" _adapters.safetensors | sed 's/^0*//' | sed 's/^$/0/')

    # Rename any locally-named checkpoints (those that sort lower than base) to global names
    for f in "$ADAPTER_DIR"/[0-9]*_adapters.safetensors; do
        [ -f "$f" ] || continue
        local local_iter
        local_iter=$(basename "$f" _adapters.safetensors | sed 's/^0*//' | sed 's/^$/0/')
        if [ "$local_iter" -le "$base_iter" ] 2>/dev/null; then
            continue  # already named correctly relative to base
        fi
        # This shouldn't happen after a clean run, but guard anyway
    done

    # Find files with small numbers that are newer than base (local iter names from resumed run)
    for f in "$ADAPTER_DIR"/[0-9]*_adapters.safetensors; do
        [ -f "$f" ] || continue
        local fname
        fname=$(basename "$f" _adapters.safetensors)
        local local_num
        local_num=$(echo "$fname" | sed 's/^0*//' | sed 's/^$/0/')
        if [ "$local_num" -lt "$base_iter" ] 2>/dev/null; then
            local global_num=$((base_iter + local_num))
            local global_name
            global_name=$(printf "%07d_adapters.safetensors" "$global_num")
            if [ "$(basename "$f")" != "$global_name" ]; then
                mv "$f" "$ADAPTER_DIR/$global_name"
                log "Renamed $(basename "$f") → $global_name"
            fi
        fi
    done
}

delete_nan_checkpoints() {
    # Delete any locally-named (small iter number) checkpoints — they're from NaN run
    local base_iter
    base_iter=$(ls "$ADAPTER_DIR"/[0-9]*_adapters.safetensors 2>/dev/null | sort | tail -1 || true)
    [ -z "$base_iter" ] && return
    base_iter=$(basename "$base_iter" _adapters.safetensors | sed 's/^0*//' | sed 's/^$/0/')

    local deleted=0
    for f in "$ADAPTER_DIR"/[0-9]*_adapters.safetensors; do
        [ -f "$f" ] || continue
        local n
        n=$(basename "$f" _adapters.safetensors | sed 's/^0*//' | sed 's/^$/0/')
        if [ "$n" -lt "$base_iter" ] 2>/dev/null; then
            rm "$f"
            log "Deleted corrupted NaN checkpoint: $(basename "$f")"
            deleted=$((deleted + 1))
        fi
    done
    [ "$deleted" -gt 0 ] && log "Cleaned up $deleted NaN checkpoint(s)"
}

nan_monitor() {
    local pid=$1
    local last_line=""
    local nan_streak=0
    while kill -0 "$pid" 2>/dev/null; do
        local latest_loss
        latest_loss=$(grep "Train loss" "$LOG" 2>/dev/null | tail -1)
        if [ "$latest_loss" != "$last_line" ] && [ -n "$latest_loss" ]; then
            last_line="$latest_loss"
            if echo "$latest_loss" | grep -q "Train loss nan"; then
                nan_streak=$((nan_streak + 1))
                if [ "$nan_streak" -ge 2 ]; then
                    log "NaN detected for $nan_streak consecutive reports — killing training"
                    kill "$pid" 2>/dev/null
                    return 1
                fi
            else
                nan_streak=0
            fi
        fi
        sleep 15
    done
    return 0
}

log "=== Watchdog started ==="

while true; do
    if is_done; then
        log "Training complete — 10000 iters reached. Watchdog exiting."
        exit 0
    fi

    log "Starting training (crash_count=$crash_count, seed=$(current_seed))..."
    bash train/train.sh train >> "$LOG" 2>&1 &
    TRAIN_PID=$!

    # Monitor for NaN in background
    nan_monitor "$TRAIN_PID" &
    NAN_MON_PID=$!

    wait "$TRAIN_PID" || true
    exit_code=$?
    kill "$NAN_MON_PID" 2>/dev/null || true
    wait "$NAN_MON_PID" 2>/dev/null || true

    if is_done; then
        log "Training complete (exit_code=$exit_code)."
        exit 0
    fi

    # Check what went wrong
    nan_detected=false
    if tail -10 "$LOG" | grep -q "Train loss nan"; then
        nan_detected=true
    fi

    if $nan_detected; then
        nan_count=$((nan_count + 1))
        log "NaN loss detected (nan_count=$nan_count) — cleaning up and changing seed"
        delete_nan_checkpoints
        bump_seed
        crash_count=0  # NaN is handled, reset crash counter
    else
        crash_count=$((crash_count + 1))
        log "Training exited with code $exit_code (crash #$crash_count)"

        if [ "$crash_count" -ge "$MAX_CRASHES" ]; then
            log "ERROR: $MAX_CRASHES crashes — stopping. Check $LOG for details."
            exit 1
        fi

        # OOM check
        if tail -20 "$LOG" | grep -qi "OutOfMemory\|kIOGPUCommandBuffer.*OutOfMemory"; then
            log "OOM detected — ensuring --grad-checkpoint is in train.sh"
            if ! grep -q "\-\-grad-checkpoint" "$TRAIN_SH"; then
                sed -i '' 's/--adapter-path "\$ADAPTER_DIR" \\/--adapter-path "$ADAPTER_DIR" \\\n        --grad-checkpoint \\/' "$TRAIN_SH"
                log "Added --grad-checkpoint"
            fi
        fi
    fi

    log "Restarting in 10s..."
    sleep 10
done
