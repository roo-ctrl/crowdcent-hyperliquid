"""Welcome watcher — put every NEW subscriber into the positions we already hold.

Polls the AlgoChains subscriber registry. When a new username appears for
BOT_NAME (credentials present = activated), it reads the MAIN portfolio's
current positions from Alpaca (the account behind ALPACA_API_KEY) and sends
one *targeted* BUY per position — the fan-out executes only for that
subscriber, at today's prices, and does not touch anyone else.

    WELCOME_MODE=exact  (default)  qty_for_newcomer = main_qty
                                  (subscribers must fund >= the main account: $50k paper minimum)
    WELCOME_MODE=scaled            qty_for_newcomer = main_qty x (WELCOME_ACCOUNT_USD / main_equity)

Sanity check without a real subscriber:
    python welcome_watcher.py --simulate-new <username> [--dry-run]
    (prints what would be sent; if the main account is still flat it shows the
     positions from predictions/portfolio_latest.json that the main account WILL hold)

Re-welcome a subscriber who was seeded on first start (does not wipe known_subscribers.txt):
    python welcome_watcher.py --welcome-existing [username] [--dry-run]

State: /state/known_subscribers.txt (first run seeds silently, so existing
subscribers are never re-welcomed on a restart unless --welcome-existing).

Environment: REGISTRY_DB_URL, ALGOCHAINS_API_KEY, BOT_NAME, ALPACA_API_KEY /
ALPACA_SECRET_KEY, WELCOME_ACCOUNT_USD (50000), WATCH_POLL_SECONDS (60).
Paper-mode subscribers are not covered here (that rail has no per-user targeting).
"""
from __future__ import annotations

import os
import pathlib
import time
from datetime import datetime, timezone

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

from sendsignal import (  # noqa: E402
    ALPACA_API_KEY,
    ALPACA_BASE_URL,
    ALPACA_SECRET_KEY,
    BOT_NAME,
    attributed_client_order_id,
    send_signal,
)
from welcome_logic import SUBSCRIBER_SQL, decide_welcome_targets  # noqa: E402

DB_URL = os.getenv("REGISTRY_DB_URL", "").strip()
WELCOME_MODE = os.getenv("WELCOME_MODE", "exact").strip().lower()
WELCOME_USD = float(os.getenv("WELCOME_ACCOUNT_USD", "50000"))
OUT_DIR = pathlib.Path(os.getenv("OUT_DIR", "predictions"))
POLL = int(os.getenv("WATCH_POLL_SECONDS", "60"))
STATE = pathlib.Path(os.getenv("STATE_DIR", "state")) / "known_subscribers.txt"
_HDR = {"APCA-API-KEY-ID": ALPACA_API_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] welcome: {msg}", flush=True)


def subscribers() -> set[str]:
    """Usernames currently ACTIVE for BOT_NAME (broker credentials present)."""
    conn = psycopg2.connect(DB_URL, connect_timeout=10)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(SUBSCRIBER_SQL, [BOT_NAME])
            return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def main_portfolio() -> tuple[float, list[dict]]:
    """(equity, positions) of the main Alpaca account. Symbols come back as 'BTCUSD'."""
    acct = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=_HDR, timeout=(5, 20)).json()
    positions = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=_HDR, timeout=(5, 20)).json()
    return float(acct["equity"]), positions


def pair(symbol: str) -> str:
    """Alpaca position symbol 'BTCUSD' -> signal symbol 'BTC/USD'."""
    s = symbol.upper()
    return s if "/" in s else (f"{s[:-3]}/{s[-3:]}" if s.endswith("USD") else s)


def welcome(user: str, *, dry_run: bool = False, simulate: bool = False) -> list[dict]:
    """Copy the main portfolio into `user`'s account via targeted signals."""
    equity, positions = main_portfolio()
    longs = [
        {"symbol": pair(p["symbol"]), "qty": float(p["qty"]), "market_value": float(p.get("market_value") or 0)}
        for p in positions
        if p.get("side") == "long" and float(p.get("qty", 0)) > 0
    ]
    source = "main Alpaca account"
    if not longs and simulate:
        try:
            import json

            longs = [{"symbol": r["alpaca_symbol"], "qty": float(r["qty"]), "market_value": float(r["notional_usd"])}
                     for r in json.loads((OUT_DIR / "portfolio_latest.json").read_text())]
            source = "predictions/portfolio_latest.json (main account is flat — this is what it WILL hold)"
        except Exception:  # noqa: BLE001
            pass
    scale = 1.0 if WELCOME_MODE == "exact" else (WELCOME_USD / equity if equity > 0 else 0.0)
    log(f"NEW subscriber {user}: main equity ${equity:,.0f} · {len(longs)} long(s) from {source} · "
        f"mode={WELCOME_MODE} scale x{scale:.4f}")
    sent = []
    for p in longs:
        qty = round(p["qty"] * scale, 6)
        if qty <= 0:
            continue
        log(f"  -> {user}: BUY {qty:<14} {p['symbol']:<10} (~${p['market_value'] * scale:,.0f})")
        res = send_signal(
            "BUY",
            p["symbol"],
            qty,
            client_order_id=attributed_client_order_id("w", user, p["symbol"]),
            target_usernames=[user],
            dry_run=dry_run,
        )
        sent.append(res)
    log(f"welcome for {user} complete: {len(sent)} signal(s){' (dry-run)' if dry_run else ''}")
    return sent


def persist_known(current: set[str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text("\n".join(sorted(current)))


def run_once(
    *,
    first_run: bool,
    known: set[str],
    welcome_existing: bool = False,
    only_user: str | None = None,
    dry_run: bool = False,
) -> set[str]:
    """One poll cycle. Returns the updated known set. Does not wipe known on welcome-existing."""
    current = subscribers()
    targets, reason = decide_welcome_targets(
        known,
        current,
        first_run=first_run,
        welcome_existing=welcome_existing,
        only_user=only_user,
    )
    if reason == "seed" and (current - known):
        log(f"seeded existing subscriber(s): {', '.join(sorted(current - known))}")
    for user in sorted(targets):
        welcome(user, dry_run=dry_run)
    if current != known:
        gone = known - current
        if gone:
            log(f"deactivated (re-welcomed on return): {', '.join(sorted(gone))}")
        persist_known(current)
        return current
    return known


def main(*, welcome_existing: bool = False, only_user: str | None = None, dry_run: bool = False) -> None:
    if not (DB_URL and ALPACA_API_KEY and ALPACA_SECRET_KEY):
        log("REGISTRY_DB_URL and Alpaca keys are required — exiting")
        return
    STATE.parent.mkdir(parents=True, exist_ok=True)
    first_run = not STATE.exists()
    known = set(STATE.read_text().split()) if STATE.exists() else set()
    log(
        f"up — bot={BOT_NAME} poll={POLL}s known={len(known)}"
        f"{' (first run: seeding silently)' if first_run and not welcome_existing else ''}"
    )
    if welcome_existing or only_user:
        known = run_once(
            first_run=False,
            known=known,
            welcome_existing=True,
            only_user=only_user,
            dry_run=dry_run,
        )
        log("welcome-existing pass complete; entering poll loop")
        first_run = False
    while True:
        try:
            known = run_once(first_run=first_run, known=known, dry_run=dry_run)
            first_run = False
        except Exception as exc:  # noqa: BLE001
            log(f"cycle error: {type(exc).__name__}: {exc}")
        time.sleep(POLL)


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    if "--simulate-new" in argv:
        user = argv[argv.index("--simulate-new") + 1]
        welcome(user, dry_run=dry, simulate=True)
    elif "--welcome-existing" in argv:
        idx = argv.index("--welcome-existing")
        only = None
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
            only = argv[idx + 1]
        main(welcome_existing=True, only_user=only, dry_run=dry)
    else:
        main(dry_run=dry)
