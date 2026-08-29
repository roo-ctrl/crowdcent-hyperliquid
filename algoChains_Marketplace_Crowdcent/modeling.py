"""Step 2 — the model. Four-model rank ensemble from modeling.ipynb (branch Roo).

Ridge · ElasticNet · LinearRegression · HistGradientBoosting, each trained per
horizon (target_10d, target_30d); predictions rank-normalized to (0, 1] and
averaged with equal weight, then re-ranked. Time-based holdout (last N dates)
gives a sanity Spearman per model and for the ensemble.

LASSO from the notebook is excluded on purpose: alpha=0.1 on [0,1] targets
zeroes every coefficient (constant prediction, Spearman = NaN).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import polars as pl
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import ElasticNet, LinearRegression, Ridge

TARGETS = ("target_10d", "target_30d")

MODELS = {
    "Ridge": lambda: Ridge(alpha=1.0, random_state=42),
    "ElasticNet": lambda: ElasticNet(alpha=0.001, l1_ratio=0.5, max_iter=10000, random_state=42),
    "LR": lambda: LinearRegression(),
    "HGBR": lambda: HistGradientBoostingRegressor(
        max_iter=500, learning_rate=0.02, max_leaf_nodes=31, l2_regularization=1.0, random_state=42
    ),
}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] model: {msg}", flush=True)


def feature_columns(train: pl.DataFrame) -> list[str]:
    return [c for c in train.columns if c.startswith("feature_")]


def ts_split(train: pl.DataFrame, lookback: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Holdout = the last `lookback` dates. Never shuffle rows: nearby days are near-duplicates."""
    dates = train["date"].unique().sort()
    split_date = dates[-lookback]
    return train.filter(pl.col("date") < split_date), train.filter(pl.col("date") >= split_date)


def _x(df: pl.DataFrame, cols: list[str]):
    # features are percentile ranks in [0, 1]; a missing value is best treated as the median
    return df.select(cols).fill_null(0.5).to_numpy()


def rank01(values) -> pl.Series:
    s = pl.Series(values)
    return s.rank() / len(s)


def train_ensemble(train: pl.DataFrame, infer: pl.DataFrame, *, lookback: int = 60) -> pl.DataFrame:
    """Return the submission-shaped frame: id, pred_10d, pred_30d (floats in (0, 1])."""
    cols = feature_columns(train)
    log(f"{len(cols)} features, {train.height:,} training rows, {infer.height} inference rows")
    tr, va = ts_split(train, lookback)
    x_infer = _x(infer, cols)

    live: dict[str, dict[str, pl.Series]] = {n: {} for n in MODELS}
    val: dict[str, dict[str, pl.Series]] = {n: {} for n in MODELS}
    truth: dict[str, object] = {}

    for name, make in MODELS.items():
        for target in TARGETS:
            horizon = target.replace("target", "pred")
            tr_t, va_t = tr.drop_nulls(subset=[target]), va.drop_nulls(subset=[target])
            t0 = time.time()

            m = make()
            m.fit(_x(tr_t, cols), tr_t[target].to_numpy())
            val_pred = m.predict(_x(va_t, cols))
            corr, _ = spearmanr(va_t[target].to_numpy(), val_pred)

            full = train.drop_nulls(subset=[target])  # retrain on everything for the live universe
            m = make()
            m.fit(_x(full, cols), full[target].to_numpy())

            live[name][horizon] = rank01(m.predict(x_infer))
            val[name][horizon] = rank01(val_pred)
            truth[horizon] = va_t[target].to_numpy()
            log(f"{name:<10} {target}: holdout Spearman = {corr:.4f}  ({time.time() - t0:.0f}s)")

    out = {"id": infer["id"]}
    for target in TARGETS:
        horizon = target.replace("target", "pred")
        out[horizon] = rank01(pl.DataFrame({n: live[n][horizon] for n in MODELS}).mean_horizontal())
        v = pl.DataFrame({n: val[n][horizon] for n in MODELS}).mean_horizontal()
        corr, _ = spearmanr(truth[horizon], v.to_numpy())
        log(f"ENSEMBLE   {target}: holdout Spearman = {corr:.4f}")

    sub = pl.DataFrame(out)
    assert sub.columns == ["id", "pred_10d", "pred_30d"], sub.columns
    assert sub["pred_10d"].is_between(0, 1).all() and sub["pred_30d"].is_between(0, 1).all()
    assert sub.height >= 80, f"only {sub.height} assets"
    return sub
