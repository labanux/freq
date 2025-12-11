freqtrade download-data --exchange binanceusdm --trading-mode futures -t 1m --pairs XRP/USDT --timerange 20241028-20251028
freqtrade backtesting --config user_data/config.json --strategy Sekka

# DOWNLOAD spot
docker exec -it freqtrade freqtrade download-data \
  --exchange binance \
  --trading-mode spot \
  --pairs SOL/USDT BTC/USDT ZEC/USDT XRP/USDT LTC/USDT ETH/USDT ENA/USDT \
  --timeframes 1h \
  --timerange 20241001-20251210 --erase

# Download Futures
docker exec -it freqtrade freqtrade download-data \
  --exchange binance \
  --trading-mode futures \
  --pairs SOL/USDT:USDT BTC/USDT:USDT ZEC/USDT:USDT XRP/USDT:USDT LTC/USDT:USDT ETH/USDT:USDT ENA/USDT:USDT \
  --timeframes 1h \
  --timerange 20241001-20251210 --erase

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
  --timerange 20241101-20251130 \
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
1. SSH
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
