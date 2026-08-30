"""The whole run, in order:

    1. download the latest CrowdCent data              (data/)
    2. run it through the model — 4-model rank ensemble (modeling.py)
    3. save the ranking                                 (predictions/ensemble_<date>.parquet + _latest)
    4. allocate: top-N tradable longs, log-decay sizing, 90% of the main account (allocate.py -> predictions/portfolio_<date>.json)
    5. send signals to AlgoChains for the rebalance     (sendsignal.py)
       - SELL whatever we held last run that dropped out of the top-40
       - BUY every new entrant
       - names that stay in the list are left alone (no churn)
       state/positions.json remembers what we hold between runs.
    (+ optionally submit the ranking to CrowdCent, and mirror the trades on the owner's own Alpaca)

Usage:
    python pipeline.py                      # everything, honoring the .env switches
    python pipeline.py --no-download        # reuse data/ on disk
    python pipeline.py --dry-run            # train + allocate, print the signals, send nothing

.env switches (see .env.example): SUBMIT, SEND_SIGNALS, EXECUTE_DIRECT
Exit code is non-zero on failure so scheduler.py won't mark the run as done.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from dotenv import load_dotenv

load_dotenv()  # the .env in THIS folder (or the container's env_file)

from allocate import build_portfolio, main_equity, tradable_crypto  # noqa: E402
from modeling import train_ensemble  # noqa: E402
from sendsignal import ALPACA_API_KEY, ALPACA_BASE_URL, ALPACA_SECRET_KEY, BOT_NAME, execute_direct, send_signal  # noqa: E402

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
OUT_DIR = Path(os.getenv("OUT_DIR", "predictions"))
STATE_DIR = Path(os.getenv("STATE_DIR", "state"))
POSITIONS_FILE = STATE_DIR / "positions.json"
CHALLENGE = "hyperliquid-ranking"


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] pipeline: {msg}", flush=True)


def flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() == "1"


# ── 1. download ──────────────────────────────────────────────────────────────


def download() -> None:
    from crowdcent_challenge import ChallengeClient

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = ChallengeClient(challenge_slug=CHALLENGE)
    log("downloading training data (latest) ...")
    client.download_training_dataset("latest", str(DATA_DIR / "training_data.parquet"))
    log("downloading inference data (latest) ...")
    client.download_inference_data("latest", str(DATA_DIR / "inference_data.parquet"))


# ── 3. save ──────────────────────────────────────────────────────────────────


def save_predictions(sub: pl.DataFrame, day: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dated = OUT_DIR / f"ensemble_{day}.parquet"
    sub.write_parquet(dated)
    sub.write_parquet(OUT_DIR / "ensemble_latest.parquet")
    log(f"saved {dated} (+ ensemble_latest.parquet), {sub.height} assets")
    return dated


def submit_to_crowdcent(path: Path) -> None:
    from crowdcent_challenge import ChallengeClient

    slot = int(os.getenv("SUBMIT_SLOT", "1"))
    result = ChallengeClient(challenge_slug=CHALLENGE).submit_predictions(file_path=str(path), slot=slot)
    log(f"CrowdCent submission (slot {slot}): {result}")


# ── 5. rebalance signals ─────────────────────────────────────────────────────


def load_positions() -> dict[str, float]:
    try:
        return json.loads(POSITIONS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_positions(positions: dict[str, float]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    POSITIONS_FILE.write_text(json.dumps(positions, indent=2, sort_keys=True))


def rebalance(portfolio: list[dict], *, dry_run: bool, direct: bool, day: str) -> dict[str, float]:
    held = load_positions()
    target = {p["alpaca_symbol"]: p["qty"] for p in portfolio}

    sells = {s: q for s, q in held.items() if s not in target}
    buys = {s: q for s, q in target.items() if s not in held}
    keeps = [s for s in target if s in held]
    log(f"rebalance: sell {len(sells)} · buy {len(buys)} · keep {len(keeps)}")

    for sym, qty in sells.items():
        send_signal("SELL", sym, qty, client_order_id=f"cc-{day}-sell-{sym.replace('/', '')}", dry_run=dry_run)
        if direct:
            execute_direct("SELL", sym, qty, dry_run=dry_run)
    for sym, qty in buys.items():
        send_signal("BUY", sym, qty, client_order_id=f"cc-{day}-buy-{sym.replace('/', '')}", dry_run=dry_run)
        if direct:
            execute_direct("BUY", sym, qty, dry_run=dry_run)

    new_positions = {**{s: held[s] for s in keeps}, **buys}
    return new_positions


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    do_download = "--no-download" not in argv
    do_submit = flag("SUBMIT", "0") and not dry_run
    do_signals = flag("SEND_SIGNALS", "0") and not dry_run
    do_direct = flag("EXECUTE_DIRECT", "0") and not dry_run
    day = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    t0 = time.time()
    log(f"start · bot={BOT_NAME} · download={do_download} submit={do_submit} signals={do_signals} direct={do_direct} dry_run={dry_run}")

    if do_download:  # 1
        download()
    train = pl.read_parquet(DATA_DIR / "training_data.parquet")
    infer = pl.read_parquet(DATA_DIR / "inference_data.parquet")

    sub = train_ensemble(train, infer, lookback=int(os.getenv("VAL_LOOKBACK_DATES", "60")))  # 2
    dated = save_predictions(sub, day)  # 3
    if do_submit:
        submit_to_crowdcent(dated)

    tradable, portfolio_usd = None, None  # 4
    if ALPACA_API_KEY and ALPACA_SECRET_KEY:
        tradable = tradable_crypto(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)
        log(f"{len(tradable)} crypto pairs tradable on Alpaca")
        if os.getenv("PORTFOLIO_USD", "auto").strip().lower() == "auto":
            portfolio_usd = main_equity(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)
            log(f"PORTFOLIO_USD=auto -> main Alpaca equity ${portfolio_usd:,.2f}")
    else:
        log("no Alpaca keys — cannot filter to tradable pairs; using the raw top-N")
    portfolio = build_portfolio(sub, tradable, portfolio_usd=portfolio_usd)
    (OUT_DIR / f"portfolio_{day}.json").write_text(json.dumps(portfolio, indent=2))
    (OUT_DIR / "portfolio_latest.json").write_text(json.dumps(portfolio, indent=2))
    with pl.Config(tbl_rows=200, tbl_width_chars=140):
        print(pl.DataFrame(portfolio).select("position", "rank", "symbol", "alpaca_symbol", "price", "weight", "notional_usd", "qty"), flush=True)

    # 5 — always compute the rebalance; only send when SEND_SIGNALS=1 (or print in dry-run)
    positions = rebalance(portfolio, dry_run=(dry_run or not do_signals), direct=do_direct, day=day)
    if do_signals:
        save_positions(positions)
        log(f"positions saved: {len(positions)} names")
    else:
        log("SEND_SIGNALS off — signals printed above, positions.json untouched")

    log(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        log(f"FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)
