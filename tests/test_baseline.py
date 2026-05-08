"""Tests for baseline model training, evaluation, and prediction."""

import numpy as np
import pandas as pd
import pytest

from court_edge_agent.models.baseline import HGBModel, RidgeModel, RollingAverageBaseline
from court_edge_agent.models.evaluate import (
    evaluate_model,
    evaluate_rolling_baseline,
    timeseries_cv_evaluation,
)
from court_edge_agent.models.train import date_split


def _make_feature_df(n: int = 40) -> pd.DataFrame:
    """Create a synthetic feature DataFrame large enough to split and train.

    Column names match REGRESSION_FEATURE_COLS exactly, including the 'threes'
    prefix (not 'threes_made') for rolling/season-avg columns, plus the four
    opponent defensive columns added in Milestone 2.
    """
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-10-01", periods=n, freq="2D")

    rows = []
    for _i, d in enumerate(dates):
        row: dict = {
            "player_id": 1,
            "player_name": "Test Player",
            "game_date": d.date(),
            "season": "2024-25",
            "opponent": "LAL",
            "home_away": "HOME",
            "days_rest": 2,
            "back_to_back_flag": 0,
        }
        # Rolling and season-avg columns — use correct prefix for each stat
        for stat, target_col in (
            ("points", "points"),
            ("rebounds", "rebounds"),
            ("assists", "assists"),
            ("threes", "threes_made"),   # feature prefix is "threes"; target is "threes_made"
            ("minutes", "minutes"),
        ):
            val = rng.uniform(5, 40)
            # target column (actual game value)
            row[target_col] = val
            for w in (3, 5, 10):
                row[f"rolling_{w}_{stat}"] = val + rng.normal(0, 1)
            row[f"season_avg_{stat}_to_date"] = val + rng.normal(0, 0.5)

        # Opponent defensive features
        row["opp_pts_allowed"] = float(rng.uniform(20, 30))
        row["opp_reb_allowed"] = float(rng.uniform(4, 9))
        row["opp_ast_allowed"] = float(rng.uniform(3, 7))
        row["opp_3pm_allowed"] = float(rng.uniform(1, 4))

        rows.append(row)

    return pd.DataFrame(rows)


class TestRollingAverageBaseline:
    def test_predict_single(self) -> None:
        df = _make_feature_df(10)
        baseline = RollingAverageBaseline(window=5)
        row = df.iloc[9]
        pred = baseline.predict_single(row, "points")
        assert pred is not None
        assert pred > 0

    def test_predict_batch_length(self) -> None:
        df = _make_feature_df(20)
        baseline = RollingAverageBaseline(window=5)
        preds = baseline.predict_batch(df, "points")
        assert len(preds) == len(df)


class TestRidgeModel:
    def test_fit_and_predict(self) -> None:
        df = _make_feature_df(40)
        model = RidgeModel(target="points")
        model.fit(df)
        preds = model.predict(df)
        assert len(preds) == len(df)
        assert all(np.isfinite(preds))

    def test_predict_single(self) -> None:
        df = _make_feature_df(40)
        model = RidgeModel(target="points")
        model.fit(df)
        pred = model.predict_single(df.iloc[0])
        assert np.isfinite(pred)

    def test_predict_before_fit_raises(self) -> None:
        model = RidgeModel(target="points")
        with pytest.raises(RuntimeError, match="not fitted"):
            model.predict(pd.DataFrame([{"points": 1}]))


class TestHGBModel:
    def test_fit_and_predict(self) -> None:
        df = _make_feature_df(40)
        model = HGBModel(target="points")
        model.fit(df)
        preds = model.predict(df)
        assert len(preds) == len(df)
        assert all(np.isfinite(preds))

    def test_predict_single(self) -> None:
        df = _make_feature_df(40)
        model = HGBModel(target="points")
        model.fit(df)
        pred = model.predict_single(df.iloc[0])
        assert np.isfinite(pred)

    def test_predict_before_fit_raises(self) -> None:
        model = HGBModel(target="points")
        with pytest.raises(RuntimeError, match="not fitted"):
            model.predict(pd.DataFrame([{"points": 1}]))

    def test_handles_nan_features_natively(self) -> None:
        """HGB must produce finite predictions even when opp_* features are NaN."""
        df = _make_feature_df(40)
        # Inject NaN into all opp columns to simulate early-season rows
        for col in ("opp_pts_allowed", "opp_reb_allowed", "opp_ast_allowed", "opp_3pm_allowed"):
            df[col] = np.nan
        model = HGBModel(target="points")
        model.fit(df)
        preds = model.predict(df)
        assert all(np.isfinite(preds))

    def test_all_markets(self) -> None:
        df = _make_feature_df(50)
        for market in ("points", "rebounds", "assists", "threes_made"):
            model = HGBModel(target=market)  # type: ignore[arg-type]
            model.fit(df)
            preds = model.predict(df)
            assert len(preds) == len(df)


class TestDateSplit:
    def test_split_sizes(self) -> None:
        df = _make_feature_df(40)
        # Dates span ~80 days from 2024-10-01; use mid-point
        train, test = date_split(df, "2024-11-10")
        assert len(train) > 0
        assert len(test) > 0
        assert len(train) + len(test) == len(df)

    def test_no_overlap(self) -> None:
        df = _make_feature_df(40)
        train, test = date_split(df, "2024-11-10")
        max_train = max(train["game_date"])
        min_test = min(test["game_date"])
        assert min_test >= max_train


class TestEvaluation:
    def test_evaluate_ridge_returns_mae_rmse(self) -> None:
        df = _make_feature_df(40)
        model = RidgeModel(target="points")
        model.fit(df)
        metrics = evaluate_model(model, df)
        assert "mae" in metrics
        assert "rmse" in metrics
        assert metrics["mae"] >= 0
        assert metrics["rmse"] >= metrics["mae"]

    def test_evaluate_hgb_returns_mae_rmse(self) -> None:
        df = _make_feature_df(40)
        model = HGBModel(target="points")
        model.fit(df)
        metrics = evaluate_model(model, df)
        assert "mae" in metrics
        assert "rmse" in metrics
        assert metrics["mae"] >= 0

    def test_evaluate_rolling_baseline(self) -> None:
        df = _make_feature_df(20)
        metrics = evaluate_rolling_baseline(df, "points", window=5)
        assert "mae" in metrics
        assert metrics["mae"] >= 0


class TestTimeSeriesCV:
    def test_returns_dataframe_with_expected_columns(self) -> None:
        df = _make_feature_df(60)
        result = timeseries_cv_evaluation(df, n_splits=3)
        assert isinstance(result, pd.DataFrame)
        assert "market" in result.columns
        assert "mae_mean" in result.columns
        assert "mae_std" in result.columns

    def test_all_markets_present(self) -> None:
        df = _make_feature_df(80)
        result = timeseries_cv_evaluation(df, n_splits=3)
        for market in ("points", "rebounds", "assists", "threes_made"):
            assert market in result["market"].values, f"Missing market: {market}"

    def test_mae_mean_is_positive(self) -> None:
        df = _make_feature_df(60)
        result = timeseries_cv_evaluation(df, n_splits=3)
        assert (result["mae_mean"] >= 0).all()
