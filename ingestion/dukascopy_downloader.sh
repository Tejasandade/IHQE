#!/bin/bash
# =============================================================================
# IHQE — Dukascopy Historical Data Downloader
# Downloads XAU/USD OHLCV data year-by-year from 2003 to current year
# Uses npx dukascopy-node — no global install required
# =============================================================================

set -e

ASSET="xauusd"
START_YEAR=2003
END_YEAR=$(date +%Y)
OUTPUT_DIR="data/historical/xauusd"

# Parse arguments
TEST_MODE=false
YEARS_LIMIT=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --test) TEST_MODE=true; shift ;;
        --years) YEARS_LIMIT=$2; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ "$TEST_MODE" = true ] && [ "$YEARS_LIMIT" -gt 0 ]; then
    START_YEAR=$((END_YEAR - YEARS_LIMIT + 1))
    echo "[INFO] Test mode: downloading years $START_YEAR to $END_YEAR only"
fi

mkdir -p "$OUTPUT_DIR"

echo "============================================"
echo "  IHQE Dukascopy Downloader"
echo "  Asset: $ASSET"
echo "  Range: $START_YEAR — $END_YEAR"
echo "============================================"

FAILED=()
SUCCESS_COUNT=0

for YEAR in $(seq $START_YEAR $END_YEAR); do
    for TF in h1 h4; do
        OUTFILE="$OUTPUT_DIR/${ASSET}_${YEAR}_${TF}.csv"
        
        # Skip if already downloaded and has sufficient data
        if [ -f "$OUTFILE" ]; then
            LINE_COUNT=$(wc -l < "$OUTFILE" 2>/dev/null || echo 0)
            if [ "$LINE_COUNT" -gt 1000 ]; then
                echo "[$YEAR $TF] Already exists ($LINE_COUNT rows). Skipping."
                SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
                continue
            fi
        fi

        echo "[$YEAR $TF] Downloading..."
        
        # Try download with retry
        RETRY=0
        MAX_RETRY=1
        while [ $RETRY -le $MAX_RETRY ]; do
            if npx -y dukascopy-node \
                -i "$ASSET" \
                -from "${YEAR}-01-01" \
                -to "${YEAR}-12-31" \
                -t "$TF" \
                -f csv \
                -dir "$OUTPUT_DIR" \
                -fn "${ASSET}_${YEAR}_${TF}" 2>/dev/null; then
                
                if [ -f "$OUTFILE" ]; then
                    LINE_COUNT=$(wc -l < "$OUTFILE")
                    echo "[$YEAR $TF] Done. ($LINE_COUNT rows)"
                    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
                    break
                fi
            fi
            
            if [ $RETRY -lt $MAX_RETRY ]; then
                echo "[$YEAR $TF] Failed. Retrying..."
                RETRY=$((RETRY + 1))
            else
                echo "[$YEAR $TF] FAILED after retry. Skipping."
                FAILED+=("${YEAR}_${TF}")
                break
            fi
        done
    done
done

echo ""
echo "============================================"
echo "  Download Complete"
echo "  Success: $SUCCESS_COUNT files"
echo "  Failed:  ${#FAILED[@]} files"
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "  Failed files: ${FAILED[*]}"
fi
echo "============================================"
