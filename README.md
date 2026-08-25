# CrowdCent — Hyperliquid Ranking

Every day, [CrowdCent](https://crowdcent.com) asks: out of ~170 crypto assets,
which will do best and which will do worst over the next 10 and 30 days?
This repo is a complete, working entry: it pulls the data, trains a model,
and submits predictions — in three commands.

## Setup (once)

1. Install [uv](https://docs.astral.sh/uv/), then run `uv sync` in this folder.
2. Make an account at crowdcent.com, generate an API key on your profile page.
3. Create a file called `.env` in this folder containing:
   `CROWDCENT_API_KEY=your_key_here`

## The three commands

```bash
uv run download_data.py      # 1. get the data
uv run train_and_predict.py  # 2. train + predict -> predictions/
uv run submit.py             # 3. send it in
```

That's it. New data drops daily at 14:00 UTC; the submission window closes
at 18:00 UTC (7–11 AM Pacific). Submissions outside the window queue for
the next day automatically.

## How the model works, in one paragraph

Every asset, every day, gets 180 numbers describing where it stands
*relative to its peers* (all pre-computed by CrowdCent — no feature
engineering needed). The model learns which of those patterns historically
preceded outperformance, scores today's 170 assets, and ranks them 0 to 1.
That ranking is the submission.

## How the score works

CrowdCent grades each submission with **NDCG@40** — a metric that only cares
whether the 40 assets you ranked highest (and lowest) actually turned out to
be the best (and worst). There's a plain-language walkthrough, with the
170-coin "staircase", percentile bands, and the full weight table, in
[`docs/ndcg40-explained.html`](docs/ndcg40-explained.html). To read it,
open the file in a browser (GitHub shows the raw HTML source, not the page).

New here? Read `AGENTS.md` — it explains the project in plain language.
