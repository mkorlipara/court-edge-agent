"""Model evaluation: MAE, RMSE, time-series CV, and rolling baseline comparisons."""

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.model_selection import TimeSeriesSplit

from court_edge_agent.common.logging import get_logger
from court_edge_agent.models.baseline import HGBModel, RidgeModel, RollingAverageBaseline

logger = get_logger(__name__)

STAT_MARKETS = ("points", "rebounds", "assists", "threes_made")

# Union type accepted by evaluation helpers
AnyModel = RidgeModel | HGBModel


def evaluate_model(
    model: AnyModel,
    test_df: pd.DataFrame,
) -> dict[str, float]:
    """Return MAE and RMSE for a fitted model on the test set."""
    target = model.target
    valid = test_df.dropna(subset=[target])
    if valid.empty:
        logger.warning("No valid test rows for target '%s'", target)
        return {}
    y_true = valid[target].to_numpy()
    y_pred = model.predict(valid)
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(root_mean_squared_error(y_true, y_pred)),
        "n": len(valid),
    }


def evaluate_rolling_baseline(
    test_df: pd.DataFrame,
    target: str,
    window: int = 5,
) -> dict[str, float]:
    """Evaluate the rolling-average baseline on the test set."""
    baseline = RollingAverageBaseline(window=window)
    valid = test_df.dropna(subset=[target])
    if valid.empty:
        return {}
    y_true = valid[target].to_numpy()
    y_pred = baseline.predict_batch(valid, target).reindex(valid.index).to_numpy()  # type: ignore[arg-type]
    mask = ~np.isnan(y_pred)
    y_true, y_pred = y_true[mask], y_pred[mask]
    if len(y_true) == 0:
        return {}
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(root_mean_squared_error(y_true, y_pred)),
        "n": int(len(y_true)),
    }


def timeseries_cv_evaluation(
    features_df: pd.DataFrame,
    n_splits: int = 5,
) -> pd.DataFrame:
    """Time-series cross-validation using HGB models.

    Uses :class:`sklearn.model_selection.TimeSeriesSplit` to create folds that
    respect temporal order — training always precedes the test window.  This
    replaces the single-cutoff evaluation as the primary metric.

    Args:
        features_df: Full feature DataFrame sorted by game_date.
        n_splits: Number of CV splits (default 5).

    Returns:
        DataFrame with columns: market, mae_mean, mae_std — one row per market.
    """
    df = features_df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values("game_date").reset_index(drop=True)

    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_records: list[dict] = []

    for fold, (train_idx, test_idx) in enumerate(tscv.split(df)):
        train_fold = df.iloc[train_idx]
        test_fold = df.iloc[test_idx]

        for market in STAT_MARKETS:
            if market not in train_fold.columns or market not in test_fold.columns:
                continue
            if train_fold[market].dropna().empty:
                continue

            model: HGBModel = HGBModel(target=market)  # type: ignore[arg-type]
            model.fit(train_fold)
            metrics = evaluate_model(model, test_fold)
            if metrics:
                fold_records.append({
                    "fold": fold,
                    "market": market,
                    "mae": metrics["mae"],
                    "rmse": metrics["rmse"],
                    "n": metrics["n"],
                })

    if not fold_records:
        logger.warning("No fold results produced in time-series CV")
        return pd.DataFrame(columns=["market", "mae_mean", "mae_std"])

    cv_df = pd.DataFrame(fold_records)
    summary = (
        cv_df.groupby("market")["mae"]
        .agg(["mean", "std"])
        .reset_index()
        .rename(columns={"mean": "mae_mean", "std": "mae_std"})
    )
    logger.info(
        "Time-series CV (%d splits):\n%s",
        n_splits,
        summary.to_string(index=False),
    )
    return summary


def full_evaluation_report(
    models: dict[str, AnyModel],
    test_df: pd.DataFrame,
) -> pd.DataFrame:
    """Produce a comparison table: model vs. rolling baselines for each market.

    Returns a DataFrame with columns:
        market | model_type | mae | rmse | n
    """
    records = []
    for market in STAT_MARKETS:
        if market not in test_df.columns:
            continue

        if market in models:
            model_metrics = evaluate_model(models[market], test_df)
            model_type = "hgb" if isinstance(models[market], HGBModel) else "ridge"
            records.append({
                "market": market,
                "model_type": model_type,
                **model_metrics,
            })

        for w in (5, 10):
            roll_metrics = evaluate_rolling_baseline(test_df, market, window=w)
            if roll_metrics:
                records.append({
                    "market": market,
                    "model_type": f"rolling_{w}",
                    **roll_metrics,
                })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values(["market", "mae"]).reset_index(drop=True)
    return df
