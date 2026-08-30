"""Train a baseline gradient-boosting model per horizon and write predictions.parquet.

Baseline approach: histogram GBM regression (sklearn's LightGBM-equivalent)
on each target (target_10d, target_30d), with a time-based holdout for a
sanity-check Spearman score. Predictions are rank-normalized to [0, 1]
per the submission spec (id, pred_10d, pred_30d).
"""

from pathlib import Path

import polars as pl
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

DATA_DIR = Path("data") # folder
OUT_DIR = Path("predictions") # folder
OUT_DIR.mkdir(exist_ok=True)

train = pl.read_parquet(DATA_DIR / "training_data.parquet")
infer = pl.read_parquet(DATA_DIR / "inference_data.parquet")

feature_cols = [c for c in train.columns if c.startswith("feature_")] # extract the feature columns
print(f"{len(feature_cols)} features, {train.height:,} training rows, {infer.height} inference rows")

# time-based holdout: last 60 dates for validation
dates = train["date"].unique().sort()
split_date = dates[-60] # validation holdout
tr = train.filter(pl.col("date") < split_date) # filter up to last training_date
va = train.filter(pl.col("date") >= split_date) # validation date and beyond

preds = {"id": infer["id"]} # predictions

for target in ["target_10d", "target_30d"]: # extract the target variables 10d and 30d
    tr_t = tr.drop_nulls(subset=[target]) # clean training data
    va_t = va.drop_nulls(subset=[target]) # clean val/test data for Nan's

    model = HistGradientBoostingRegressor(
        max_iter=500,
        learning_rate=0.02,
        max_leaf_nodes=31,
        l2_regularization=2.0,
        early_stopping=True,
        n_iter_no_change=20,
        validation_fraction=0.1,
        random_state=42,
    )
    model.fit(tr_t[feature_cols].to_numpy(), tr_t[target].to_numpy()) # fit the model on training, converted to numpy arrays

    val_pred = model.predict(va_t[feature_cols].to_numpy()) # prediction of 10d and 30d
    corr, _ = spearmanr(va_t[target].to_numpy(), val_pred) # compare prediction from val and actual val target
    print(f"{target}: holdout Spearman = {corr:.4f}")

    # retrain on all data before predicting the live universe
    full = train.drop_nulls(subset=[target])
    model.fit(full[feature_cols].to_numpy(), full[target].to_numpy())
    raw = model.predict(infer[feature_cols].to_numpy())

    horizon = target.replace("target", "pred")
    preds[horizon] = pl.Series(raw).rank() / len(raw)  # rank-normalize to (0, 1]

out = pl.DataFrame(preds)
out.write_parquet(OUT_DIR / "model_1.parquet")
print(f"\nWrote {OUT_DIR / 'model_1.parquet'} ({out.height} assets)")
print(out.head())
