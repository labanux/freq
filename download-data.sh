#!/bin/bash
#===============================================================================
# Freqtrade Data Downloader (Spot + Futures)
# 
# Downloads historical data for both spot and futures trading
#
# Usage:
#   ./download-data.sh                    # Use defaults
#   ./download-data.sh --timerange 20230101-20251230
#   ./download-data.sh --timeframes "1h 4h 1d"
#   ./download-data.sh --pairs "BTC/USDT ETH/USDT"
#===============================================================================

set -e

#-------------------------------------------------------------------------------
# DEFAULT CONFIGURATION - Modify these as needed
#-------------------------------------------------------------------------------

# Timeframes to download (1h for entry, 15m for trade detail)
TIMEFRAMES="1h 5m"

# Time range for data
TIMERANGE="20211231-20260101"

# Pairs for trading (space-separated)
PAIRS="BTC/USDT ETH/USDT SOL/USDT XRP/USDT LTC/USDT ADA/USDT DOGE/USDT ENA/USDT ZEC/USDT BNB/USDT"

# Exchange
EXCHANGE="binance"

# Flags
ERASE_EXISTING=false  # Default: incremental download (only missing data)

#-------------------------------------------------------------------------------
# Parse command line arguments
#-------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        --timeframes|-t)
            TIMEFRAMES="$2"
            shift 2
            ;;
        --timerange|-r)
            TIMERANGE="$2"
            shift 2
            ;;
        --pairs|-p)
            PAIRS="$2"
            shift 2
            ;;
        --exchange|-e)
            EXCHANGE="$2"
            shift 2
            ;;
        --no-erase)
            ERASE_EXISTING=false
            shift
            ;;
        --erase)
            ERASE_EXISTING=true
            shift
            ;;
        --help|-h)
            echo "Usage: ./download-data.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --timeframes, -t \"1h\"         Timeframes to download (default: 1h)"
            echo "  --timerange, -r 20220101-20251230  Date range for data"
            echo "  --pairs, -p \"BTC/USDT ETH/USDT\"   Pairs (space-separated)"
            echo "  --exchange, -e binance           Exchange name"
            echo "  --erase                          Erase existing data and redownload"
            echo "  --no-erase                       Keep existing data (default)"
            echo "  --help, -h                       Show this help"
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
echo -e "Pairs:       ${YELLOW}${PAIRS}${NC}"
echo -e "Erase:       ${YELLOW}${ERASE_EXISTING}${NC}"
echo ""

#-------------------------------------------------------------------------------
# Download Spot Data
#-------------------------------------------------------------------------------
echo -e "${YELLOW}[1/2] Downloading SPOT data (${TIMEFRAMES})...${NC}"
docker compose run --rm freqtrade download-data \
    --exchange "$EXCHANGE" \
    --trading-mode spot \
    --timeframes $TIMEFRAMES \
    --timerange "$TIMERANGE" \
    $ERASE_FLAG \
    --pairs $PAIRS

echo ""

#-------------------------------------------------------------------------------
# Download Futures Data
#-------------------------------------------------------------------------------
echo -e "${YELLOW}[2/2] Downloading FUTURES data (${TIMEFRAMES})...${NC}"

# Convert pairs to futures format (add :USDT suffix)
FUTURES_PAIRS=""
for PAIR in $PAIRS; do
    FUTURES_PAIRS="$FUTURES_PAIRS ${PAIR}:USDT"
done

docker compose run --rm freqtrade download-data \
    --exchange "$EXCHANGE" \
    --trading-mode futures \
    --timeframes $TIMEFRAMES \
    --timerange "$TIMERANGE" \
    $ERASE_FLAG \
    --pairs $FUTURES_PAIRS

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✓ Data Download Complete!${NC}"
echo -e "${GREEN}  - Spot: ${PAIRS}${NC}"
echo -e "${GREEN}  - Futures: ${FUTURES_PAIRS}${NC}"
echo -e "${GREEN}========================================${NC}"
