# Findings

**Data source:** `https://arb1.arbitrum.io/rpc` (free public endpoint).

The live snapshot covers a 100,000-block Arbitrum window and contains **937 Uniswap V3 Swap events**: 915 from the 0.05% WETH/USDC pool and 22 from the 0.30% pool. Comparing the latest observed price at each aligned block produced **378 observations above the 10 bps cross-pool threshold**.

- **0.05% fee tier:** 915 swaps, about **$2.21m** notional. Five events met the sample's large-notional and price-shock thresholds; one reverted at least 50% toward its pre-swap price within the next ten swaps, a 20% sample reversion rate.
- **0.30% fee tier:** 22 swaps, about **$14.0k** notional. One event met the large-shock threshold and did not show a qualifying reversion within ten subsequent swaps.

The earlier 20,000-block smoke test returned zero 0.30% events because that pool is much less active. Expanding the lookback recovered events without changing the pool discovery or event filter.

## Why this data is useful

A Uniswap V3 Swap event contains the signed token amounts and the pool's post-trade square-root price. That makes it possible to measure a price move directly from public chain data, without relying on a third-party indexer. A large move followed by a quick move back is a simple, auditable proxy for temporary dislocation and possible backrun or arbitrage activity.

## Potential application and limits

This output can seed an alerting or research system: flag unusually large swaps, compare the next few pool prices, and prioritize events for deeper MEV analysis. It is not proof that a transaction was profitable arbitrage. A production detector would add longer history, router-path decoding, transaction ordering, gas costs, liquidity/depth modelling, and more historical coverage.

## Reproduction

```bash
python main.py --demo
python main.py --lookback-blocks 100000 --chunk-size 5000
```
