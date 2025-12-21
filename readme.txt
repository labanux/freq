freqtrade download-data --exchange binanceusdm --trading-mode futures -t 1m --pairs XRP/USDT --timerange 20241028-20251028
freqtrade backtesting --config user_data/config.json --strategy Sekka

# DOWNLOAD spot
docker exec -it freqtrade freqtrade download-data \
  --exchange binance \
  --trading-mode spot \
  --pairs SOL/USDT BTC/USDT ZEC/USDT XRP/USDT LTC/USDT ETH/USDT ENA/USDT \
  --timeframes 1h \
  --timerange 20241001-20251220 --erase

# Download Futures
docker exec -it freqtrade freqtrade download-data \
  --exchange binance \
  --trading-mode futures \
  --pairs SOL/USDT:USDT BTC/USDT:USDT ZEC/USDT:USDT XRP/USDT:USDT LTC/USDT:USDT ETH/USDT:USDT ENA/USDT:USDT \
  --timeframes 1h \
  --timerange 20241001-20251220 --erase

docker exec -it freqtrade freqtrade download-data \
  --exchange binanceus \
  --timeframes 1h \
  --pairs LTC/USDT \
  --timerange 20210101-20251130

docker exec -it freqtrade freqtrade webserver \
  --datadir /freqtrade/user_data/data \
  --config /freqtrade/user_data/config.json \
  --logfile /freqtrade/user_data/logs/freqtrade.log

#refresh
docker compose restart freqtrade

## BACKTESTING
docker exec -it freqtrade freqtrade backtesting \
  --strategy SekkaHour \
  --dry-run-wallet 100000 \
  --timerange 20241101-20251130 \
  --config user_data/config-hour.json \
  -p XRP/USDT 

# Futures
docker exec -it freqtrade freqtrade backtesting \
  --strategy SekkaLong \
  --dry-run-wallet 100000 \
  --timerange 20241101-20251219 \
  --config user_data/config-long.json \
  --pairs BTC/USDT:USDT

docker exec -it freqtrade freqtrade backtesting \
  --strategy SekkaStrat \
  --timerange 20241101-20251031 \
  -p XRP/USDT


docker compose run --rm freqai backtesting --config /freqtrade/user_data/config-ai.json --strategy SekkaAi --timerange 20241101-20251031 --freqaimodel LightGBMClassifier

# Hyper OPT
docker exec -it freqtrade freqtrade hyperopt \
  --strategy OptHour \
  --hyperopt-loss ZeroLossMaxTrades \
  --spaces buy sell \
  --timerange 20241101-20251130 \
  --config user_data/config-hour.json \
  -e 2000


docker compose run --rm freqtrade hyperopt \
  --config /freqtrade/user_data/config.json \
  --strategy OpSekka \
  --hyperopt-loss SharpeHyperOptLoss \
  --spaces buy sell \
  --timerange 20241101-20251031 \
  -e 100

docker compose run --rm freqtrade hyperopt \
  --strategy OptHour \
  --hyperopt-loss ProfitDrawDownHyperOptLoss \
  --spaces buy sell \
  --timerange 20241101-20251031 \
  -e 100

# DOCKER
Installation
sudo sh get-docker.sh
sudo usermod -aG docker $USER

Docker Build GCloud
1. Auth: gcloud auth configure-docker
2. Build: docker build --platform linux/amd64 -t gcr.io/lbn-financial-28pwg/freqos .
3. Push: docker push gcr.io/lbn-financial-28pwg/freqos

Docker Run on VM Instance:
1. SSH asia-southeast1-b
2. docker pull gcr.io/lbn-financial-28pwg/freqos
3. 

docker run --rm \
  --name freqrun \
  gcr.io/lbn-financial-28pwg/freqos \
  backtesting \
  --config /freqtrade/user_data/config.json \
  --strategy SekkaStrat \
  --timerange 20251001-20251031 \
  -p ZEC/USDT


1620/3000:     95 trades. 95/0/0 Wins/Draws/Losses. Avg profit   8.89%. Median profit   8.18%. Total profit 3632.48002317 USDT ( 363.25%). Avg duration 3 days, 14:37:00 min. Objective: -95.00000


    # Buy parameters:
    buy_params = {
        "DCA_STEP": 10,
        "DCA_THRESHOLD": 0.06,
        "RSI_THRESHOLD": 45,
        "VWAP_GAP": -0.06,
    }

    # Sell parameters:
    sell_params = {
        "RSI_TP": 60,
        "TP_THRESHOLD": 0.01,
    }

    # Stoploss parameters:
    stoploss = -0.99  # value loaded from strategy

    # Trailing stop parameters:
    trailing_stop = False  # value loaded from strategy
    trailing_stop_positive = None  # value loaded from strategy
    trailing_stop_positive_offset = 0.0  # value loaded from strategy
    trailing_only_offset_is_reached = False  # value loaded from strategy


    # max_open_trades parameters:
    max_open_trades = 7  # value loaded from strategy

## GIT
  On VM:
  ssh-keygen -t ed25519 -C "gcloud-vm"
  cat ~/.ssh/id_ed25519.pub

## On GitHub:
  Add Key to GitHub
  Go to your GitHub Repository -> Settings.
  Click Deploy keys (sidebar) -> Add deploy key.
  Title: GCloud VM
  Key: Paste the key you copied.
  Allow write access? (Optional, only if you plan to push changes from the VM).
  Click Add key.

## On VM:
git clone git@github.com:labanux/freq.git
or
git clone https://github.com/oktolibrasilaban/ft_userdata.git

cd dir name
git pull
