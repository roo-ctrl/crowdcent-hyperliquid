"""Step 2 — the model, converted 1:1 from modeling.ipynb (the ensemble Roo chose).

Four linear-family models, each trained per horizon (target_10d, target_30d):
    Ridge · ElasticNet · LinearRegression · LASSO
Predictions are rank-normalised to (0, 1], averaged with equal weight across the
models, and re-ranked — exactly the notebook's aggregate(). Time-based holdout
(last `lookback` dates) gives a sanity Spearman per model and for the ensemble.
No gradient boosting.

Entry point used by pipeline.py:
    train_ensemble(train, infer, lookback=60) -> DataFrame[id, pred_10d, pred_30d]
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import polars as pl
from scipy.stats import spearmanr
from sklearn.linear_model import ElasticNet, Lasso, LinearRegression, Ridge

# We trade the 10-day horizon, so by default only target_10d is trained/evaluated.
# HORIZONS=10d,30d trains both (the CrowdCent submission needs a pred_30d column
# either way; with 10d only, pred_30d is a copy of pred_10d).
HORIZONS = [h.strip() for h in os.getenv("HORIZONS", "10d").split(",") if h.strip()]
TARGETS = [f"target_{h}" for h in HORIZONS]
MODELS = ["Ridge", "ElasticNet", "LR", "LASSO"]  # one key per model — the notebook's choice


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] model: {msg}", flush=True)


def _make(name: str):
    """Same estimators and hyper-parameters as the notebook cells."""
    if name == "Ridge":
        return Ridge(alpha=1.0, random_state=42)
    if name == "ElasticNet":
        # alpha much smaller than Ridge's: the L1 part zeroes coefficients aggressively
        return ElasticNet(alpha=0.001, l1_ratio=0.5, max_iter=10000, random_state=42)
    if name == "LR":
        return LinearRegression()  # plain OLS — no regularisation, no knobs
    if name == "LASSO":
        return Lasso(alpha=0.0001)
    raise ValueError(name)


def ts_split(train: pl.DataFrame, lookback: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Time-based holdout: the last `lookback` dates are validation (never shuffle)."""
    dates = train["date"].unique().sort()
    split_date = dates[-lookback]
    return train.filter(pl.col("date") < split_date), train.filter(pl.col("date") >= split_date)


def fit_model(name: str, train: pl.DataFrame, tr: pl.DataFrame, va: pl.DataFrame, infer: pl.DataFrame,
              feature_cols: list[str], preds: dict) -> dict:
    """The notebook's <Model>_regression() body, generic over the model name."""
    for target in TARGETS:
        tr_t = tr.drop_nulls(subset=[target])
        va_t = va.drop_nulls(subset=[target])
        t0 = time.time()

        model = _make(name)
        model.fit(tr_t[feature_cols].to_numpy(), tr_t[target].to_numpy())
        val_pred = model.predict(va_t[feature_cols].to_numpy())
        corr, _ = spearmanr(va_t[target].to_numpy(), val_pred)

        # retrain on all data before predicting the live universe
        full = train.drop_nulls(subset=[target])
        model = _make(name)
        model.fit(full[feature_cols].to_numpy(), full[target].to_numpy())
        raw = model.predict(infer[feature_cols].to_numpy())

        horizon = target.replace("target", "pred")
        preds[name][horizon] = pl.Series(raw).rank() / len(raw)  # rank-normalise to (0, 1]
        preds[name][f"val_{horizon}"] = pl.Series(val_pred).rank() / len(val_pred)  # for the ensemble check
        log(f"{name:<10} {target}: holdout Spearman = {corr:.4f}  ({time.time() - t0:.0f}s)")
    return preds


def aggregate(final: dict) -> pl.DataFrame:
    """Equal-weight ensemble: average the models' rank columns per horizon, re-rank to (0, 1]."""
    agg = {"id": final[MODELS[0]]["id"]}  # ids are identical across models
    for target in TARGETS:
        horizon = target.replace("target", "pred")
        stacked = pl.DataFrame({name: final[name][horizon] for name in MODELS})
        mean_rank = stacked.mean_horizontal()
        agg[horizon] = mean_rank.rank() / len(mean_rank)
    for horizon in ("pred_10d", "pred_30d"):  # submission needs both columns
        if horizon not in agg:
            agg[horizon] = agg["pred_10d" if "pred_10d" in agg else "pred_30d"]
    return pl.DataFrame({k: agg[k] for k in ("id", "pred_10d", "pred_30d")})


def train_ensemble(train: pl.DataFrame, infer: pl.DataFrame, *, lookback: int = 60) -> pl.DataFrame:
    feature_cols = [c for c in train.columns if c.startswith("feature_")]
    log(f"{len(feature_cols)} features, {train.height:,} training rows, {infer.height} inference rows")
    log(f"ensemble = {' + '.join(MODELS)} (equal-weight rank average) · horizons = {', '.join(HORIZONS)}")

    tr, va = ts_split(train, lookback)
    preds = {name: {"id": infer["id"]} for name in MODELS}
    for name in MODELS:
        preds = fit_model(name, train, tr, va, infer, feature_cols, preds)
    final = preds

    # ensemble sanity check on the holdout, same aggregation as aggregate()
    for target in TARGETS:
        horizon = target.replace("target", "pred")
        va_t = va.drop_nulls(subset=[target])
        stacked = pl.DataFrame({name: final[name][f"val_{horizon}"] for name in MODELS})
        corr, _ = spearmanr(va_t[target].to_numpy(), stacked.mean_horizontal().to_numpy())
        log(f"ENSEMBLE   {target}: holdout Spearman = {corr:.4f}")

    submission = aggregate(final)
    assert submission.columns == ["id", "pred_10d", "pred_30d"]
    assert submission["pred_10d"].is_between(0, 1).all()
    assert submission["pred_30d"].is_between(0, 1).all()
    assert submission.height >= 80
    return submission
