# ================================================================
# OptPerps – Hyperopt Strategy for Futures (Optimizable Parameters)
# ---------------------------------------------------------------
# Same logic as SekkaPerps, but with optimizable parameters.
# Use this for hyperopt optimization on futures.
# ================================================================

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, CategoricalParameter
from pandas import DataFrame
import pandas as pd
import numpy as np
import talib.abstract as ta
import logging
from datetime import datetime, timedelta
from typing import Optional


class OptPerps(IStrategy):
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
    # OPTIMIZABLE PARAMETERS
    # ==============================================================
    
    # Buy parameters
    DCA_STEP = CategoricalParameter([1, 3, 5], default=5, space="buy", optimize=True)
    DCA_THRESHOLD = CategoricalParameter([0.03, 0.04,0.05, 0.06], default=0.03, space="buy", optimize=True)
    ENTRY_RSI = CategoricalParameter([45, 50, 55, 60, 65], default=40, space="buy", optimize=True)
    ENTRY_VWAP_GAP = DecimalParameter(-0.05, -0.02, default=-0.03, decimals=2, space="buy", optimize=True)
    
    # Sell parameters
    TP_PERCENTAGE = DecimalParameter(0.01, 0.05, default=0.02, decimals=2, space="sell", optimize=True)
    
    # Futures parameters: FALSE
    LEVERAGE = CategoricalParameter([1, 3, 5], default=1, space="buy", optimize=False)
    
    # Fixed parameters
    GENERAL_PERIOD = 14
    COOLDOWN_HOURS = 6  # Hours to wait before re-entering after stop loss

    # ==============================================================

    minimal_roi = {}  # We use custom_exit instead
    stoploss = -0.20

    logger = logging.getLogger(__name__)
    _last_dca_stage = None
    _stoploss_cooldown = {}  # Track pairs in cooldown after STOP_LOSS_AFTER_DCA
    _entry_stake = {}  # Track per-entry stake for each pair (consistent throughout trade cycle)

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
        return float(self.LEVERAGE.value)

    # ------------------ Plot Config ------------------
    plot_config = {
        "main_plot": {
            "vwap_1h": {"color": "orange"}
        }
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
            (df["rsi_1h"] <= self.ENTRY_RSI.value) 
            & (df["vwap_gap_1h"] < self.ENTRY_VWAP_GAP.value),
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
            return False
        
        # Clear expired cooldown
        if cooldown_until and current_time >= cooldown_until:
            self._stoploss_cooldown.pop(pair, None)
        
        return True

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["exit_long"] = 0
        return df

    # ------------------ Clear Stake on Exit ------------------
    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time, **kwargs) -> bool:
        """
        Clear stored per-entry stake when trade exits.
        This frees up the allocation for new trades.
        """
        if pair in self._entry_stake:
            del self._entry_stake[pair]
        return True

    # ------------------ Custom Stake ------------------
    def custom_stake_amount(self, pair: str, current_time: pd.Timestamp, current_rate: float, **kwargs) -> float:
        from freqtrade.persistence import Trade
        
        trade = kwargs.get("trade", None)
        stage = trade.nr_of_successful_entries if trade else 0
        total_entries = self.DCA_STEP.value + 1  # 1 initial + DCA_STEP DCAs
        
        # For DCA entries, use the stored stake from initial entry
        if stage > 0:
            stake = self._entry_stake.get(pair, 0)
            remaining = self.wallets.get_available_stake_amount()
            return float(max(min(stake, remaining), 0.0))
        
        # For initial entry (stage 0), calculate fresh stake
        free = self.wallets.get_available_stake_amount()
        pairs = self.dp.current_whitelist()
        
        # Get all open trades
        try:
            open_trades = Trade.get_trades_proxy(is_open=True)
        except Exception:
            open_trades = []
        
        # Calculate reserved balance for active trades' remaining DCAs
        reserved = 0
        active_pairs = set()
        for t in open_trades:
            active_pairs.add(t.pair)
            if t.pair in self._entry_stake:
                remaining_dcas = total_entries - t.nr_of_successful_entries
                reserved += remaining_dcas * self._entry_stake[t.pair]
        
        # Available for new entries = free - reserved for active DCAs
        available = max(free - reserved, 0)
        
        # Count inactive pairs (no active trade)
        inactive_pairs = [p for p in pairs if p not in active_pairs]
        num_inactive = len(inactive_pairs)
        
        if num_inactive > 0 and available > 0:
            per_pair_budget = available / num_inactive
            stake = per_pair_budget / total_entries
        else:
            stake = 0
        
        # Store this stake for future DCAs in this trade cycle
        if stake > 0:
            self._entry_stake[pair] = stake
        
        remaining = self.wallets.get_available_stake_amount()
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
            trade.enter_tag = tag
            return est_stake

        return 0

    # ------------------ Exit Logic ------------------
    def custom_exit(self, pair: str, trade, current_time, current_rate, **kwargs):
        avg_price = trade.open_rate
        dca_stage = trade.nr_of_successful_entries
        
        # For futures trading, use current_rate directly
        rel = (current_rate / avg_price) - 1.0

        # Take profit based on price percentage
        if rel >= self.TP_PERCENTAGE.value:
            return "TAKE_PROFIT"

        # Stop loss after all DCAs are used
        if dca_stage >= (self.DCA_STEP.value + 1) and rel <= -self.DCA_THRESHOLD.value:
            self._last_dca_stage.pop(f"{pair}_{trade.open_date}", None)
            
            # Set cooldown for this pair
            if self._stoploss_cooldown is None:
                self._stoploss_cooldown = {}
            cooldown_until = current_time + timedelta(hours=self.COOLDOWN_HOURS)
            self._stoploss_cooldown[pair] = cooldown_until
            
            return "STOP_LOSS_AFTER_DCA"

        return None
