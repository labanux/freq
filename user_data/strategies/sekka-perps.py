# ================================================================
# SekkaPerps – Production Strategy for Futures (Static Parameters)
# ---------------------------------------------------------------
# Same logic as SekkaLong, but configured for futures trading.
# Use this for live futures trading.
# ================================================================

from freqtrade.strategy import IStrategy
from pandas import DataFrame
import pandas as pd
import numpy as np
import talib.abstract as ta
import logging
from datetime import datetime
from typing import Optional


class SekkaPerps(IStrategy):
    timeframe = "1h"
    informative_timeframes = []  # Single timeframe only - no multi-timeframe
    process_only_new_candles = True
    can_short = False  # Long-only strategy

    use_exit_signal = True
    exit_profit_only = False
    ignore_buying_expiry = True
    position_adjustment_enable = True  # ✅ Ensure DCA works

    startup_candle_count = 20

    # ==============================================================
    # STATIC PARAMETERS - Update these from hyperopt results
    # ==============================================================
    
    # Buy parameters
    DCA_STEP = 7
    DCA_THRESHOLD = 0.04
    ENTRY_RSI = 40
    ENTRY_VWAP_GAP = -0.05
    GENERAL_PERIOD = 14

    # Sell parameters
    TP_PERCENTAGE = 0.02

    # Futures settings
    LEVERAGE = 3  # 3x leverage for futures
    COOLDOWN_HOURS = 24  # Hours to wait before re-entering after stop loss
    stoploss = -0.25  # Tighter stoploss for leverage (25% = ~75% with 3x)


    # ==============================================================

    minimal_roi = {}  # We use custom_exit instead
    stoploss = -0.7

    #max_entry_position_adjustment = -1

    logger = logging.getLogger(__name__)
    _last_dca_stage = None
    _stoploss_cooldown = {}  # Track pairs in cooldown after STOP_LOSS_AFTER_DCA
    

    # ------------------ Informative Pairs ------------------
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = []
        for pair in pairs:
            # Add main timeframe (for entry indicators)
            informative_pairs.append((pair, self.timeframe))
        return informative_pairs

    # ------------------ Leverage (Futures) ------------------
    def leverage(self, pair: str, current_time, current_rate: float,
                 proposed_leverage: float, max_leverage: float,
                 entry_tag: Optional[str], side: str, **kwargs) -> float:
        """
        Return the leverage to use for futures trading.
        """
        return float(self.LEVERAGE)

    # ------------------ Plot Config ------------------
    plot_config = {
        "main_plot": {
            "vwap_1h": {"color": "orange"}
            #"ema_fast": {"color": "yellow"},
            #"ema_slow": {"color": "blue"},
        }
        #"subplots": {
        #    "RSI": {
        #        "rsi_1h": {"color": "red"},
        #    },
        #    "MACD": {
        #        "macd": {"color": "blue"},
        #        "macdsignal": {"color": "orange"},
        #        "macdhist": {"color": "green", "type": "bar"},
        #    },
        #},
    }

    # ------------------ Indicators ------------------
    def hlc3(self, df: DataFrame) -> pd.Series:
        return (df["high"] + df["low"] + df["close"]) / 3.0

    def compute_vwap(self, df: DataFrame, window: int) -> pd.Series:
        hlc3 = self.hlc3(df)
        pv = hlc3 * df["volume"]
        pv_sum = pv.rolling(window, min_periods=1).sum()
        vol_sum = df["volume"].rolling(window, min_periods=1).sum()
        vwap = (pv_sum / vol_sum.replace(0, np.nan)).ffill().fillna(df["close"])
        return vwap

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        period = self.GENERAL_PERIOD
        
        # Calculate indicators on futures data
        df["rsi_1h"] = ta.RSI(df, timeperiod=period)
        df["vwap_1h"] = self.compute_vwap(df, period)
        df["vwap_gap_1h"] = np.where(df["vwap_1h"] > 0, (df["close"] / df["vwap_1h"]) - 1.0, 0.0)
        
        return df

    # Freqtrade 2025.10+ requires populate_entry_trend/populate_exit_trend
    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["enter_long"] = 0
        df.loc[
            (df["rsi_1h"] <= self.ENTRY_RSI) 
            & (df["vwap_gap_1h"] < self.ENTRY_VWAP_GAP),
            "enter_long",
        ] = 1
        return df

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, 
                            rate: float, time_in_force: str, current_time, 
                            entry_tag, side: str, **kwargs) -> bool:
        """
        Block entry if pair is in cooldown after STOP_LOSS_AFTER_DCA.
        """
        if self._stoploss_cooldown is None:
            self._stoploss_cooldown = {}
        
        cooldown_until = self._stoploss_cooldown.get(pair)
        if cooldown_until and current_time < cooldown_until:
            self.logger.info(f"[{pair}] Entry blocked - cooldown until {cooldown_until}")
            return False
        
        # Clear expired cooldown
        if cooldown_until and current_time >= cooldown_until:
            self._stoploss_cooldown.pop(pair, None)
        
        return True

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["exit_long"] = 0
        return df

    # ------------------ Custom Stake ------------------
    def custom_stake_amount(self, pair: str, current_time: pd.Timestamp, current_rate: float, **kwargs) -> float:
        balance = self.wallets.get_total_stake_amount()
        free = self.wallets.get_available_stake_amount()
        used = max(balance - free, 0)
        remaining = max(balance - used, 0)

        trade = kwargs.get("trade", None)
        stage = trade.nr_of_successful_entries if trade else 0
        
        # Total entries = DCA_STEP + 1 (Initial), since no cut loss, no need to add 1
        total_steps = self.DCA_STEP

        if stage == 0:
            stake = balance / total_steps
        else:
            # Remaining steps including this one
            remaining_steps = total_steps - stage
            if remaining_steps > 0:
                stake = remaining / remaining_steps
            else:
                stake = 0

        return float(max(min(stake, remaining), 0.0))

    # ------------------ DCA Logic ------------------
    def adjust_trade_position(self, trade, current_time, current_rate, current_profit, **kwargs):
        if self._last_dca_stage is None:
            self._last_dca_stage = {}

        trade_id = getattr(trade, "id", None) or f"{trade.pair}_{getattr(trade, 'open_date', None)}"
        current_stage = trade.nr_of_successful_entries
        recorded = self._last_dca_stage.get(trade_id)

        if recorded is not None and recorded == current_stage:
            return 0
        
        # Stop if we reached max entries (Initial + DCA_STEP)
        if current_stage >= (self.DCA_STEP + 1):
            return 0

        avg_rate = trade.open_rate
        drop_ratio = (current_rate / avg_rate) - 1.0
        next_dca_trigger = -self.DCA_THRESHOLD

        free_balance = self.wallets.get_available_stake_amount()
        est_stake = self.custom_stake_amount(trade.pair, current_time, current_rate, trade=trade)

        if drop_ratio <= next_dca_trigger and free_balance >= est_stake:
            next_stage = current_stage + 1
            tag = f"DCA_{next_stage}"
            self._last_dca_stage[trade_id] = current_stage
            trade.enter_tag = tag
            return est_stake  # ✅ FIXED: execute with actual stake

        return 0

    # ------------------ Exit Logic ------------------
    def custom_exit(self, pair: str, trade, current_time, current_rate, **kwargs):
        avg_price = trade.open_rate
        dca_stage = trade.nr_of_successful_entries
        
        # For spot trading, use current_rate directly
        rel = (current_rate / avg_price) - 1.0

        # Get RSI from exit timeframe (matches --timeframe-detail)
        #try:
            #df, _ = self.dp.get_analyzed_dataframe(pair, self.EXIT_TIMEFRAME)
            # Calculate RSI on the exit timeframe data
            #import talib.abstract as ta_exit
            #rsi_exit = ta_exit.RSI(df, timeperiod=self.GENERAL_PERIOD).iloc[-1]
            #rsi_exit = 50
        #except Exception:
        #    rsi_exit = 50  # Default if unable to get RSI

        # Take profit based on price percentage & RSI
        if rel >= self.TP_PERCENTAGE: # and rsi_exit >= self.TP_RSI:
            return "TAKE_PROFIT"

        # Stop loss after all DCAs are used
        if dca_stage >= (self.DCA_STEP + 1) and rel <= -self.DCA_THRESHOLD:
            self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
            
            # Set cooldown for this pair
            if self._stoploss_cooldown is None:
                self._stoploss_cooldown = {}
            from datetime import timedelta
            cooldown_until = current_time + timedelta(hours=self.COOLDOWN_HOURS)
            self._stoploss_cooldown[pair] = cooldown_until
            self.logger.info(f"[{pair}] STOP_LOSS_AFTER_DCA - cooldown until {cooldown_until}")
            
            return "STOP_LOSS_AFTER_DCA"

        return None