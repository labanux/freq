# ================================================================
# SekkaStrat v14n – Fixed DCA trigger not executing (Freqtrade 2025.10)
# ---------------------------------------------------------------
# Fixes:
# - DCA now executes correctly by returning actual stake amount (est_stake)
# - Preserves 3-step recursive DCA at -3% from avg price
# - Fully compatible with Freqtrade 2025.10 wallet API
# ================================================================

from freqtrade.strategy import IStrategy
from pandas import DataFrame
import pandas as pd
import numpy as np
import talib.abstract as ta
import logging


class SekkaStrat(IStrategy):
    timeframe = "1m"
    informative_timeframes = []
    process_only_new_candles = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_buying_expiry = True
    position_adjustment_enable = True  # ✅ Ensure DCA works

    startup_candle_count = 60

    # ------------------ Parameters ------------------
    VWAP_GAP = -0.015
    RSI_THRESHOLD = 35
    TP_THRESHOLD = 0.04
    RSI_TP = 70
    DCA_THRESHOLD = 0.03
    DCA_STEP = 4
    RSI_PERIOD = 14
    VWAP_WINDOW = 14

    minimal_roi = {}
    stoploss = -0.99
    max_entry_position_adjustment = DCA_STEP

    logger = logging.getLogger(__name__)
    _last_dca_stage = None

    # ------------------ Plot Config ------------------
    plot_config = {
        "main_plot": {
            "vwap_1m": {"color": "orange"},
            "ema_fast": {"color": "yellow"},
            "ema_slow": {"color": "blue"},
        },
        "subplots": {
            "RSI": {
                "rsi_1m": {"color": "red"},
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
        # Single timeframe (1m) only - no multi-timeframe dependencies
        df["rsi_1m"] = ta.RSI(df, timeperiod=self.RSI_PERIOD)
        df["vwap_1m"] = self.compute_vwap(df, self.VWAP_WINDOW)
        df["vwap_gap_1m"] = np.where(df["vwap_1m"] > 0, (df["close"] / df["vwap_1m"]) - 1.0, 0.0)
        # EMAs
        df["ema_fast"] = ta.EMA(df, timeperiod=6)
        df["ema_slow"] = ta.EMA(df, timeperiod=24)

        # MACD
        macd = ta.MACD(df)
        df["macd"] = macd["macd"]
        df["macdsignal"] = macd["macdsignal"]
        df["macdhist"] = macd["macdhist"]
        return df

    # Freqtrade 2025.10+ requires populate_entry_trend/populate_exit_trend
    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["enter_long"] = 0
        df.loc[
            (df["rsi_1m"] <= self.RSI_THRESHOLD) 
            & (df["vwap_gap_1m"] < self.VWAP_GAP),
            #& (df["ema_fast"] > df["ema_slow"]) 
            # EMA cross upward
            #& (df["macdhist"] > 0) 
            # Histogram positive
            # (df["macd"] > df["macdsignal"]),
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
        self.logger.info(f"[{current_time}] {trade.pair} | DCA check stage={trade.nr_of_successful_entries}")
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

            self.logger.info(
                f"[{current_time}] {trade.pair} | Triggering {tag} at {current_rate:.4f} "
                f"({drop_ratio*100:.2f}%) | Free={free_balance:.2f} Stake={est_stake:.2f}"
            )
            trade.enter_tag = tag
            return est_stake  # ✅ FIXED: execute with actual stake

        return 0

    # ------------------ Exit Logic ------------------
    def custom_exit(self, pair: str, trade, current_time, current_rate, **kwargs):
        avg_price = trade.open_rate
        dca_stage = trade.nr_of_successful_entries
        rel = (current_rate / avg_price) - 1.0

        #if rel >= self.TP_THRESHOLD:
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            rsi_1m = df.iloc[-1]["rsi_1m"]
        except Exception:
            rsi_1m = 50
            
        if rel >= self.TP_THRESHOLD and rsi_1m >= self.RSI_TP: 
            self.logger.info(f"[{current_time}] {pair} | TAKE_PROFIT reached +{rel*100:.2f}%")
            self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
            return "TAKE_PROFIT"

        # DISABLED CUT LOSS
        # Stop loss after all DCAs are used
        #if dca_stage >= (self.DCA_STEP + 1) and rel <= -self.DCA_THRESHOLD:
        #    self.logger.info(f"[{current_time}] {pair} | STOP_LOSS_AFTER_DCA triggered {rel*100:.2f}%")
        #    self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
        #    return "STOP_LOSS_AFTER_DCA"

        return None