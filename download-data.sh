#!/bin/bash
#===============================================================================
# Freqtrade Data Downloader
# 
# Downloads historical data for both Spot and Futures trading
#
# Usage:
#   ./download-data.sh                    # Use defaults
#   ./download-data.sh --timerange 20230101-20251230
#   ./download-data.sh --timeframes "1h 4h 1d"
#   ./download-data.sh --pairs "BTC/USDT ETH/USDT"
#   ./download-data.sh --spot-only        # Only download spot data
#   ./download-data.sh --futures-only     # Only download futures data
#===============================================================================

set -e

#-------------------------------------------------------------------------------
# DEFAULT CONFIGURATION - Modify these as needed
#-------------------------------------------------------------------------------

# Timeframes to download (space-separated)
TIMEFRAMES="1h"

# Time range for data
TIMERANGE="20220101-20251230"

# Pairs for Spot trading (space-separated)
SPOT_PAIRS="SOL/USDT BTC/USDT ZEC/USDT XRP/USDT LTC/USDT ETH/USDT ENA/USDT"

# Pairs for Futures trading (auto-generated from SPOT_PAIRS if not specified)
FUTURES_PAIRS=""

# Exchange
EXCHANGE="binance"

# Flags
DOWNLOAD_SPOT=true
DOWNLOAD_FUTURES=true
ERASE_EXISTING=true

#-------------------------------------------------------------------------------
# Parse command line arguments
#-------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        --timeframes)
            TIMEFRAMES="$2"
            shift 2
            ;;
        --timerange)
            TIMERANGE="$2"
            shift 2
            ;;
        --pairs)
            SPOT_PAIRS="$2"
            shift 2
            ;;
        --futures-pairs)
            FUTURES_PAIRS="$2"
            shift 2
            ;;
        --exchange)
            EXCHANGE="$2"
            shift 2
            ;;
        --spot-only)
            DOWNLOAD_FUTURES=false
            shift
            ;;
        --futures-only)
            DOWNLOAD_SPOT=false
            shift
            ;;
        --no-erase)
            ERASE_EXISTING=false
            shift
            ;;
        --help|-h)
            echo "Usage: ./download-data.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --timeframes \"1h 4h 1d\"    Timeframes to download (space-separated)"
            echo "  --timerange 20220101-20251230  Date range for data"
            echo "  --pairs \"BTC/USDT ETH/USDT\"   Spot pairs (space-separated)"
            echo "  --futures-pairs \"...\"         Futures pairs (auto-generated if not set)"
            echo "  --exchange binance             Exchange name"
            echo "  --spot-only                    Only download spot data"
            echo "  --futures-only                 Only download futures data"
            echo "  --no-erase                     Don't erase existing data"
            echo "  --help                         Show this help"
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
# Auto-generate futures pairs from spot pairs if not specified
#-------------------------------------------------------------------------------
if [ -z "$FUTURES_PAIRS" ]; then
    FUTURES_PAIRS=""
    for pair in $SPOT_PAIRS; do
        # Convert SOL/USDT to SOL/USDT:USDT
        FUTURES_PAIRS="$FUTURES_PAIRS ${pair}:USDT"
    done
    FUTURES_PAIRS=$(echo $FUTURES_PAIRS | xargs)  # Trim whitespace
fi

#-------------------------------------------------------------------------------
# Build erase flag
#-------------------------------------------------------------------------------
ERASE_FLAG=""
if [ "$ERASE_EXISTING" = true ]; then
    ERASE_FLAG="--erase"
fi

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
echo -e "${BLUE}  Freqtrade Data Downloader${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Exchange:    ${YELLOW}${EXCHANGE}${NC}"
echo -e "Timeframes:  ${YELLOW}${TIMEFRAMES}${NC}"
echo -e "Timerange:   ${YELLOW}${TIMERANGE}${NC}"
echo -e "Spot Pairs:  ${YELLOW}${SPOT_PAIRS}${NC}"
echo -e "Futures:     ${YELLOW}${FUTURES_PAIRS}${NC}"
echo -e "Erase:       ${YELLOW}${ERASE_EXISTING}${NC}"
echo ""

#-------------------------------------------------------------------------------
# Download Spot Data
#-------------------------------------------------------------------------------
if [ "$DOWNLOAD_SPOT" = true ]; then
    echo -e "${YELLOW}[1/2] Downloading SPOT data...${NC}"
    docker compose run --rm freqtrade download-data \
        --exchange "$EXCHANGE" \
        --trading-mode spot \
        --timeframes $TIMEFRAMES \
        --timerange "$TIMERANGE" \
        $ERASE_FLAG \
        --pairs $SPOT_PAIRS
    echo -e "${GREEN}✓ Spot data downloaded!${NC}"
    echo ""
fi

#-------------------------------------------------------------------------------
# Download Futures Data
#-------------------------------------------------------------------------------
if [ "$DOWNLOAD_FUTURES" = true ]; then
    echo -e "${YELLOW}[2/2] Downloading FUTURES data...${NC}"
    docker compose run --rm freqtrade download-data \
        --exchange "$EXCHANGE" \
        --trading-mode futures \
        --timeframes $TIMEFRAMES \
        --timerange "$TIMERANGE" \
        $ERASE_FLAG \
        --pairs $FUTURES_PAIRS
    echo -e "${GREEN}✓ Futures data downloaded!${NC}"
    echo ""
fi

#-------------------------------------------------------------------------------
# Done
#-------------------------------------------------------------------------------
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✓ Data Download Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
