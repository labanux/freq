# ================================================================
# OptHour Strategy - Hyperopt Optimized Version of SekkaHour
# Hybrid Spot/Futures + Shorting Support
# ================================================================

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from pandas import DataFrame
import pandas as pd
import numpy as np
import talib.abstract as ta
import logging

class OptHour(IStrategy):
    timeframe = "1h"
    informative_timeframes = []
    process_only_new_candles = True
    can_short = True 

    use_exit_signal = True
    exit_profit_only = False
    ignore_buying_expiry = True
    position_adjustment_enable = True

    startup_candle_count = 300

    # ------------------ Hyperopt Parameters ------------------
    
    # LONG Parameters
    TP_THRESHOLD = DecimalParameter(0.01, 0.10, default=0.04, decimals=2, space="sell", optimize=True)
    DCA_THRESHOLD = DecimalParameter(0.01, 0.10, default=0.01, decimals=2, space="buy", optimize=True)
    DCA_STEP = IntParameter(1, 10, default=5, space="buy", optimize=True)
    
    VWAP_GAP = DecimalParameter(-0.10, -0.01, default=-0.03, decimals=2, space="buy", optimize=True)
    RSI_THRESHOLD = IntParameter(20, 60, default=48, space="buy", optimize=True)
    RSI_TP = IntParameter(60, 90, default=72, space="sell", optimize=True)

    # SHORT Parameters
    TP_THRESHOLD_SHORT = DecimalParameter(0.01, 0.10, default=0.04, decimals=2, space="sell", optimize=True)
    DCA_THRESHOLD_SHORT = DecimalParameter(0.01, 0.10, default=0.02, decimals=2, space="sell", optimize=True) # Space sell usually for Short? Or buy? Freqtrade treats parameters just as values.
    # Note: 'space' usually groups params. 'buy' params are used for entry/buy signal generation. 'sell' for exit. 
    # But Freqtrade Hyperopt spaces are [buy, sell, roi, stoploss, trailing, protection]. 
    # Ideally we put Entry params in 'buy' and Exit/DCA in 'sell' or 'trailing'? 
    # Actually, DCA params are structure/risk management. Often put in 'buy' or 'trailing'. 
    # I'll put Entry params in 'buy' and TP in 'sell'. DCA in 'buy' (entry management).
    
    DCA_STEP_SHORT = IntParameter(1, 10, default=4, space="buy", optimize=True)
    
    VWAP_GAP_SHORT = DecimalParameter(0.01, 0.10, default=0.03, decimals=2, space="buy", optimize=True)
    RSI_THRESHOLD_SHORT = IntParameter(50, 90, default=67, space="buy", optimize=True)
    RSI_TP_SHORT = IntParameter(10, 50, default=30, space="sell", optimize=True)

    # Fixed Constants
    RSI_PERIOD = 14
    VWAP_WINDOW = 14

    minimal_roi = {}
    stoploss = -0.99
    max_entry_position_adjustment = -1

    logger = logging.getLogger(__name__)
    _last_dca_stage = None

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
        pair = metadata['pair']
        spot_pair = pair.split(':')[0] if ":" in pair else pair

        try:
            spot_df = self.dp.get_pair_dataframe(pair=spot_pair, timeframe=self.timeframe, candle_type='spot')
        except Exception as e:
            # self.logger.warning(f"Could not load spot data for {spot_pair}, using main data.")
            spot_df = df.copy()

        # Calculate Indicators on SPOT data
        # Check if empty
        if spot_df.empty:
            spot_df = df.copy()

        spot_df["rsi_1h_spot"] = ta.RSI(spot_df, timeperiod=self.RSI_PERIOD)
        spot_df["vwap_1h_spot"] = self.compute_vwap(spot_df, self.VWAP_WINDOW)
        # Avoid div by zero
        spot_df["vwap_gap_1h_spot"] = np.where(spot_df["vwap_1h_spot"] > 0, (spot_df["close"] / spot_df["vwap_1h_spot"]) - 1.0, 0.0)

        # Rename for merging
        spot_df_renamed = spot_df[["date", "rsi_1h_spot", "vwap_1h_spot", "vwap_gap_1h_spot", "open", "close"]].copy()
        spot_df_renamed = spot_df_renamed.rename(columns={"open": "open_spot", "close": "close_spot"})
        
        # Merge
        df = pd.merge(df, spot_df_renamed, on="date", how="left")
        df = df.ffill()

        return df

    # ------------------ Entry Trend ------------------
    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["enter_long"] = 0
        df["enter_short"] = 0 

        # Long Logic
        df.loc[
            (df["rsi_1h_spot"] <= self.RSI_THRESHOLD.value) 
            & (df["vwap_gap_1h_spot"] < self.VWAP_GAP.value)
            #& (df['open_spot'].shift(1) > df['close_spot'].shift(2))
            #& (df['open_spot'].shift(2) > df['close_spot'].shift(3)),
            ,
            "enter_long",
        ] = 1
        
        # Short Logic
        df.loc[
            (df["rsi_1h_spot"] >= self.RSI_THRESHOLD_SHORT.value) 
            & (df["vwap_gap_1h_spot"] > self.VWAP_GAP_SHORT.value)
            #& (df['open_spot'].shift(1) < df['close_spot'].shift(2))
            #& (df['open_spot'].shift(2) < df['close_spot'].shift(3)),
            ,
            "enter_short",
        ] = 1
        
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["exit_long"] = 0
        df["exit_short"] = 0
        return df

    # ------------------ Custom Stake ------------------
    def custom_stake_amount(self, pair: str, current_time: pd.Timestamp, current_rate: float, **kwargs) -> float:
        total_balance = self.wallets.get_total_stake_amount()
        max_trades = self.config.get('max_open_trades', 1)
        if max_trades == -1:
            max_trades = 7
        
        pair_allocation = total_balance / max_trades

        trade = kwargs.get("trade", None)
        stage = trade.nr_of_successful_entries if trade else 0
        
        # Determine Steps
        total_steps = self.DCA_STEP.value 
        if trade:
            if trade.is_short:
                total_steps = self.DCA_STEP_SHORT.value
            else:
                total_steps = self.DCA_STEP.value

        if stage == 0:
            stake = pair_allocation / total_steps
        else:
            current_invested = trade.stake_amount
            remaining_for_pair = max(pair_allocation - current_invested, 0)
            
            remaining_steps = total_steps - stage
            if remaining_steps > 0:
                stake = remaining_for_pair / remaining_steps
            else:
                stake = 0

        free_balance = self.wallets.get_available_stake_amount()
        return float(max(min(stake, free_balance), 0.0))

    # ------------------ DCA Logic ------------------
    def adjust_trade_position(self, trade, current_time, current_rate, current_profit, **kwargs):
        if self._last_dca_stage is None:
            self._last_dca_stage = {}

        trade_id = getattr(trade, "id", None) or f"{trade.pair}_{getattr(trade, 'open_date', None)}"
        current_stage = trade.nr_of_successful_entries
        recorded = self._last_dca_stage.get(trade_id)

        if recorded is not None and recorded == current_stage:
            return 0
        
        # Max Steps
        max_steps = self.DCA_STEP_SHORT.value if trade.is_short else self.DCA_STEP.value
        
        if current_stage >= (max_steps + 1):
            return 0

        avg_rate = trade.open_rate
        
        # Threshold
        dca_thresh = self.DCA_THRESHOLD_SHORT.value if trade.is_short else self.DCA_THRESHOLD.value
        
        # Calculate deviation
        if trade.is_short:
             # Short: DCA if Price > Average (Price UP)
             current_deviation = (current_rate / avg_rate) - 1.0 
             trigger = (current_deviation >= dca_thresh)
        else:
             # Long: DCA if Price < Average (Price DOWN)
             current_deviation = (current_rate / avg_rate) - 1.0 
             trigger = (current_deviation <= -dca_thresh)

        free_balance = self.wallets.get_available_stake_amount()
        est_stake = self.custom_stake_amount(trade.pair, current_time, current_rate, trade=trade)

        if trigger and free_balance >= est_stake:
            next_stage = current_stage + 1
            tag = f"DCA_{next_stage}"
            self._last_dca_stage[trade_id] = current_stage
            
            # self.logger.info(f"Triggering DCA {tag} for {trade.pair} ({trade.trade_direction})")
            
            trade.enter_tag = tag
            return est_stake

        return 0

    # ------------------ Exit Logic ------------------
    def custom_exit(self, pair: str, trade, current_time, current_rate, **kwargs):
        avg_price = trade.open_rate
        
        # Relative Profit
        if trade.is_short:
             rel = (avg_price - current_rate) / avg_price
        else:
             rel = (current_rate / avg_price) - 1.0

        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            rsi_val = df.iloc[-1]["rsi_1h_spot"]
        except Exception:
            rsi_val = 50
        
        # Exit Check
        if trade.is_short:
             if rel >= self.TP_THRESHOLD_SHORT.value and rsi_val <= self.RSI_TP_SHORT.value:
                self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
                return "TAKE_PROFIT"
        else:
             if rel >= self.TP_THRESHOLD.value and rsi_val >= self.RSI_TP.value: 
                 self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
                 return "TAKE_PROFIT"

        return None