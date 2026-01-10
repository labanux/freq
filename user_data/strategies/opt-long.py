# ================================================================
# SekkaStrat v14n – Fixed DCA trigger not executing (Freqtrade 2025.10)
# ---------------------------------------------------------------
# Fixes:
# - DCA now executes correctly by returning actual stake amount (est_stake)
# - Preserves 3-step recursive DCA at -3% from avg price
# - Fully compatible with Freqtrade 2025.10 wallet API
# ================================================================

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from pandas import DataFrame
import pandas as pd
import numpy as np
import talib.abstract as ta
import logging
from datetime import datetime
from typing import Optional


class OptLong(IStrategy):
    timeframe = "1h"
    informative_timeframes = []  # Single timeframe only - no multi-timeframe
    process_only_new_candles = True
    can_short = False  # Long-only strategy

    use_exit_signal = True
    exit_profit_only = False
    ignore_buying_expiry = True
    position_adjustment_enable = True  # ✅ Ensure DCA works

    startup_candle_count = 20

    # LONG Parameters
    TP_PERCENTAGE = DecimalParameter(0.01, 0.04, default=0.01, decimals=2, space="sell", optimize=True)
    TP_RSI = IntParameter(55, 70, default=65, space="sell", optimize=True)

    DCA_THRESHOLD = DecimalParameter(0.04, 0.10, default=0.01, decimals=2, space="buy", optimize=True)
    DCA_STEP = IntParameter(4, 6, default=4, space="buy", optimize=True)
    ENTRY_VWAP_GAP = DecimalParameter(-0.10, -0.03, default=-0.03, decimals=2, space="buy", optimize=True)
    ENTRY_RSI = IntParameter(30, 45, default=30, space="buy", optimize=True)
    
    GENERAL_PERIOD = IntParameter(14, 20, default=14, space="buy", optimize=True)

    # Fixed Constants - Note: Use actual values in methods, not .value at class level
    # RSI_PERIOD and VWAP_WINDOW will use GENERAL_PERIOD.value in populate_indicators

    minimal_roi = {}  # We use custom_exit instead
    stoploss = -0.99
    LEVERAGE = 1

    #max_entry_position_adjustment = -1

    logger = logging.getLogger(__name__)
    _last_dca_stage = None

    # Protections (Freqtrade 2025.11+ requires in strategy, not config)
    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 24,
                "trade_limit": 1
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 2,
                "stop_duration_candles": 48,
                "only_per_pair": True
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 168,
                "trade_limit": 5,
                "stop_duration_candles": 24,
                "max_allowed_drawdown": 0.2
            }
        ]

    # ------------------ Informative Pairs ------------------
    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = []
        for pair in pairs:
            # Assume Futures pair 'BTC/USDT:USDT' -> Spot 'BTC/USDT'
            if ":" in pair:
                spot_pair = pair.split(':')[0]
            else:
                spot_pair = pair # Already spot?
            informative_pairs.append((spot_pair, self.timeframe, 'spot'))
        return informative_pairs

    # ------------------ Plot Config ------------------
    plot_config = {
        "main_plot": {
            "vwap_1h": {"color": "orange"},
            "ema_fast": {"color": "yellow"},
            "ema_slow": {"color": "blue"},
        },
        "subplots": {
            "RSI": {
                "rsi_1h": {"color": "red"},
            },
            "MACD": {
                "macd": {"color": "blue"},
                "macdsignal": {"color": "orange"},
                "macdhist": {"color": "green", "type": "bar"},
            },
        },
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
        # Single timeframe (1h) only - no multi-timeframe dependencies
        # Use GENERAL_PERIOD for both RSI and VWAP
        period = self.GENERAL_PERIOD.value
        df["rsi_1h"] = ta.RSI(df, timeperiod=period)
        df["vwap_1h"] = self.compute_vwap(df, period)
        df["vwap_gap_1h"] = np.where(df["vwap_1h"] > 0, (df["close"] / df["vwap_1h"]) - 1.0, 0.0)
        # EMAs
        #df["ema_fast"] = ta.EMA(df, timeperiod=6)
        #df["ema_slow"] = ta.EMA(df, timeperiod=24)

        # MACD
        #macd = ta.MACD(df)
        #df["macd"] = macd["macd"]
        #df["macdsignal"] = macd["macdsignal"]
        #df["macdhist"] = macd["macdhist"]
        return df

    # Freqtrade 2025.10+ requires populate_entry_trend/populate_exit_trend
    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["enter_long"] = 0
        df.loc[
            (df["rsi_1h"] <= self.ENTRY_RSI.value) 
            & (df["vwap_gap_1h"] < self.ENTRY_VWAP_GAP.value),
            "enter_long",
        ] = 1
        return df

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
        total_steps = self.DCA_STEP.value

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
        #self.logger.info(f"[{current_time}] {trade.pair} | DCA check stage={trade.nr_of_successful_entries}")
        if self._last_dca_stage is None:
            self._last_dca_stage = {}

        trade_id = getattr(trade, "id", None) or f"{trade.pair}_{getattr(trade, 'open_date', None)}"
        current_stage = trade.nr_of_successful_entries
        recorded = self._last_dca_stage.get(trade_id)

        if recorded is not None and recorded == current_stage:
            return 0
        
        # Stop if we reached max entries (Initial + DCA_STEP)
        if current_stage >= (self.DCA_STEP.value + 1):
            return 0

        avg_rate = trade.open_rate
        drop_ratio = (current_rate / avg_rate) - 1.0
        next_dca_trigger = -self.DCA_THRESHOLD.value

        free_balance = self.wallets.get_available_stake_amount()
        est_stake = self.custom_stake_amount(trade.pair, current_time, current_rate, trade=trade)

        if drop_ratio <= next_dca_trigger and free_balance >= est_stake:
            next_stage = current_stage + 1
            tag = f"DCA_{next_stage}"
            self._last_dca_stage[trade_id] = current_stage

            #self.logger.info(
            #    f"[{current_time}] {trade.pair} | Triggering {tag} at {current_rate:.4f} "
            #    f"({drop_ratio*100:.2f}%) | Free={free_balance:.2f} Stake={est_stake:.2f}"
            #)
            trade.enter_tag = tag
            return est_stake  # ✅ FIXED: execute with actual stake

        return 0

    # ------------------ Exit Logic ------------------
    def custom_exit(self, pair: str, trade, current_time, current_rate, **kwargs):
        avg_price = trade.open_rate
        dca_stage = trade.nr_of_successful_entries
        rel = (current_rate / avg_price) - 1.0

        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            rsi_1h = df.iloc[-1]["rsi_1h"]
        except Exception:
            rsi_1h = 50
            
        if rel >= self.TP_PERCENTAGE.value and rsi_1h >= self.TP_RSI.value: 
            #self.logger.info(f"[{current_time}] {pair} | TAKE_PROFIT reached +{rel*100:.2f}%")
            #self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
            return "TAKE_PROFIT"

        # Stop loss after all DCAs are used
        if dca_stage >= (self.DCA_STEP.value + 1) and rel <= -self.DCA_THRESHOLD.value:
        #    self.logger.info(f"[{current_time}] {pair} | STOP_LOSS_AFTER_DCA triggered {rel*100:.2f}%")
            self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
            return "STOP_LOSS_AFTER_DCA"

        return None

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: Optional[str], side: str,
                 **kwargs) -> float:
        return self.LEVERAGE