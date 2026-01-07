#!/bin/bash
#===============================================================================
# Freqtrade Hyperopt Runner
# 
# This script runs hyperopt optimization. Can be run locally or on VM.
#
# Usage:
#   ./run-hyperopt.sh                     # Use defaults
#   ./run-hyperopt.sh --strategy SekkaLong
#   ./run-hyperopt.sh --epochs 1000
#   ./run-hyperopt.sh --timerange 20240101-20251230
#===============================================================================

set -e

#-------------------------------------------------------------------------------
# DEFAULT CONFIGURATION - Modify these as needed
#-------------------------------------------------------------------------------

STRATEGY="OptLong"
HYPEROPT_LOSS="ZeroLossMaxTrades"
SPACES="buy sell"
TIMERANGE="20220101-20251230"
CONFIG="user_data/config-long.json"
EPOCHS=1000
JOBS=-1  # -1 = use all cores

#-------------------------------------------------------------------------------
# Parse command line arguments
#-------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        --strategy|-s)
            STRATEGY="$2"
            shift 2
            ;;
        --loss)
            HYPEROPT_LOSS="$2"
            shift 2
            ;;
        --spaces)
            SPACES="$2"
            shift 2
            ;;
        --timerange|-t)
            TIMERANGE="$2"
            shift 2
            ;;
        --config|-c)
            CONFIG="$2"
            shift 2
            ;;
        --epochs|-e)
            EPOCHS="$2"
            shift 2
            ;;
        --jobs|-j)
            JOBS="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: ./run-hyperopt.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --strategy, -s    Strategy name (default: OptLong)"
            echo "  --loss            Hyperopt loss function (default: ZeroLossMaxTrades)"
            echo "  --spaces          Optimization spaces (default: buy sell)"
            echo "  --timerange, -t   Time range (default: 20230101-20251230)"
            echo "  --config, -c      Config file (default: user_data/config-long.json)"
            echo "  --epochs, -e      Number of epochs (default: 5000)"
            echo "  --jobs, -j        Number of parallel jobs, 0=all cores (default: 0)"
            echo "  --help, -h        Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

#-------------------------------------------------------------------------------
# Colors
#-------------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

#-------------------------------------------------------------------------------
# Display configuration
#-------------------------------------------------------------------------------
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Freqtrade Hyperopt Runner${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Strategy:    ${YELLOW}${STRATEGY}${NC}"
echo -e "Loss:        ${YELLOW}${HYPEROPT_LOSS}${NC}"
echo -e "Spaces:      ${YELLOW}${SPACES}${NC}"
echo -e "Timerange:   ${YELLOW}${TIMERANGE}${NC}"
echo -e "Config:      ${YELLOW}${CONFIG}${NC}"
echo -e "Epochs:      ${YELLOW}${EPOCHS}${NC}"
echo -e "Jobs:        ${YELLOW}${JOBS}${NC}"
echo ""
echo -e "Started at:  ${YELLOW}$(date)${NC}"
echo ""

#-------------------------------------------------------------------------------
# Run Hyperopt
#-------------------------------------------------------------------------------
docker compose run --rm freqtrade hyperopt \
    --strategy "$STRATEGY" \
    --hyperopt-loss "$HYPEROPT_LOSS" \
    --spaces $SPACES \
    --timerange "$TIMERANGE" \
    --config "$CONFIG" \
    -j "$JOBS" \
    -e "$EPOCHS"

#-------------------------------------------------------------------------------
# Done
#-------------------------------------------------------------------------------
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✓ Hyperopt Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "Finished at: ${YELLOW}$(date)${NC}"
echo ""

#-------------------------------------------------------------------------------
# Export and upload best result to GCloud Storage
#-------------------------------------------------------------------------------
BUCKET_NAME="hyperopt_result"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULT_FILE="hyperopt_${STRATEGY}_${TIMESTAMP}.json"

echo -e "${YELLOW}Exporting best result...${NC}"
docker compose run --rm freqtrade hyperopt-show --best \
    --export-json "/freqtrade/user_data/${RESULT_FILE}" \
    --config "$CONFIG"

if [ -f "user_data/${RESULT_FILE}" ]; then
    echo -e "${YELLOW}Uploading to gs://${BUCKET_NAME}/${RESULT_FILE}...${NC}"
    gsutil cp "user_data/${RESULT_FILE}" "gs://${BUCKET_NAME}/${RESULT_FILE}"
    echo -e "${GREEN}✓ Result uploaded to GCloud Storage!${NC}"
    echo -e "  gs://${BUCKET_NAME}/${RESULT_FILE}"
else
    echo -e "${YELLOW}⚠ Could not export result file${NC}"
fi

echo ""
echo -e "To view results locally:"
echo -e "  docker compose run --rm freqtrade hyperopt-list --best -n 10 --config ${CONFIG}"

