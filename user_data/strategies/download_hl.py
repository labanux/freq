
import ccxt.async_support as ccxt
import asyncio
import json
import gzip
import os
from datetime import datetime
import time

# Options
PAIRS = ['SOL/USDC', 'BTC/USDC', 'ETH/USDC', 'HYPE/USDC']
TIMEFRAME = '1h'
SINCE_STR = '2024-11-01 00:00:00'
DATA_DIR = 'user_data/data/hyperliquid'

async def download_pair(ex, pair):
    print(f"Downloading {pair}...")
    since = ex.parse8601(SINCE_STR)
    all_ohlcv = []
    
    while True:
        try:
            # Hyperliquid might not support 'since' correctly in all versions, 
            # but usually fetch_ohlcv supports it.
            ohlcv = await ex.fetch_ohlcv(pair, TIMEFRAME, since, limit=1000)
            if not ohlcv:
                break
            
            all_ohlcv.extend(ohlcv)
            last_ts = ohlcv[-1][0]
            
            print(f"  Fetched {len(ohlcv)} candles. Last: {datetime.fromtimestamp(last_ts/1000)}")
            
            # Prevent infinite loop if exchange returns same data
            if last_ts == since:
                # Try to advance by 1 hour explicitly if stuck
                since += 3600000
                if since > time.time() * 1000:
                   break
                continue
            
            since = last_ts + 1
            
            # Simple rate limit wait
            await asyncio.sleep(0.5)
            
            # Stop if reached now
            if last_ts > (time.time() * 1000) - 3600000: # Within last hour
                break
                
        except Exception as e:
            print(f"  Error fetching {pair}: {e}")
            break
            
    return all_ohlcv

import pandas as pd

async def save_to_file(pair, ohlcv):
    if not ohlcv:
        print(f"No data for {pair}")
        return

    # Create DataFrame
    columns = ['date', 'open', 'high', 'low', 'close', 'volume']
    df = pd.DataFrame(ohlcv, columns=columns)
    
    # Convert date to datetime if needed, but Freqtrade might expect int timestamps 
    # OR datetime objects.
    # Freqtrade Feather expects: date (datetime64[ns, UTC]), open, high, low, close, volume (float64)
    df['date'] = pd.to_datetime(df['date'], unit='ms', utc=True)
    df['open'] = df['open'].astype('float64')
    df['high'] = df['high'].astype('float64')
    df['low'] = df['low'].astype('float64')
    df['close'] = df['close'].astype('float64')
    df['volume'] = df['volume'].astype('float64')

    # Freqtrade format: pair name in filename should use underscore? 
    # Usually: BTC_USDC-1h.feather
    filename_pair = pair.replace('/', '_')
    path = f"{DATA_DIR}/{filename_pair}-{TIMEFRAME}.feather"
    
    # Ensure directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Save Feather
    df.to_feather(path)
        
    print(f"Saved {len(df)} candles to {path}")

async def main():
    config = {
        'timeout': 30000, 
        'options': {'defaultType': 'spot', 'fetchMarkets': {'hip3': {'limit': 10000}}}
    }
    ex = ccxt.hyperliquid(config)
    
    try:
        await ex.load_markets()
        print(f"Markets loaded: {len(ex.markets)}")
        
        for pair in PAIRS:
            if pair in ex.markets:
                data = await download_pair(ex, pair)
                await save_to_file(pair, data)
            else:
                print(f"Pair {pair} not found on exchange.")
                
    finally:
        await ex.close()

if __name__ == "__main__":
    asyncio.run(main())
