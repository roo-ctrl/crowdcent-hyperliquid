# AGENTS.md — read this first (humans and AI assistants alike)

This file gives context to anyone — or any AI coding assistant like Claude or
Cursor — working in this repo. If you're non-technical, start here: open this
folder in Cursor or Claude Code, and the assistant will have read this file
and can answer your questions about anything below.

## What this project is, in plain language

CrowdCent runs a daily prediction contest. Each day they publish a list of
about 170 cryptocurrencies along with 180 measurements for each one. Your job
is to predict which of those coins will perform **best relative to the
others** over the next 10 days and 30 days — not whether they go up or down,
just their ranking against each other. Think of it like predicting the
finishing order of a horse race, not the finishing times.

You submit your ranking as a small file. After the 10 and 30 days pass,
CrowdCent scores how close your predicted order was to the real one, and a
leaderboard tracks everyone's skill over time.

## The three scripts

| Script | What it does | Plain-language version |
|---|---|---|
| `download_data.py` | Downloads training + inference data | "Get the history book and today's race card" |
| `train_and_predict.py` | Trains a model, writes `predictions/` | "Study the history, then predict today's race" |
| `submit.py` | Uploads the predictions | "Hand in the answer sheet" |

Run each with `uv run <script>.py`, in that order.

## Key facts an assistant needs

- **Data**: parquet files in `data/` (git-ignored, re-downloadable anytime).
  Training data is one row per asset per day since 2020; columns are `id`,
  `date`, 180 `feature_*` columns, and targets `target_10d` / `target_30d`.
  All features and targets are percentile ranks in [0, 1] — already
  normalized, no cleaning needed.
- **Submission format**: a parquet with exactly `id`, `pred_10d`, `pred_30d`,
  each prediction a float in [0, 1]. Only the *ordering* matters.
- **Timing**: new data 14:00 UTC daily; submissions close 18:00 UTC. Late
  submissions queue for the next day — never lost. 5 slots per day, and
  re-submitting to a slot overwrites it, so experimenting is safe.
- **Secrets**: the API key lives in `.env` (git-ignored). Never commit it,
  never print it.
- **Validation rule**: always split train/validation **by date** (train on
  the past, validate on the most recent dates). Never shuffle rows randomly —
  nearby days are near-duplicates and random splits give inflated scores.

## Branches

- `main` — the simple showcase version you are reading.
- `Roo` — Roo's working branch, includes `modeling.ipynb` with four models
  (gradient boosting, ridge, elastic net, linear regression) and an ensemble
  that averages them.

## Ground rules for AI assistants

- Keep `main` simple: three scripts, minimal dependencies. Experiments belong
  on personal branches.
- Don't submit to CrowdCent without the user explicitly asking.
- The user may be non-technical: explain what you're doing in plain language
  before running commands.
