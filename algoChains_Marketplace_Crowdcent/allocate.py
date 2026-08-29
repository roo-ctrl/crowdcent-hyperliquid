"""Step 4 — turn the ranking into a portfolio.

Take the TOP_N highest-ranked assets (by RANK_HORIZON, default pred_10d to
match the 10-day rerun), keep only the ones Alpaca can actually trade as
crypto pairs, and spread INVEST_PCT of PORTFOLIO_USD across them equally.

    $100,000 x 90% = $90,000 / 40 names = $2,250 per name
    qty = $2,250 / last price   (fractional, 6 dp)

Output: a list of {symbol, alpaca_symbol, rank, price, notional_usd, qty}.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import polars as pl
import requests

ALPACA_DATA = "https://data.alpaca.markets/v1beta3/crypto/us/latest/trades"


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] allocate: {msg}", flush=True)


def settings() -> dict:
    return {
        "top_n": int(os.getenv("TOP_N", "40")),
        "horizon": os.getenv("RANK_HORIZON", "pred_10d"),
        "portfolio_usd": float(os.getenv("PORTFOLIO_USD", "100000")),
        "invest_pct": float(os.getenv("INVEST_PCT", "0.90")),
    }


def alpaca_symbol(crowdcent_id: str) -> str:
    """CrowdCent ids are bare tickers ('AAVE'); Alpaca crypto pairs are 'AAVE/USD'."""
    return f"{crowdcent_id.upper()}/USD"


def tradable_crypto(api_key: str, api_secret: str, base_url: str) -> set[str]:
    """Set of active, tradable Alpaca crypto symbols ('AAVE/USD', ...). Needs Alpaca keys."""
    r = requests.get(
        f"{base_url}/v2/assets",
        params={"asset_class": "crypto", "status": "active"},
        headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret},
        timeout=(5, 20),
    )
    r.raise_for_status()
    return {a["symbol"] for a in r.json() if a.get("tradable")}


def last_prices(symbols: list[str]) -> dict[str, float]:
    """Latest trade price per Alpaca crypto symbol (public endpoint, no auth)."""
    prices: dict[str, float] = {}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i : i + 50]
        r = requests.get(ALPACA_DATA, params={"symbols": ",".join(chunk)}, timeout=(5, 20))
        r.raise_for_status()
        for sym, t in (r.json().get("trades") or {}).items():
            if t.get("p"):
                prices[sym] = float(t["p"])
    return prices


def build_portfolio(predictions: pl.DataFrame, tradable: set[str] | None) -> list[dict]:
    cfg = settings()
    ranked = predictions.sort(cfg["horizon"], descending=True)

    candidates = []
    for rank, (cid, score) in enumerate(zip(ranked["id"], ranked[cfg["horizon"]]), start=1):
        sym = alpaca_symbol(cid)
        if tradable is not None and sym not in tradable:
            continue
        candidates.append({"symbol": cid, "alpaca_symbol": sym, "rank": rank, "score": float(score)})
        if len(candidates) == cfg["top_n"]:
            break
    if not candidates:
        raise RuntimeError("no tradable assets in the ranking")
    if len(candidates) < cfg["top_n"]:
        log(f"only {len(candidates)} of top {cfg['top_n']} are tradable on Alpaca — allocating across those")

    prices = last_prices([c["alpaca_symbol"] for c in candidates])
    candidates = [c for c in candidates if c["alpaca_symbol"] in prices] or candidates
    per_name = cfg["portfolio_usd"] * cfg["invest_pct"] / len(candidates)

    portfolio = []
    for c in candidates:
        price = prices.get(c["alpaca_symbol"])
        if not price:
            log(f"no price for {c['alpaca_symbol']} — skipped")
            continue
        portfolio.append({**c, "price": price, "notional_usd": round(per_name, 2), "qty": round(per_name / price, 6)})

    log(
        f"top {len(portfolio)} longs by {cfg['horizon']} · "
        f"${cfg['portfolio_usd']:,.0f} x {cfg['invest_pct']:.0%} = ${cfg['portfolio_usd'] * cfg['invest_pct']:,.0f} · "
        f"${per_name:,.2f} each"
    )
    return portfolio
