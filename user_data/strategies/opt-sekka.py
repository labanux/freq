# ================================================================
# SekkaStrat v14n – Hyperopt Version
# ---------------------------------------------------------------
# Optimized for Freqtrade Hyperopt
# ================================================================

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from pandas import DataFrame
import pandas as pd
import numpy as np
import talib.abstract as ta
import logging


class OpSekka(IStrategy):
    timeframe = "1m"
    informative_timeframes = ["30m", "1h"]
    process_only_new_candles = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_buying_expiry = True
    position_adjustment_enable = True

    startup_candle_count = 100

    # ------------------ Hyperopt Parameters ------------------
    # Buy Hyperspace
    buy_rsi_period = IntParameter(10, 40, default=14, space="buy")
    buy_vwap_window = IntParameter(10, 100, default=14, space="buy")
    buy_rsi_threshold = IntParameter(20, 50, default=35, space="buy")
    buy_vwap_gap = DecimalParameter(-0.05, -0.005, default=-0.015, space="buy")

    # Sell/Exit Hyperspace
    # Note: DCA Step and TP are often better as fixed logic, but we can optimize them too
    # We use 'protection' space or just class attributes if we want to optimize them via hyperopt
    # Freqtrade hyperopt mainly targets buy/sell signals. 
    # To optimize TP/DCA, we treat them as parameters used in custom_exit/adjust_trade_position
    
    tp_threshold = DecimalParameter(0.01, 0.10, default=0.04, space="sell")
    dca_step = DecimalParameter(0.01, 0.06, default=0.03, space="sell")
    
    # RSI Exit Threshold
    exit_rsi_threshold = IntParameter(50, 90, default=70, space="sell")

    minimal_roi = {}
    stoploss = -0.99
    max_entry_position_adjustment = 3

    logger = logging.getLogger(__name__)
    _last_dca_stage = None

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
        # We need to calculate indicators for ALL potential parameter values during hyperopt
        # OR we calculate a range of them. 
        # Since rolling windows change, we might need to calculate the MAX window
        # and then slice dynamically, OR just calculate multiple columns.
        # For efficiency in hyperopt, it's often better to calculate a few variations 
        # or use the .value property inside populate_buy_trend if possible (but that's slow).
        
        # OPTIMIZATION STRATEGY:
        # Calculate the indicators with the CURRENT parameter values.
        # Freqtrade re-runs populate_indicators for each epoch if parameters affect indicators.
        
        # However, Freqtrade optimizes 'buy' parameters by reloading indicators.
        # Let's use the .value accessor.
        
        # For RSI, we can just calculate a few common ones or rely on the parameter.
        # But wait! populate_indicators runs ONCE per epoch.
        # So we can use self.buy_rsi_period.value
        
        df["rsi"] = ta.RSI(df, timeperiod=self.buy_rsi_period.value)
        
        # Custom VWAP with dynamic window
        df["vwap"] = self.compute_vwap(df, self.buy_vwap_window.value)
        df["vwap_gap"] = np.where(df["vwap"] > 0, (df["close"] / df["vwap"]) - 1.0, 0.0)

        return df.ffill()

    def populate_buy_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["buy"] = 0
        df.loc[
            (df["rsi"] <= self.buy_rsi_threshold.value) & 
            (df["vwap_gap"] <= self.buy_vwap_gap.value),
            "buy",
        ] = 1
        return df

    def populate_sell_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["sell"] = 0
        return df

    # ------------------ Custom Stake ------------------
    def custom_stake_amount(self, pair: str, current_time: pd.Timestamp, current_rate: float, **kwargs) -> float:
        balance = self.wallets.get_total_stake_amount()
        free = self.wallets.get_available_stake_amount()
        used = max(balance - free, 0)
        remaining = max(balance - used, 0)

        trade = kwargs.get("trade", None)
        stage = trade.nr_of_successful_entries if trade else 0

        if stage == 0:
            stake = balance * 0.25
        elif stage == 1:
            stake = remaining / 3
        elif stage == 2:
            stake = remaining / 2
        else:
            stake = remaining

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
        if current_stage >= 4:
            return 0

        avg_rate = trade.open_rate
        drop_ratio = (current_rate / avg_rate) - 1.0
        
        # Use Hyperopt Parameter for DCA Step
        next_dca_trigger = -self.dca_step.value

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
            return est_stake

        return 0

    # ------------------ Exit Logic ------------------
    def custom_exit(self, pair: str, trade, current_time, current_rate, **kwargs):
        avg_price = trade.open_rate
        dca_stage = trade.nr_of_successful_entries
        rel = (current_rate / avg_price) - 1.0

        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            rsi = df.iloc[-1]["rsi"]
        except Exception:
            rsi = 50
            
        # Use Hyperopt Parameters for TP and RSI Exit
        if rel >= self.tp_threshold.value and rsi >= self.exit_rsi_threshold.value: 
            self.logger.info(f"[{current_time}] {pair} | TAKE_PROFIT reached +{rel*100:.2f}%")
            self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
            return "TAKE_PROFIT"

        # Use Hyperopt Parameter for Stop Loss after DCA
        if dca_stage >= 4 and rel <= -self.dca_step.value:
            self.logger.info(f"[{current_time}] {pair} | STOP_LOSS_AFTER_DCA triggered {rel*100:.2f}%")
            self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
            return "STOP_LOSS_AFTER_DCA"

        return None