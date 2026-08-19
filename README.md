# CrowdCent — Hyperliquid Ranking

Rank ~170 Hyperliquid crypto assets by expected relative return over 10-day and
30-day horizons. Docs: https://docs.crowdcent.com/

## One-time setup

1. Create an account at https://crowdcent.com, verify email.
2. Profile -> **Generate New Key**, paste it into `.env` (`CROWDCENT_API_KEY=...`).
3. Install deps: `uv sync`

## Workflow

```bash
uv run download_data.py      # pulls training + current inference parquet into data/
uv run train_and_predict.py  # trains LightGBM baseline, writes predictions/predictions.parquet
uv run submit.py             # uploads (queues if outside the 14:00-18:00 UTC window)
```

## Key facts

- Training data: `id`, `eodhd_id`, `date`, 80 features (`feature_{n}_lag{0,5,10,15}`),
  targets `target_10d`, `target_30d`.
- Submission format: `id`, `pred_10d`, `pred_30d` — floats in [0, 1], min 80 assets.
- New inference data daily ~14:00 UTC; submission window closes ~18:00 UTC; 5 slots/day.
- Scoring: symmetric NDCG@40 + Spearman, plus "unique" variants vs the meta-model.
  Composite score needs ≥10 submissions.
