# ================================================================
# SekkaAi - FreqAI Enabled Version
# ---------------------------------------------------------------
# - Uses FreqAI for entry signals
# - Uses Sekka's original DCA logic for position management
# - Uses Sekka's original Exit logic
# ================================================================

from freqtrade.strategy import IStrategy
from pandas import DataFrame
import pandas as pd
import numpy as np
import talib.abstract as ta
import logging

class SekkaAi(IStrategy):
    timeframe = "1m"
    informative_timeframes = ["30m", "1h"]
    process_only_new_candles = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_buying_expiry = True
    position_adjustment_enable = True

    startup_candle_count = 300

    TP_THRESHOLD = 0.04
    DCA_STEP = 0.03
    RSI_PERIOD = 14
    VWAP_WINDOW = 14

    minimal_roi = {}
    stoploss = -0.99
    max_entry_position_adjustment = 3

    logger = logging.getLogger(__name__)
    _last_dca_stage = None

    # ------------------ Helper Methods ------------------
    def hlc3(self, df: DataFrame) -> pd.Series:
        return (df["high"] + df["low"] + df["close"]) / 3.0

    def compute_vwap(self, df: DataFrame, window: int) -> pd.Series:
        hlc3 = self.hlc3(df)
        pv = hlc3 * df["volume"]
        pv_sum = pv.rolling(window, min_periods=1).sum()
        vol_sum = df["volume"].rolling(window, min_periods=1).sum()
        vwap = (pv_sum / vol_sum.replace(0, np.nan)).ffill().fillna(df["close"])
        return vwap

    # ------------------ FreqAI Mandatory Methods ------------------

    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int, metadata: dict, **kwargs):
        """
        Use this to create features that will be expanded by the user_data/config.json
        'indicator_periods_candles' setting.
        """
        dataframe["%rsi"] = ta.RSI(dataframe, timeperiod=self.RSI_PERIOD)
        return dataframe

    def feature_engineering_expand_basic(self, dataframe: DataFrame, metadata: dict, **kwargs):
        """
        Use this to create features that will NOT be expanded by the user_data/config.json
        'indicator_periods_candles' setting.
        """
        dataframe["%pct-change"] = dataframe["close"].pct_change()
        dataframe["%vwap"] = self.compute_vwap(dataframe, self.VWAP_WINDOW)
        dataframe["%vwap_gap"] = np.where(dataframe["%vwap"] > 0, (dataframe["close"] / dataframe["%vwap"]) - 1.0, 0.0)
        return dataframe

    def feature_engineering_standard(self, dataframe: DataFrame, metadata: dict, **kwargs):
        """
        This is optional, but often used for features that don't fit into the expand categories.
        Here we just ensure the RSI is available for the custom_exit logic if needed.
        """
        dataframe["rsi_1m"] = ta.RSI(dataframe, timeperiod=self.RSI_PERIOD)
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs):
        """
        Define the target for the model to predict.
        Example: Predict if the close price 20 candles from now is higher than current close.
        """
        # 'up' if price increases, 'down' otherwise
        dataframe["&s-up_or_down"] = np.where(dataframe["close"].shift(-20) > dataframe["close"], "up", "down")
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Initialize FreqAI - this will call the feature_engineering_* methods above
        dataframe = self.freqai.start(dataframe, metadata, self)
        
        # Ensure indicators needed for DCA/Exit logic are present (if not added by FreqAI)
        # We added rsi_1m in feature_engineering_standard, so it should be there.
        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["buy"] = 0
        
        # FreqAI Entry Logic
        # 1. do_predict must be 1 (prediction available)
        # 2. Prediction must be 'up' (assuming Classifier)
        # 3. Optional: Check probability/confidence if available
        
        conditions = [
            dataframe["do_predict"] == 1,
            dataframe["&s-up_or_down"] == "up"
        ]
        
        if conditions:
            dataframe.loc[
                pd.concat(conditions, axis=1).all(axis=1),
                "buy"
            ] = 1
            
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sell"] = 0
        return dataframe

    # ------------------ Custom Stake & DCA (Unchanged) ------------------
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
        next_dca_trigger = -self.DCA_STEP

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

    # ------------------ Exit Logic (Unchanged) ------------------
    def custom_exit(self, pair: str, trade, current_time, current_rate, **kwargs):
        avg_price = trade.open_rate
        dca_stage = trade.nr_of_successful_entries
        rel = (current_rate / avg_price) - 1.0

        try:
            # We need to access the dataframe to get RSI
            # Note: get_analyzed_dataframe might return the dataframe with FreqAI columns
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            rsi_1m = df.iloc[-1]["rsi_1m"]
        except Exception:
            rsi_1m = 50
            
        if rel >= self.TP_THRESHOLD and rsi_1m >= 70: 
            self.logger.info(f"[{current_time}] {pair} | TAKE_PROFIT reached +{rel*100:.2f}%")
            self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
            return "TAKE_PROFIT"

        if dca_stage >= 4 and rel <= -self.DCA_STEP:
            self.logger.info(f"[{current_time}] {pair} | STOP_LOSS_AFTER_DCA triggered {rel*100:.2f}%")
            self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
            return "STOP_LOSS_AFTER_DCA"

        return None