freqtrade download-data --exchange binanceusdm --trading-mode futures -t 1m --pairs XRP/USDT --timerange 20241028-20251028
freqtrade backtesting --config user_data/config.json --strategy Sekka

# DOWNLOAD spot
docker exec -it freqtrade freqtrade download-data \
  --exchange binance \
  --trading-mode spot \
  --timeframes 1d \
  --timerange 20220101-20251230 --erase \
  --pairs SOL/USDT BTC/USDT ZEC/USDT XRP/USDT LTC/USDT ETH/USDT ENA/USDT

# Download Futures
docker exec -it freqtrade freqtrade download-data \
  --exchange binance \
  --trading-mode futures \
  --pairs SOL/USDT:USDT BTC/USDT:USDT ZEC/USDT:USDT XRP/USDT:USDT LTC/USDT:USDT ETH/USDT:USDT ENA/USDT:USDT \
  --timeframes 1d \
  --timerange 20220101-20251230 --erase

# DOWNLOAD spot Hyperliquid
docker exec -it freqtrade python3 /freqtrade/user_data/strategies/download_hl.py

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
  --timerange 20220101-20251230 \
  --config user_data/config-hour.json \
  -p XRP/USDT 

# Futures
docker exec -it freqtrade freqtrade backtesting \
  --strategy SekkaLong \
  --dry-run-wallet 100000 \
  --timerange 20220101-20251230 \
  --config user_data/config-long.json \
  --pairs BTC/USDT:USDT

docker exec -it freqtrade freqtrade backtesting \
  --strategy SekkaStrat \
  --timerange 20241101-20251031 \
  -p XRP/USDT


docker compose run --rm freqai backtesting --config /freqtrade/user_data/config-ai.json --strategy SekkaAi --timerange 20241101-20251031 --freqaimodel LightGBMClassifier

# Hyper OPT
docker exec -it freqtrade freqtrade hyperopt \
  --strategy OptLong \
  --hyperopt-loss ZeroLossMaxTrades \
  --spaces buy sell \
  --timerange 20230101-20251230 \
  --config user_data/config-long.json \
  -j 0 -e 5000


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

If edited on server:
- git stash
- git pull
- git stash pop

Overwrite Local files:
git checkout -- user_data/strategies/opt-long.py
git pull

IF permission denied:
sudo chown -R $USER:$USER /freqtrade/user_data

## RUN ON PROD #####
# 1. Stop and remove existing container
docker stop freqtrade-main
docker rm freqtrade-main
docker restart freqtrade-main
docker logs freqtrade-main

# 2. Re-run with port mapping (-p 8080:8080) & correct user ID if needed
docker run -d \
  --name freqtrade-main \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/user_data:/freqtrade/user_data \
  freqtradeorg/freqtrade:stable \
  trade \
  --config /freqtrade/user_data/config-long.json \
  --strategy SekkaLong

# Start Bot
curl -X POST http://localhost:8080/api/v1/start \
     -H "Content-Type: application/json" \
     -u admin:admin


## TELEGRAM
Step 1: Get Token & Chat ID

Token: Message @BotFather on Telegram. Send /newbot. Follow steps. You get a token like 123456789:ABCdef....
Chat ID: Message @userinfobot (or your new bot). Get your numeric ID (e.g., 12345678).

## Increase SWAP
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab


30 Dec
docker exec -it freqtrade freqtrade hyperopt --strategy OptLong --hyperopt-loss ZeroLossMaxTrades --spaces buy sell --timerange 20230101-20251228 --config user_data/config-long.json -e 5000
Change to include Leverage


# Buy parameters:
    buy_params = {
        "DCA_STEP": 10,
        "DCA_THRESHOLD": 0.1,
        "RSI_THRESHOLD": 42,
        "VWAP_GAP": -0.05,
    }

    # Sell parameters:
    sell_params = {
        "LEVERAGE": 1,
        "RSI_TP": 60,
        "TP_THRESHOLD": 0.01,
    }

    TP_THRESHOLD = 0.01
    DCA_THRESHOLD = 0.1
    RSI_THRESHOLD = 42


# Pre-Requisite Shell:
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com

# With shell script:
./gcloud-create-vm.sh (default hyperopt-vm)
./gcloud-manage-vm.sh init
./gcloud-manage-vm.sh update
./gcloud-manage-vm.sh download --timeframes 1d --timerange 20220101-20251230
./gcloud-manage-vm.sh run-bg -e

Other commands:
./gcloud-manage-vm.sh stop
./gcloud-manage-vm.sh start
./gcloud-manage-vm.sh status
./gcloud-manage-vm.sh delete
