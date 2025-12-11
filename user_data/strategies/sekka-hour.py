# ================================================================
# SekkaStrat v14n – Hybrid Spot/Futures
# ---------------------------------------------------------------
# - Uses Spot data for indicators
# - Trades on Futures (Long & Short enabled)
# - DCA enabled
# ================================================================

from freqtrade.strategy import IStrategy
from pandas import DataFrame
import pandas as pd
import numpy as np
import talib.abstract as ta
import logging

class SekkaHour(IStrategy):
    timeframe = "1h"
    informative_timeframes = []
    process_only_new_candles = True
    
    # 1. Enable Shorting
    can_short = True 

    use_exit_signal = True
    exit_profit_only = False
    ignore_buying_expiry = True
    position_adjustment_enable = True

    startup_candle_count = 300

    # LONG PARAMETERS
    TP_THRESHOLD = 0.01
    DCA_THRESHOLD = 0.04
    DCA_STEP = 10
    RSI_PERIOD = 14
    VWAP_WINDOW = 14

    VWAP_GAP = -0.01
    RSI_THRESHOLD = 53
    RSI_TP = 61

    # SHORT PARAMETERS
    TP_THRESHOLD_SHORT = 0.01
    DCA_THRESHOLD_SHORT = 0.08
    DCA_STEP_SHORT = 6
    RSI_PERIOD_SHORT = 14
    VWAP_WINDOW_SHORT = 14

    VWAP_GAP_SHORT = 0.03
    RSI_THRESHOLD_SHORT = 75
    RSI_TP_SHORT = 36
    
    minimal_roi = {}
    stoploss = -0.99

    logger = logging.getLogger(__name__)
    _last_dca_stage = None

    # ------------------ Plot Config ------------------
    plot_config = {
        "main_plot": {
            "vwap_1h_spot": {"color": "orange"},
        },
        "subplots": {
            "RSI": {
                "rsi_1h_spot": {"color": "red"},
            },
        },
    }

    # ------------------ Informative Pairs ------------------
    def informative_pairs(self):
        # We need to load the Spot version of the current pair
        # For backtesting, we must define which pairs we want. 
        # Since we don't know the exact pair at this stage dynamically for all exchanges in this definition method easily 
        # (unless we use the whitelist), we usually rely on 'populate_indicators' creating it or defining it here strictly.
        # But properly, we return a list of tuples (pair, timeframe).
        
        # However, to be dynamic, we iterate over current pairlist if available, or just rely on DP to split it?
        # Standard way: return [] and do it inside populate_indicators using `dp.get_pair_dataframe`?
        # NO, backtesting needs `informative_pairs` to pre-load data.
        
        # Assumption: Input pair is 'BTC/USDT:USDT' (Futures). We want 'BTC/USDT' (Spot).
        pairs = self.dp.current_whitelist()
        informative_pairs = []
        for pair in pairs:
            # Simple logic to strip :USDT suffix or check exchange naming
            # For 'BTC/USDT:USDT', split by ':' -> 'BTC/USDT'
            spot_pair = pair.split(':')[0] 
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
        # 1. Get spot pair name
        pair = metadata['pair']
        spot_pair = pair.split(':')[0] # 'BTC/USDT:USDT' -> 'BTC/USDT'

        # 2. Get Spot Dataframe
        try:
            spot_df = self.dp.get_pair_dataframe(pair=spot_pair, timeframe=self.timeframe, candle_type='spot')
        except Exception as e:
            # Fallback if spot data missing (shouldn't happen if downloaded)
            self.logger.warning(f"Could not load spot data for {spot_pair}, using futures data. Error: {e}")
            spot_df = df.copy()

        # 3. Calculate Indicators on SPOT data
        # We name them _spot to distinguish
        spot_df["rsi_1h_spot"] = ta.RSI(spot_df, timeperiod=self.RSI_PERIOD)
        spot_df["vwap_1h_spot"] = self.compute_vwap(spot_df, self.VWAP_WINDOW)
        spot_df["vwap_gap_1h_spot"] = np.where(spot_df["vwap_1h_spot"] > 0, (spot_df["close"] / spot_df["vwap_1h_spot"]) - 1.0, 0.0)

        # 4. Merge Spot indicators into Futures DataFrame
        # We use explicit columns to avoid overwriting if names collided
        # We assume timestamps align (same timeframe). Freqtrade handles alignment if using merge_informative_pair,
        # but here manual assignment works if indexes match. Safer to use merge.
        
        # Rename columns to avoid collision before merge
        spot_df_renamed = spot_df[["date", "rsi_1h_spot", "vwap_1h_spot", "vwap_gap_1h_spot", "open", "close"]].copy()
        # Rename open/close for the pattern logic if needed (e.g. open_spot, close_spot)
        spot_df_renamed = spot_df_renamed.rename(columns={"open": "open_spot", "close": "close_spot"})
        
        # Merge on date
        df = pd.merge(df, spot_df_renamed, on="date", how="left")
        
        # Fill NaNs if any alignment issues (forward fill)
        df = df.ffill()

        return df

    # ------------------ Entry Trend ------------------
    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["enter_long"] = 0
        df["enter_short"] = 0 # Initialize short column

        # Long Logic (using SPOT indicators)
        df.loc[
            (df["rsi_1h_spot"] <= self.RSI_THRESHOLD) 
            & (df["vwap_gap_1h_spot"] < self.VWAP_GAP),
            # Pattern check on SPOT candles
            #& (df['open_spot'].shift(1) > df['close_spot'].shift(2))
            #& (df['open_spot'].shift(2) > df['close_spot'].shift(3)),
            "enter_long",
        ] = 1
        
        # Short Logic (Generic Placeholder for now - User to define)
        # For now, we leave it empty (0) or add a dummy logic if requested
        # df.loc[..., "enter_short"] = 1
        df.loc[
            (df["rsi_1h_spot"] >= self.RSI_THRESHOLD_SHORT) 
            & (df["vwap_gap_1h_spot"] > self.VWAP_GAP_SHORT),
            # Pattern check on SPOT candles
            #& (df['open_spot'].shift(1) < df['close_spot'].shift(2))
            #& (df['open_spot'].shift(2) < df['close_spot'].shift(3)),
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
        total_steps = self.DCA_STEP
        if trade:
            if trade.is_short:
                total_steps = self.DCA_STEP_SHORT
            else:
                total_steps = self.DCA_STEP

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
        self.logger.info(f"[{current_time}] {trade.pair} | DCA check stage={trade.nr_of_successful_entries}")
        if self._last_dca_stage is None:
            self._last_dca_stage = {}

        trade_id = getattr(trade, "id", None) or f"{trade.pair}_{getattr(trade, 'open_date', None)}"
        current_stage = trade.nr_of_successful_entries
        recorded = self._last_dca_stage.get(trade_id)

        if recorded is not None and recorded == current_stage:
            return 0
        
        # Select Max Steps based on direction
        max_steps = self.DCA_STEP_SHORT if trade.is_short else self.DCA_STEP
        
        if current_stage >= (max_steps + 1):
            return 0

        avg_rate = trade.open_rate
        
        # Select Threshold based on direction
        dca_thresh = self.DCA_THRESHOLD_SHORT if trade.is_short else self.DCA_THRESHOLD
        
        # Calculate deviation from average entry
        if trade.is_short:
             # Short: We DCA if price GOES UP (current > avg)
             current_deviation = (current_rate / avg_rate) - 1.0 
             trigger = (current_deviation >= dca_thresh)
        else:
             # Long: We DCA if price GOES DOWN (current < avg)
             current_deviation = (current_rate / avg_rate) - 1.0 
             trigger = (current_deviation <= -dca_thresh)

        free_balance = self.wallets.get_available_stake_amount()
        est_stake = self.custom_stake_amount(trade.pair, current_time, current_rate, trade=trade)

        if trigger and free_balance >= est_stake:
            next_stage = current_stage + 1
            tag = f"DCA_{next_stage}"
            self._last_dca_stage[trade_id] = current_stage
            
            # Log
            self.logger.info(f"Triggering DCA {tag} for {trade.pair} ({trade.trade_direction})")
            
            trade.enter_tag = tag
            return est_stake

        return 0

    # ------------------ Exit Logic ------------------
    def custom_exit(self, pair: str, trade, current_time, current_rate, **kwargs):
        # We need to check RSI spot for TP
        dca_stage = trade.nr_of_successful_entries
        
        # Calculate profit logic manually or use passed current_profit? 
        # Using simple relative calculation matches original logic better
        avg_price = trade.open_rate
        
        # Relative movement (Profit/Loss raw)
        # Long: (Curr - Avg) / Avg
        # Short: (Avg - Curr) / Avg
        if trade.is_short:
             rel = (avg_price - current_rate) / avg_price
        else:
             rel = (current_rate / avg_price) - 1.0

        try:
            # We must use SPOT RSI for exit condition too, as per request
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            rsi_val = df.iloc[-1]["rsi_1h_spot"]
        except Exception:
            rsi_val = 50
        
        # TP Logic
        # For Long: RSI > High Level (Overbought)
        # For Short: RSI < Low Level (Oversold) ??
        # Original code: if rel >= TP and RSI >= RSI_TP
        
        # We adapt for Short:
        if trade.is_short:
             # Short Take Profit: Profit reached AND RSI is LOW (Oversold) ??
             # Usually for short TP you want RSI to be low?
             # Or do we mirror the logic?
             # Let's assume standard RSI logic: Short Entry High RSI -> Exit Low RSI.
             # But the user only specified "Use spot data".
             # I will implement symmetric logic:
             # Exit Short if Profit > TP AND RSI < (100 - RSI_TP) ??
             # For now, I'll restrict TP logic using RSI to Longs only unless specified. 
             # Actually, basic TP is handled by config minimal_roi usually, but here it's custom.
             
             # Placeholder for Short TP Custom: Just use ROI for now or symmetric
             if rel >= self.TP_THRESHOLD_SHORT and rsi_val <= self.RSI_TP_SHORT:
                self.logger.info(f"[{current_time}] {pair} | TAKE_PROFIT reached +{rel*100:.2f}%")
                self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
                return "TAKE_PROFIT"
        else:
             # Long
             if rel >= self.TP_THRESHOLD and rsi_val >= self.RSI_TP: 
                 self.logger.info(f"[{current_time}] {pair} | TAKE_PROFIT reached +{rel*100:.2f}%")
                 self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
                 return "TAKE_PROFIT"

        return None