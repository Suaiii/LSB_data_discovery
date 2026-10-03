# Detecting Short-Lived Price Dislocations after Large Uniswap V3 Swaps on Arbitrum

This is a compact blockchain data discovery project for the Linden Shore assessment. It uses a free public Arbitrum RPC to collect Uniswap V3 `Swap` events for WETH/USDC pools, measures large price shocks, checks whether prices revert within the next ten swaps, and compares prices across the 0.05% and 0.30% fee tiers.

The research question is: **when a large swap moves the pool price, how often does the price move back quickly, and when do the two fee tiers temporarily disagree?** This is a practical proxy for short-lived dislocation and possible backrun/arbitrage activity. The output is a signal detector, not proof of profitable arbitrage.

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Offline smoke test (always works and writes example outputs)
python main.py --demo

# Live collection from the free Arbitrum public RPC
python main.py --lookback-blocks 20000 --chunk-size 2000
```

The live command uses `https://arb1.arbitrum.io/rpc` by default and falls back to two public endpoints when needed. It adapts log ranges after provider errors. Set `RPC_URL`, `LOOKBACK_BLOCKS`, or `CHUNK_SIZE` to tune the run. No API key is required.

## Outputs

- `data/swaps.csv`: decoded event-level data with block, transaction, signed token amounts, notional, tick, and post-swap price.
- `results/summary.json`: machine-readable run statistics.
- `results/candidate_reversions.csv`: large swaps followed by at least 50% price reversion within ten later swaps.
- `results/cross_pool_signals.csv`: aligned-block observations with at least 10 bps fee-tier price difference.
- `results/findings.md`: short write-up generated from the run.

## Method

1. Discover pools with the canonical Uniswap V3 factory `getPool(WETH, USDC, fee)` call.
2. Query `Swap` logs in bounded block ranges and decode the event's signed `amount0`, `amount1`, `sqrtPriceX96`, liquidity, and tick fields.
3. Convert the square-root price into USDC per WETH, accounting for token decimals and token ordering.
4. Define a large swap as a notional at or above the sample's 95th percentile and a price shock of at least 2 bps.
5. Search the next ten swaps for a move at least halfway back toward the pre-swap price.
6. Forward-fill the latest observation by block and flag fee-tier differences of at least 10 bps.

Thresholds are deliberately explicit and easy to change. A production strategy would add router decoding, gas costs, transaction ordering, and pool liquidity/depth modelling.

## Assessment fit

The repository contains the full RPC → event log → decoding → CSV → analysis → findings pipeline, plus a deterministic offline mode for reproducibility. It uses only free public infrastructure and keeps the scope small enough to inspect in one sitting.

## Observed live run

The checked-in live snapshot was collected from the public Arbitrum RPC over a 20,000-block window. It contains 127 swaps from the 0.05% pool and no swaps from the 0.30% pool during that window. One of the sample's large price shocks moved at least halfway back toward its pre-swap price within the next ten swaps. Because the window is short and the second fee tier was inactive, these numbers are directional rather than a market-wide estimate; rerun with a larger lookback before drawing a trading conclusion.

The useful takeaway is methodological: pool-level event data is enough to build a transparent first-pass detector for post-swap price recovery, while a stronger arbitrage study would need longer coverage, both fee tiers, router-path decoding, transaction ordering, gas costs, and liquidity-aware profitability checks.
