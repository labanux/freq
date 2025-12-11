
from freqtrade.optimize.hyperopt import IHyperOptLoss
from pandas import DataFrame
import numpy as np

class ZeroLossMaxTrades(IHyperOptLoss):
    """
    Custom Loss function:
    1. Zero Loss (100% Win Rate) is mandatory. Penalize heavily if any loss.
    2. Min 2% Average Profit required.
    3. Maximize Trade Count.
    """

    def calculate_loss(self, results: DataFrame, trade_count: int,
                       min_date, max_date,
                       *args, **kwargs) -> float:
        
        if trade_count == 0:
            return 1000.0  # High penalty for no trades

        # 1. Check for Losses
        # results['profit_ratio'] contains the profit percentage (0.01 = 1%)
        losing_trades = results[results['profit_ratio'] < 0]
        loss_count = len(losing_trades)

        if loss_count > 0:
            # We have losses. Return a HIGH positive number to reject this.
            # 100 base + 10 per losing trade + total loss percentage
            return 100.0 + (loss_count * 10.0) - losing_trades['profit_ratio'].sum()

        # 2. Check Min Profit (2%)
        avg_profit = results['profit_ratio'].mean()
        if avg_profit < 0.015:
            # Penalize if below 2%
            # 50 base + penalty proportional to gap
            return 50.0 + (0.02 - avg_profit) * 1000.0

        # 3. Maximize Trades
        # If we are here: 0 Losses, >2% Profit.
        # We want more trades to lower the loss score.
        # Loss = -1 * trade_count (e.g., 50 trades = -50 score)
        return -1.0 * trade_count

    def hyperopt_loss_function(self, results: DataFrame, trade_count: int,
                               min_date, max_date,
                               *args, **kwargs) -> float:
        """
        Required by IHyperOptLoss interface.
        """
        return self.calculate_loss(results, trade_count, min_date, max_date, *args, **kwargs)
