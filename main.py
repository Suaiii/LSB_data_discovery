#!/usr/bin/env python3
"""Arbitrum Uniswap V3 WETH/USDC swap discovery and price dislocation analysis."""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from web3 import Web3
from web3.exceptions import Web3Exception

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
DATA_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

DEFAULT_RPC = "https://arb1.arbitrum.io/rpc"
RPC_FALLBACKS = [
    DEFAULT_RPC,
    "https://arbitrum-one.publicnode.com",
    "https://1rpc.io/arb",
]
FACTORY = Web3.to_checksum_address("0x1F98431c8aD98523631AE4a59f267346ea31F984")
WETH = Web3.to_checksum_address("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1")
USDC = Web3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831")
FEES = (500, 3000)
ZERO = "0x0000000000000000000000000000000000000000"
SWAP_TOPIC = "0x" + Web3.keccak(text="Swap(address,address,int256,int256,uint160,uint128,int24)").hex().removeprefix("0x")

FACTORY_ABI = [{"inputs":[{"internalType":"address","name":"tokenA","type":"address"},{"internalType":"address","name":"tokenB","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"}],"name":"getPool","outputs":[{"internalType":"address","name":"pool","type":"address"}],"stateMutability":"view","type":"function"}]
POOL_ABI = [
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"anonymous": False, "inputs": [
        {"indexed": True, "name": "sender", "type": "address"}, {"indexed": True, "name": "recipient", "type": "address"},
        {"indexed": False, "name": "amount0", "type": "int256"}, {"indexed": False, "name": "amount1", "type": "int256"},
        {"indexed": False, "name": "sqrtPriceX96", "type": "uint160"}, {"indexed": False, "name": "liquidity", "type": "uint128"}, {"indexed": False, "name": "tick", "type": "int24"}], "name": "Swap", "type": "event"},
]


def connect(rpc: str | None = None) -> tuple[Web3, str]:
    urls = [rpc] if rpc else []
    urls += [u for u in RPC_FALLBACKS if u not in urls]
    errors = []
    for url in urls:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
            if w3.is_connected() and w3.eth.chain_id == 42161:
                return w3, url
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("No Arbitrum RPC endpoint responded. " + " | ".join(errors))


def signed_word(value: str | bytes) -> int:
    n = int(value.hex() if isinstance(value, bytes) else value, 16)
    return n - (1 << 256) if n >= (1 << 255) else n


def decode_swap(w3: Web3, raw: dict[str, Any], fee: int, pool: str, token0: str, token1: str) -> dict[str, Any]:
    topics = raw["topics"]
    if isinstance(topics[0], bytes):
        topics = ["0x" + t.hex() for t in topics]
    data = raw["data"]
    data_hex = data.hex() if isinstance(data, bytes) else data[2:]
    words = [data_hex[i:i + 64] for i in range(0, len(data_hex), 64)]
    amount0, amount1 = signed_word(words[0]), signed_word(words[1])
    sqrt_price, liquidity, tick = int(words[2], 16), int(words[3], 16), signed_word(words[4])
    ratio = (sqrt_price / (2 ** 96)) ** 2
    if token0.lower() == WETH.lower():
        weth = amount0 / 1e18; usdc = amount1 / 1e6; price = ratio * 1e12
    else:
        usdc = amount0 / 1e6; weth = amount1 / 1e18; price = 1 / (ratio * 1e-12)
    return {"fee": fee, "pool": pool, "block_number": int(raw["blockNumber"], 16) if isinstance(raw["blockNumber"], str) else int(raw["blockNumber"]),
            "log_index": int(raw["logIndex"], 16) if isinstance(raw["logIndex"], str) else int(raw["logIndex"]),
            "tx_hash": raw["transactionHash"].hex() if isinstance(raw["transactionHash"], bytes) else raw["transactionHash"],
            "sender": "0x" + topics[1][-40:], "recipient": "0x" + topics[2][-40:], "amount_weth": weth,
            "amount_usdc": usdc, "notional_usdc": abs(usdc), "sqrt_price_x96": sqrt_price,
            "liquidity": liquidity, "tick": tick, "price_usdc_per_weth": price,
            "direction": "SELL_WETH" if weth > 0 else "BUY_WETH"}


def discover_pools(w3: Web3) -> dict[int, str]:
    factory = w3.eth.contract(address=FACTORY, abi=FACTORY_ABI)
    pools: dict[int, str] = {}
    for fee in FEES:
        pool = factory.functions.getPool(WETH, USDC, fee).call()
        if pool and pool.lower() != ZERO:
            pools[fee] = Web3.to_checksum_address(pool)
    return pools


def collect(w3: Web3, pools: dict[int, str], start: int, end: int, chunk_size: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fee, pool in pools.items():
        contract = w3.eth.contract(address=pool, abi=POOL_ABI)
        token0 = Web3.to_checksum_address(contract.functions.token0().call())
        token1 = Web3.to_checksum_address(contract.functions.token1().call())
        cursor, chunk = start, chunk_size
        while cursor <= end:
            stop = min(cursor + chunk - 1, end)
            try:
                range_start = cursor
                logs = w3.eth.get_logs({"address": pool, "topics": [SWAP_TOPIC], "fromBlock": range_start, "toBlock": stop})
                rows.extend(decode_swap(w3, dict(log), fee, pool, token0, token1) for log in logs)
                cursor = stop + 1
                chunk = min(chunk_size, max(100, chunk * 2))
                print(f"fee={fee} blocks={range_start}-{stop} swaps={len(logs)}")
            except Exception as exc:
                if chunk <= 100:
                    print(f"Skipping blocks {cursor}-{stop}: {exc}")
                    cursor = stop + 1
                else:
                    chunk = max(100, chunk // 2)
                    print(f"RPC range rejected; retrying with chunk={chunk}")
    return rows


def demo_rows() -> list[dict[str, Any]]:
    rng = np.random.default_rng(7)
    rows = []
    block = 300_000_000
    for fee, base in ((500, 3_350.0), (3000, 3_352.0)):
        price = base
        for i in range(240):
            shock = rng.normal(0, 0.0007)
            if i in (35, 90, 160): shock += 0.012
            if i in (38, 93, 163): shock -= 0.007
            price *= 1 + shock
            notional = float(abs(rng.normal(18_000, 9_000)))
            if i in (35, 90, 160): notional = 250_000.0
            rows.append({"fee": fee, "pool": f"demo-{fee}", "block_number": block + i * 2, "log_index": 1,
                         "tx_hash": f"0x{i:064x}", "sender": "0x" + "1" * 40, "recipient": "0x" + "2" * 40,
                         "amount_weth": -notional / price, "amount_usdc": notional, "notional_usdc": notional,
                         "sqrt_price_x96": int(math.sqrt(price / 1e12) * 2 ** 96), "liquidity": 10**15,
                         "tick": int(math.log(price / 3_350) / math.log(1.0001)), "price_usdc_per_weth": price,
                         "direction": "BUY_WETH"})
    return rows


def analyse(df: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return {"swap_count": 0, "fees": [], "note": "No swaps collected; rerun with a larger lookback or --demo."}, pd.DataFrame(), pd.DataFrame()
    df = df.sort_values(["fee", "block_number", "log_index"]).copy()
    candidates = []
    per_fee = []
    for fee, g in df.groupby("fee", sort=True):
        g = g.reset_index(drop=True)
        g["previous_price"] = g.price_usdc_per_weth.shift(1)
        g["shock_bps"] = (g.price_usdc_per_weth / g.previous_price - 1) * 10_000
        threshold = float(g.notional_usdc.quantile(.95))
        large = g[(g.notional_usdc >= threshold) & (g.shock_bps.abs() >= 2)].copy()
        reverted = 0; distances = []
        for idx, event in large.iterrows():
            pre = g.loc[idx - 1, "price_usdc_per_weth"] if idx else np.nan
            move = abs(event.price_usdc_per_weth - pre)
            if not move: continue
            for j in range(idx + 1, min(idx + 11, len(g))):
                frac = 1 - abs(g.loc[j, "price_usdc_per_weth"] - pre) / move
                if frac >= .5:
                    reverted += 1; distances.append(int(g.loc[j, "block_number"] - event.block_number))
                    row = event.to_dict(); row.update(reversion_fraction=float(frac), reversion_blocks=distances[-1]); candidates.append(row); break
        per_fee.append({"fee": int(fee), "swap_count": int(len(g)), "volume_usdc": float(g.notional_usdc.sum()),
                        "median_swap_usdc": float(g.notional_usdc.median()), "large_swap_threshold_p95": threshold,
                        "large_price_shocks": int(len(large)), "reverted_within_10_swaps": reverted,
                        "reversion_rate": float(reverted / len(large)) if len(large) else 0.0,
                        "median_reversion_blocks": float(np.median(distances)) if distances else None})
    # As-of block comparison across fee tiers: signals where pools diverge by >10 bps.
    piv = df.pivot_table(index="block_number", columns="fee", values="price_usdc_per_weth", aggfunc="last").sort_index().ffill()
    signals = []
    if len(FEES) == 2 and FEES[0] in piv and FEES[1] in piv:
        piv["dislocation_bps"] = (piv[FEES[1]] / piv[FEES[0]] - 1) * 10_000
        for block, row in piv[piv.dislocation_bps.abs() >= 10].iterrows():
            signals.append({"block_number": int(block), "price_fee_500": float(row[FEES[0]]), "price_fee_3000": float(row[FEES[1]]), "dislocation_bps": float(row.dislocation_bps), "direction": "3000_premium" if row.dislocation_bps > 0 else "500_premium"})
    summary = {"swap_count": int(len(df)), "fee_tiers": [int(x) for x in sorted(df.fee.unique())], "block_start": int(df.block_number.min()), "block_end": int(df.block_number.max()), "per_fee": per_fee, "cross_pool_signal_count": len(signals)}
    return summary, pd.DataFrame(candidates), pd.DataFrame(signals)


def write_outputs(df: pd.DataFrame, summary: dict[str, Any], candidates: pd.DataFrame, signals: pd.DataFrame, source: str) -> None:
    df.to_csv(DATA_DIR / "swaps.csv", index=False)
    candidates.to_csv(RESULTS_DIR / "candidate_reversions.csv", index=False)
    signals.to_csv(RESULTS_DIR / "cross_pool_signals.csv", index=False)
    summary.update({"source": source, "generated_at_utc": pd.Timestamp.utcnow().isoformat()})
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    lines = ["# Findings", "", f"Data source: `{source}`.", f"The pipeline collected **{summary.get('swap_count', 0):,} Swap events** across fee tiers `{summary.get('fee_tiers', [])}`.", ""]
    for row in summary.get("per_fee", []):
        lines.append(f"- Fee {row['fee'] / 1_000_000:.2%}: {row['swap_count']:,} swaps, ${row['volume_usdc']:,.0f} notional, {row['reversion_rate']:.1%} of large price shocks reverted within ten subsequent swaps.")
    lines += ["", "Cross-pool signals are rows where the last observed price in the 0.30% pool differed from the 0.05% pool by at least 10 bps at an aligned block.", "", "## Interpretation", "A large swap changes the pool's marginal price. A subsequent move back toward the pre-swap price is a simple, observable proxy for short-lived dislocation and possible backrun/arbitrage activity. This is a signal detector, not proof that a particular transaction was an arbitrage trade: proving that would require decoding router paths, gas ordering, and profitability.", "", "## Reproduction", "Run `python main.py --demo` for an offline smoke test, or `python main.py --lookback-blocks 20000` against the free public Arbitrum RPC."]
    (RESULTS_DIR / "findings.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Generate deterministic local data without an RPC")
    parser.add_argument("--rpc", default=os.getenv("RPC_URL"), help="Arbitrum RPC URL")
    parser.add_argument("--lookback-blocks", type=int, default=int(os.getenv("LOOKBACK_BLOCKS", "10000")))
    parser.add_argument("--chunk-size", type=int, default=int(os.getenv("CHUNK_SIZE", "2000")))
    args = parser.parse_args()
    if args.demo:
        rows, source = demo_rows(), "deterministic demo data"
    else:
        w3, source = connect(args.rpc)
        latest = w3.eth.block_number
        start = max(0, latest - args.lookback_blocks + 1)
        print(f"Connected to chain 42161 via {source}; scanning blocks {start}-{latest}")
        pools = discover_pools(w3)
        print("Pools:", pools)
        rows = collect(w3, pools, start, latest, args.chunk_size)
    df = pd.DataFrame(rows)
    summary, candidates, signals = analyse(df)
    write_outputs(df, summary, candidates, signals, source)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
