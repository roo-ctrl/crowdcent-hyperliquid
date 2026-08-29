"""Step 5 — send trade signals to AlgoChains (and optionally trade the owner's own Alpaca).

WHAT IS REQUIRED to send a signal to AlgoChains:
    1. An AlgoChains API key (Developer -> keys on the website)      -> ALGOCHAINS_API_KEY
    2. The bot's marketplace name, exactly as listed                -> BOT_NAME
    3. One HTTPS POST per trade to the signal endpoint              -> SIGNAL_URL
           POST https://signals-prod.algochains.ai/signals/signal/
           headers: X-API-Key: <ALGOCHAINS_API_KEY>
           json:    {"strategy_name": BOT_NAME, "symbol": "AAVE/USD", "side": "BUY", "qty": 12.5,
                     "client_order_id": "<unique id>"}
       sides: BUY · SELL · SHORT · CLOSE_ALL
       response: 202 {"status":"accepted","dispatched":<subscribers>,"paper_bridge":"queued"}
    That's it. The fan-out looks up everyone subscribed to BOT_NAME, places the
    order in their broker accounts, and mirrors the signal to AlgoChains Paper.

OPTIONAL — trade the same signal on the owner's own Alpaca account:
    ALPACA_API_KEY / ALPACA_SECRET_KEY (paper keys start with "PK")  -> execute_direct()

Both functions are best-effort and never raise into the pipeline.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import requests

SIGNAL_URL = os.getenv("SIGNAL_URL", "https://signals-prod.algochains.ai/signals/signal/")
ALGOCHAINS_API_KEY = os.getenv("ALGOCHAINS_API_KEY", "").strip()
BOT_NAME = os.getenv("BOT_NAME", "CrowdCent_Hyperliquid_Top40")

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "").strip()
ALPACA_BASE_URL = os.getenv(
    "ALPACA_BASE_URL",
    "https://paper-api.alpaca.markets" if ALPACA_API_KEY.startswith("PK") else "https://api.alpaca.markets",
)


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] signal: {msg}", flush=True)


def send_signal(side: str, symbol: str, qty: float, *, client_order_id: str | None = None, dry_run: bool = False) -> dict:
    """POST one signal to AlgoChains. Returns the response dict (or a dry-run echo)."""
    payload = {
        "strategy_name": BOT_NAME,
        "symbol": symbol,
        "side": side.upper(),
        "qty": float(qty),
        "client_order_id": client_order_id or uuid.uuid4().hex,
    }
    if dry_run or not ALGOCHAINS_API_KEY:
        log(f"[dry-run] would POST {payload}")
        return {"dry_run": True, **payload}
    try:
        r = requests.post(SIGNAL_URL, json=payload, headers={"X-API-Key": ALGOCHAINS_API_KEY}, timeout=(5, 20))
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"text": r.text[:200]}
        log(f"{side} {qty} {symbol}: HTTP {r.status_code} dispatched={body.get('dispatched')} paper={body.get('paper_bridge')}")
        return {"status_code": r.status_code, **body}
    except Exception as exc:  # noqa: BLE001 — one bad symbol must not stop the batch
        log(f"{side} {qty} {symbol}: FAILED {type(exc).__name__}: {exc}")
        return {"error": f"{type(exc).__name__}: {exc}", **payload}


def execute_direct(side: str, symbol: str, qty: float, *, dry_run: bool = False) -> dict | None:
    """Mirror the signal on the owner's own Alpaca account (market order, GTC). Never raises."""
    if not (ALPACA_API_KEY and ALPACA_SECRET_KEY):
        return None
    order = {"symbol": symbol, "qty": str(qty), "side": side.lower(), "type": "market", "time_in_force": "gtc"}
    if dry_run:
        log(f"[dry-run] would place on own Alpaca: {order}")
        return {"dry_run": True, **order}
    try:
        r = requests.post(
            f"{ALPACA_BASE_URL}/v2/orders",
            json=order,
            headers={"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY},
            timeout=(5, 20),
        )
        body = r.json()
        log(f"own Alpaca {side} {qty} {symbol}: HTTP {r.status_code} id={body.get('id')} status={body.get('status')}")
        return body
    except Exception as exc:  # noqa: BLE001
        log(f"own Alpaca {side} {qty} {symbol}: FAILED {type(exc).__name__}: {exc}")
        return None


if __name__ == "__main__":
    # smoke test:  python sendsignal.py BUY AAVE/USD 1.5   (dry-run unless ALGOCHAINS_API_KEY is set)
    import sys

    if len(sys.argv) != 4:
        print("usage: python sendsignal.py <BUY|SELL|SHORT|CLOSE_ALL> <SYMBOL> <QTY>")
        sys.exit(2)
    print(send_signal(sys.argv[1], sys.argv[2], float(sys.argv[3])))
