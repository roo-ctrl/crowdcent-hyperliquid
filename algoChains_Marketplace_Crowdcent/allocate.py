"""Step 4 — turn the ranking into a portfolio.

Walk down the CrowdCent ranking (by RANK_HORIZON, default pred_10d) and keep
the assets Alpaca can actually trade as crypto pairs, up to TOP_N of them.
CrowdCent ranks ~170 tokens and Alpaca lists only a few dozen, so N is
"however many tradable names we found", not a fixed 40.

Sizing (WEIGHTING=log, default): the ranking is the signal, so position size
decays logarithmically with rank — rank 1 gets the most, the last tradable
name gets substantially less:

    w_i = ln((N + 1) / i)      i = 1..N, normalised to sum to 1
    notional_i = PORTFOLIO_USD x INVEST_PCT x w_i
    qty_i = notional_i / last price   (fractional, 6 dp)

    e.g. N = 20, $90,000 invested: #1 ~ $8,700 · #10 ~ $2,100 · #20 ~ $140

WEIGHTING=equal gives the old flat split. Names whose slice would be below
MIN_NOTIONAL_USD are dropped so we never send dust orders.

Output: a list of {symbol, alpaca_symbol, rank, price, weight, notional_usd, qty}.
"""
from __future__ import annotations

import math
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
        "portfolio_usd": os.getenv("PORTFOLIO_USD", "auto").strip().lower(),  # "auto" or a number
        "invest_pct": float(os.getenv("INVEST_PCT", "0.90")),
        "weighting": os.getenv("WEIGHTING", "log").strip().lower(),
        "min_notional": float(os.getenv("MIN_NOTIONAL_USD", "10")),
    }


def weights(n: int, scheme: str = "log") -> list[float]:
    """Position weights for ranks 1..n, summing to 1."""
    if scheme == "equal" or n == 1:
        return [1.0 / n] * n
    raw = [math.log((n + 1) / i) for i in range(1, n + 1)]  # log decay: big at #1, tiny at #n
    total = sum(raw)
    return [w / total for w in raw]


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


def main_equity(api_key: str, api_secret: str, base_url: str) -> float:
    """Live equity of the main Alpaca account (PORTFOLIO_USD=auto)."""
    r = requests.get(
        f"{base_url}/v2/account",
        headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret},
        timeout=(5, 20),
    )
    r.raise_for_status()
    return float(r.json()["equity"])


def build_portfolio(predictions: pl.DataFrame, tradable: set[str] | None, *, portfolio_usd: float | None = None) -> list[dict]:
    cfg = settings()
    if portfolio_usd is not None:
        cfg["portfolio_usd"] = float(portfolio_usd)
    elif cfg["portfolio_usd"] == "auto":
        raise RuntimeError("PORTFOLIO_USD=auto needs Alpaca keys (main account equity)")
    else:
        cfg["portfolio_usd"] = float(cfg["portfolio_usd"])
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
    candidates = [c for c in candidates if prices.get(c["alpaca_symbol"])]
    if not candidates:
        raise RuntimeError("no prices for any tradable asset")
    invest = cfg["portfolio_usd"] * cfg["invest_pct"]
    ws = weights(len(candidates), cfg["weighting"])

    portfolio = []
    for pos, (c, w) in enumerate(zip(candidates, ws), start=1):
        notional = invest * w
        if notional < cfg["min_notional"]:
            log(f"#{pos} {c['alpaca_symbol']}: ${notional:,.2f} below MIN_NOTIONAL_USD — dropped")
            continue
        price = prices[c["alpaca_symbol"]]
        portfolio.append({
            **c,
            "position": pos,
            "price": price,
            "weight": round(w, 6),
            "notional_usd": round(notional, 2),
            "qty": round(notional / price, 6),
        })

    log(
        f"{len(portfolio)} tradable longs by {cfg['horizon']} ({cfg['weighting']} weighting) · "
        f"${cfg['portfolio_usd']:,.0f} x {cfg['invest_pct']:.0%} = ${invest:,.0f} · "
        f"#1 ${portfolio[0]['notional_usd']:,.0f} … #{len(portfolio)} ${portfolio[-1]['notional_usd']:,.0f}"
    )
    return portfolio
