"""Baseline models for player stat prediction.

Three baselines in increasing sophistication:
1. Last-N rolling average (pure heuristic, no training)
2. Ridge regression on rolling / season-avg features
3. HistGradientBoosting (HGB) — handles NaN natively, default production model
"""

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from court_edge_agent.common.logging import get_logger

logger = get_logger(__name__)

StatMarket = Literal["points", "rebounds", "assists", "threes_made"]

STAT_MARKETS: tuple[str, ...] = ("points", "rebounds", "assists", "threes_made")

# Maps stat market name → feature column prefix.
# "threes_made" is the market/target name but the feature columns use the
# shorter prefix "threes" (e.g. "rolling_5_threes", "season_avg_threes_to_date").
_MARKET_TO_PREFIX: dict[str, str] = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes_made": "threes",
}


def _feature_prefix(market: str) -> str:
    return _MARKET_TO_PREFIX.get(market, market)


# Feature columns fed into the regression model (must exist in feature matrix).
# Keep in sync with FEATURE_COLUMNS in build_features.py and the DB schema.
REGRESSION_FEATURE_COLS = [
    "rolling_3_points", "rolling_5_points", "rolling_10_points",
    "rolling_3_rebounds", "rolling_5_rebounds", "rolling_10_rebounds",
    "rolling_3_assists", "rolling_5_assists", "rolling_10_assists",
    "rolling_3_threes", "rolling_5_threes", "rolling_10_threes",
    "rolling_3_minutes", "rolling_5_minutes", "rolling_10_minutes",
    "season_avg_points_to_date", "season_avg_rebounds_to_date",
    "season_avg_assists_to_date", "season_avg_threes_to_date",
    "season_avg_minutes_to_date",
    "days_rest", "back_to_back_flag",
    # Opponent defensive context
    "opp_pts_allowed", "opp_reb_allowed", "opp_ast_allowed", "opp_3pm_allowed",
]


@dataclass
class RollingAverageBaseline:
    """Predict using the last-N game rolling average for the target stat.

    No training required. Used as a reference benchmark.
    """

    window: int = 5

    def predict_single(self, feature_row: pd.Series, target: StatMarket) -> float | None:
        prefix = _feature_prefix(target)
        col = f"rolling_{self.window}_{prefix}"
        val = feature_row.get(col)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            season_col = f"season_avg_{prefix}_to_date"
            val = feature_row.get(season_col)
        return float(val) if val is not None and not np.isnan(float(val)) else None

    def predict_batch(self, features_df: pd.DataFrame, target: StatMarket) -> pd.Series:
        prefix = _feature_prefix(target)
        col = f"rolling_{self.window}_{prefix}"
        season_col = f"season_avg_{prefix}_to_date"
        preds = features_df[col].astype(float).copy()
        mask = preds.isna()
        if mask.any() and season_col in features_df.columns:
            preds = preds.where(~mask, other=features_df[season_col].astype(float))
        return preds


@dataclass
class RidgeModel:
    """Ridge regression model for a single stat market.

    Wraps sklearn Ridge inside a Pipeline with StandardScaler to handle
    the different scales of rolling windows vs. binary flags.
    """

    target: StatMarket
    alpha: float = 1.0
    _pipeline: Pipeline = field(init=False, repr=False)
    _is_fitted: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._pipeline = Pipeline([
            # Median imputation handles NaN in early-season rolling windows
            # (e.g. rolling_10 is NaN for the first 9 games of a player).
            # strategy="median" is more robust than "mean" for skewed stat distributions.
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("ridge", Ridge(alpha=self.alpha)),
        ])

    def _get_feature_matrix(self, df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
        """Select feature columns present in the DataFrame."""
        available = [c for c in REGRESSION_FEATURE_COLS if c in df.columns]
        X = df[available].to_numpy(dtype=float, na_value=np.nan)
        return X, available

    def fit(self, features_df: pd.DataFrame) -> "RidgeModel":
        """Train on a feature DataFrame that includes target column."""
        train = features_df.dropna(subset=[self.target])
        if len(train) < 10:
            logger.warning(
                "Very few training samples (%d) for target '%s'", len(train), self.target
            )
        X, cols = self._get_feature_matrix(train)
        y = train[self.target].to_numpy()
        self._pipeline.fit(X, y)
        self._is_fitted = True
        logger.info(
            "Trained Ridge model for '%s' on %d samples (%d features)",
            self.target, len(train), len(cols),
        )
        return self

    def predict(self, features_df: pd.DataFrame) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("Model is not fitted. Call .fit() first.")
        X, _ = self._get_feature_matrix(features_df)
        return self._pipeline.predict(X)

    def predict_single(self, feature_row: pd.Series) -> float:
        df = pd.DataFrame([feature_row])
        return float(self.predict(df)[0])


@dataclass
class HGBModel:
    """HistGradientBoosting model for a single stat market.

    HGB handles NaN values natively — no imputation step required.
    This is the default production model replacing RidgeModel.
    """

    target: StatMarket
    _model: HistGradientBoostingRegressor = field(init=False, repr=False)
    _is_fitted: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._model = HistGradientBoostingRegressor(random_state=42)

    def _get_feature_matrix(self, df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
        """Select feature columns present in the DataFrame."""
        available = [c for c in REGRESSION_FEATURE_COLS if c in df.columns]
        X = df[available].to_numpy(dtype=float, na_value=np.nan)
        return X, available

    def fit(self, features_df: pd.DataFrame) -> "HGBModel":
        """Train on a feature DataFrame that includes the target column."""
        train = features_df.dropna(subset=[self.target])
        if len(train) < 10:
            logger.warning(
                "Very few training samples (%d) for target '%s'", len(train), self.target
            )
        X, cols = self._get_feature_matrix(train)
        y = train[self.target].to_numpy()
        self._model.fit(X, y)
        self._is_fitted = True
        logger.info(
            "Trained HGB model for '%s' on %d samples (%d features)",
            self.target, len(train), len(cols),
        )
        return self

    def predict(self, features_df: pd.DataFrame) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("Model is not fitted. Call .fit() first.")
        X, _ = self._get_feature_matrix(features_df)
        return self._model.predict(X)

    def predict_single(self, feature_row: pd.Series) -> float:
        df = pd.DataFrame([feature_row])
        return float(self.predict(df)[0])
