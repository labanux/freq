# Use the official image as base
FROM freqtradeorg/freqtrade:stable_plot

# Switch to root to handle file permissions
USER root

# 1. Copy Strategies
##COPY --chown=ftuser:ftuser user_data/strategies /freqtrade/user_data/strategies

# 2. Copy Hyperopt definitions (Important if using custom loss functions)
#COPY --chown=ftuser:ftuser user_data/hyperopts /freqtrade/user_data/hyperopts

# 3. Copy FreqAI models (Important if using FreqAI)
#COPY --chown=ftuser:ftuser user_data/freqaimodels /freqtrade/user_data/freqaimodels

# 4. Copy Configurations
#COPY --chown=ftuser:ftuser user_data/*.json /freqtrade/user_data/

#COPY --chown=ftuser:ftuser readme.txt .

#COPY --chown=ftuser:ftuser Dockerfile .

# 5. Copy Historical Data (BinanceUS)
# Ensure the destination directory exists to avoid copy errors
#RUN mkdir -p /freqtrade/user_data/data/binance
#COPY --chown=ftuser:ftuser user_data/data/binance /freqtrade/user_data/data/binance

# Switch back to the standard user
USER ftuser

# Set working directory
# WORKDIR /freqtrade
