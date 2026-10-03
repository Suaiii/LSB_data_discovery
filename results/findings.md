# Findings

**Data source:** `https://arb1.arbitrum.io/rpc` (free public endpoint).

The live snapshot covers a 20,000-block Arbitrum window and contains **127 Uniswap V3 Swap events**. All 127 came from the 0.05% WETH/USDC pool; the 0.30% pool had no Swap events in this window. The sample therefore produced **zero cross-pool signals** and should be treated as a directional smoke test rather than a market-wide estimate.

- **0.05% fee tier:** 127 swaps, about **$296,320** notional. One event met the sample's large-notional and price-shock thresholds, and it reverted at least 50% toward its pre-swap price within the next ten swaps.
- **0.30% fee tier:** no events observed in this window, so no reversion or cross-pool statistic is reported.

## Why this data is useful

A Uniswap V3 Swap event contains the signed token amounts and the pool's post-trade square-root price. That makes it possible to measure a price move directly from public chain data, without relying on a third-party indexer. A large move followed by a quick move back is a simple, auditable proxy for temporary dislocation and possible backrun or arbitrage activity.

## Potential application and limits

This output can seed an alerting or research system: flag unusually large swaps, compare the next few pool prices, and prioritize events for deeper MEV analysis. It is not proof that a transaction was profitable arbitrage. A production detector would add longer history, router-path decoding, transaction ordering, gas costs, liquidity/depth modelling, and a second active fee tier.

## Reproduction

```bash
python main.py --demo
python main.py --lookback-blocks 20000 --chunk-size 2000
```
