# Findings

Data source: `https://arb1.arbitrum.io/rpc`.
The pipeline collected **127 Swap events** across fee tiers `[500]`.

- Fee 0.05%: 127 swaps, $296,320 notional, 100.0% of large price shocks reverted within ten subsequent swaps.

Cross-pool signals are rows where the last observed price in the 0.30% pool differed from the 0.05% pool by at least 10 bps at an aligned block.

## Interpretation
A large swap changes the pool's marginal price. A subsequent move back toward the pre-swap price is a simple, observable proxy for short-lived dislocation and possible backrun/arbitrage activity. This is a signal detector, not proof that a particular transaction was an arbitrage trade: proving that would require decoding router paths, gas ordering, and profitability.

## Reproduction
Run `python main.py --demo` for an offline smoke test, or `python main.py --lookback-blocks 20000` against the free public Arbitrum RPC.
