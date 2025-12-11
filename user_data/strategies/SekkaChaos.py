# ================================================================
# SekkaChaos - Bill Williams Chaos Theory + DCA
# ---------------------------------------------------------------
# Logic:
# 1. Alligator Indicator (Trend direction)
# 2. Awesome Oscillator (Momentum)
# 3. Fractals (Breakout levels)
# 4. DCA for position management
# ================================================================

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from pandas import DataFrame
import pandas as pd
import numpy as np
import talib.abstract as ta
import logging

class SekkaChaos(IStrategy):
    timeframe = "1h"
    informative_timeframes = []
    process_only_new_candles = True
    
    # Enable Shorting
    can_short = True 

    # DCA / Position Management
    position_adjustment_enable = True
    max_entry_position_adjustment = -1 

    startup_candle_count = 100

    # ---------------- Parameters ----------------
    # DCA
    DCA_STEP = IntParameter(1, 6, default=3, space="buy", optimize=True)
    DCA_THRESHOLD = DecimalParameter(0.01, 0.10, default=0.03, space="buy", optimize=True)
    
    # Chaos / Entry Params
    AO_THRESHOLD = DecimalParameter(-5.0, 5.0, default=0.0, space="buy", optimize=True)
    
    # Exit
    TP_THRESHOLD = DecimalParameter(0.01, 0.10, default=0.04, space="sell", optimize=True)
    
    # ---------------- Strategy Settings ----------------
    minimal_roi = {
        "0": 0.20,
        "30": 0.10,
        "60": 0.05,
        "120": 0
    }
    
    stoploss = -0.99  # We use DCA, so wide stoploss initially

    logger = logging.getLogger(__name__)
    _last_dca_stage = None

    # ---------------- Plot Config ----------------
    plot_config = {
        "main_plot": {
            "jaw": {"color": "blue"},
            "teeth": {"color": "red"},
            "lips": {"color": "green"},
        },
        "subplots": {
            "AO": {
                "ao": {"type": "bar", "color": "orange"}
            }
        }
    }

    # ---------------- Indicators ----------------
    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        
        # 1. Awesome Oscillator (AO)
        # AO = SMA(High+Low/2, 5) - SMA(High+Low/2, 34)
        median_price = (df['high'] + df['low']) / 2
        df['ao'] = ta.SMA(median_price, timeperiod=5) - ta.SMA(median_price, timeperiod=34)

        # 2. Williams Alligator
        # Uses Smoothed Moving Average (SMMA). 
        # SMMA(n) approx EMA(2n-1) or manual calculation. We'll use manual for accuracy if speed allows, 
        # or simple EMA approximation for speed. Let's use EMA approximation slightly adjusted.
        # Jaw (Blue): 13-period SMMA, shifted 8
        # Teeth (Red): 8-period SMMA, shifted 5
        # Lips (Green): 5-period SMMA, shifted 3
        
        # SMMA approx using EMA: timeperiod = 2*n - 1
        # Use pandas ewm for potentially better Series preservation, but ta.EMA is fine if wrapped
        df['jaw'] = pd.Series(ta.EMA(median_price, timeperiod=(2*13)-1), index=df.index).shift(8)
        df['teeth'] = pd.Series(ta.EMA(median_price, timeperiod=(2*8)-1), index=df.index).shift(5)
        df['lips'] = pd.Series(ta.EMA(median_price, timeperiod=(2*5)-1), index=df.index).shift(3)

        # 3. Fractals (2-bar lag)
        # Bullish Fractal: High[i-2] is highest of 5 candles
        # Bearish Fractal: Low[i-2] is lowest of 5 candles
        # Note: This signal appears at candle `i`, based on `i-2`.
        df['is_fractal_up'] = (
            (df['high'].shift(2) > df['high'].shift(3)) &
            (df['high'].shift(2) > df['high'].shift(4)) &
            (df['high'].shift(2) > df['high'].shift(1)) &
            (df['high'].shift(2) > df['high'])
        )
        
        df['is_fractal_down'] = (
            (df['low'].shift(2) < df['low'].shift(3)) &
            (df['low'].shift(2) < df['low'].shift(4)) &
            (df['low'].shift(2) < df['low'].shift(1)) &
            (df['low'].shift(2) < df['low'])
        )

        return df

    # ---------------- Entry Logic ----------------
    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[
            (
                # Long Condition (Bullish Chaos)
                # 1. Alligator Open Up (Lips > Teeth > Jaw)
                (df['lips'] > df['teeth']) &
                (df['teeth'] > df['jaw']) &
                
                # 2. Momentum increasing (AO > 0 or Rising)
                (df['ao'] > 0) &
                (df['ao'] > df['ao'].shift(1))
                
                # Optional: Fractal breakout could be added here
            ),
            'enter_long'] = 1

        df.loc[
            (
                # Short Condition (Bearish Chaos)
                # 1. Alligator Open Down (Lips < Teeth < Jaw)
                (df['lips'] < df['teeth']) &
                (df['teeth'] < df['jaw']) &
                
                # 2. Momentum decreasing
                (df['ao'] < 0) &
                (df['ao'] < df['ao'].shift(1))
            ),
            'enter_short'] = 1
            
        return df

    # ---------------- Exit Logic ----------------
    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        # We rely mostly on TP/SL/DCA, but can add trend reversal exit
        df.loc[
            (
                # Exit Long if Alligator closes mouths (Lips cross below Teeth)
                (df['lips'] < df['teeth'])
            ),
            'exit_long'] = 1

        df.loc[
            (
                # Exit Short if Alligator closes mouths (Lips cross above Teeth)
                (df['lips'] > df['teeth'])
            ),
            'exit_short'] = 1
            
        return df

    # ---------------- DCA Logic (Copied from Sekka) ----------------
    def custom_stake_amount(self, pair: str, current_time: pd.Timestamp, current_rate: float, **kwargs) -> float:
        balance = self.wallets.get_total_stake_amount()
        free = self.wallets.get_available_stake_amount()
        used = max(balance - free, 0)
        remaining = max(balance - used, 0)
        trade = kwargs.get("trade", None)
        stage = trade.nr_of_successful_entries if trade else 0
        total_steps = self.DCA_STEP.value if hasattr(self.DCA_STEP, 'value') else self.DCA_STEP

        if stage == 0:
            stake = balance / total_steps
        else:
            remaining_steps = total_steps - stage
            stake = remaining / remaining_steps if remaining_steps > 0 else 0

        return float(max(min(stake, remaining), 0.0))

    def adjust_trade_position(self, trade, current_time, current_rate, current_profit, **kwargs):
        if self._last_dca_stage is None: self._last_dca_stage = {}
        trade_id = f"{trade.pair}_{trade.open_date}"
        current_stage = trade.nr_of_successful_entries
        
        # Limit total entries
        dca_limit = self.DCA_STEP.value if hasattr(self.DCA_STEP, 'value') else self.DCA_STEP
        if current_stage >= (dca_limit + 1):
            return 0
            
        if self._last_dca_stage.get(trade_id) == current_stage:
            return 0

        # DCA Trigger
        # Short: price goes UP (current_rate > open_rate)
        # Long: price goes DOWN (current_rate < open_rate)
        
        dca_thresh = self.DCA_THRESHOLD.value if hasattr(self.DCA_THRESHOLD, 'value') else self.DCA_THRESHOLD
        
        if trade.is_short:
             # Short DCA: Price rose by X%
             drop_ratio = (current_rate / trade.open_rate) - 1.0
             if drop_ratio >= dca_thresh:
                # Trigger Short DCA
                return self._execute_dca(trade, current_time, current_rate, current_stage)
        else:
             # Long DCA: Price dropped by X%
             drop_ratio = (current_rate / trade.open_rate) - 1.0
             if drop_ratio <= -dca_thresh:
                 # Trigger Long DCA
                 return self._execute_dca(trade, current_time, current_rate, current_stage)

        return 0

    def _execute_dca(self, trade, current_time, current_rate, current_stage):
        stake = self.custom_stake_amount(trade.pair, current_time, current_rate, trade=trade)
        if self.wallets.get_available_stake_amount() >= stake:
             self._last_dca_stage[f"{trade.pair}_{trade.open_date}"] = current_stage
             return stake
        return 0

    def custom_exit(self, pair: str, trade, current_time, current_rate, **kwargs):
        # Allow basic TP exit
        start_rate = trade.open_rate
        current_profit = (start_rate - current_rate) / start_rate if trade.is_short else (current_rate - start_rate) / start_rate
        
        tp = self.TP_THRESHOLD.value if hasattr(self.TP_THRESHOLD, 'value') else self.TP_THRESHOLD
        
        if current_profit >= tp:
             return "TAKE_PROFIT"
        return None
