# algoChains Marketplace · CrowdCent bot

Every 10 days: pull the latest CrowdCent Hyperliquid data → rank ~170 crypto
assets with the 4-model ensemble → take the **top 40 longs** → allocate **90% of
a $100,000 portfolio** equally ($2,250 each) → send BUY/SELL rebalance signals
to AlgoChains subscribers. Runs as one Docker container, same pattern as
`Roobertos_Crypto_Bot`, so it drops onto the same Linode.

```
pipeline.py      1 download → 2 model → 3 save → 4 allocate → 5 send signals
modeling.py      the ensemble (Ridge · ElasticNet · Linear · HistGradientBoosting)
allocate.py      top-N, Alpaca-tradable filter, equal-weight sizing
sendsignal.py    send_signal() to AlgoChains (+ optional execute_direct() on your Alpaca)
scheduler.py     the 10-day loop (state/last_run.txt)
data/            downloaded parquet          predictions/  ensemble_<date>.parquet, portfolio_<date>.json
state/           last_run.txt, positions.json (what we hold between runs)
```

## Setup

1. `cp .env.example .env` and fill in:
   - `CROWDCENT_API_KEY` — crowdcent.com → profile → Generate New Key
   - `ALGOCHAINS_API_KEY` + `BOT_NAME` — must match the marketplace listing exactly (`CrowdCent-Model-Roo`)
   - `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — used to filter the top-40 to pairs Alpaca can trade (and, if `EXECUTE_DIRECT=1`, to mirror the trades on your own account)
2. Leave the switches at 0 for the first run: `SUBMIT=0`, `SEND_SIGNALS=0`, `EXECUTE_DIRECT=0`.

## Run

```bash
docker compose build
docker compose run --rm -e RUN_ONCE=1 crowdcent --dry-run   # train + allocate, send nothing, print the signals
docker compose run --rm -e RUN_ONCE=1 crowdcent             # honors the .env switches
docker compose up -d                                        # the bot: every RUN_EVERY_DAYS at RUN_AT_UTC
docker compose logs -f
```

Local (no Docker): `uv sync && uv run pipeline.py --dry-run`.

Welcome a subscriber who was only seeded (no signals sent) on first watcher start.
The compose entrypoint is already `python -u welcome_watcher.py`, so pass flags only:

```bash
docker compose run --rm welcome_watcher --welcome-existing --dry-run
docker compose run --rm welcome_watcher --welcome-existing ronaldo
```

`client_order_id` values include the listing slug (`ac-crowdcent-model-roo-…`) so AlgoChains Portfolio can attribute fills.

## What is required to send a signal to AlgoChains

Exactly three things — see the top of `sendsignal.py`:

1. an AlgoChains API key (`X-API-Key` header),
2. the bot's marketplace name (`strategy_name`),
3. one HTTPS POST per trade to `https://signals-prod.algochains.ai/signals/signal/` with
   `{"strategy_name", "symbol", "side": BUY|SELL|SHORT|CLOSE_ALL, "qty", "client_order_id"}`.

The fan-out then looks up every subscriber of that bot, places the order in their
broker account, and mirrors the signal to AlgoChains Paper.

## How the rebalance works

- The ranking is by `RANK_HORIZON` (default `pred_10d`, matching the 10-day rerun).
- Only assets Alpaca lists as tradable crypto pairs (`AAVE/USD`, …) are eligible; the
  top 40 are taken from those. Sizing: `PORTFOLIO_USD × INVEST_PCT / 40` per name,
  `qty = notional / last price`.
- `state/positions.json` remembers the previous run. Each run: **SELL** names that
  dropped out, **BUY** new entrants, leave names that stay (no churn on the rest).
- First run with `SEND_SIGNALS=1` buys all 40.

## Deploy to the Linode (later)

```bash
scp -r algoChains_Marketplace_Crowdcent root@172.232.162.253:/opt/
ssh root@172.232.162.253 'cd /opt/algoChains_Marketplace_Crowdcent && docker compose up -d --build'
```
