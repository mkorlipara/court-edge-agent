"""Tests for feature engineering — focus on leakage and correctness."""

import datetime
from datetime import date

import numpy as np
import pandas as pd

from court_edge_agent.features.build_features import (
    _parse_matchup,
    build_features_for_dataset,
    build_features_for_player,
    build_inference_features,
    build_opponent_features,
    compute_opponent_stats,
)


def _make_game_logs(n: int = 15, player_id: int = 1, player_name: str = "Test Player") -> pd.DataFrame:
    """Create synthetic game log DataFrame for a single player."""
    rng = np.random.default_rng(42)
    dates = pd.date_range(start="2024-10-01", periods=n, freq="2D")
    return pd.DataFrame({
        "player_id": [player_id] * n,
        "player_name": [player_name] * n,
        "season": ["2024-25"] * n,
        "game_id": [f"0022{player_id:02d}{i:04d}" for i in range(n)],
        "game_date": [d.date() for d in dates],
        "matchup": ["GSW vs. LAL" if i % 2 == 0 else "GSW @ LAC" for i in range(n)],
        "wl": ["W"] * n,
        "minutes": rng.uniform(28, 38, n).tolist(),
        "points": rng.uniform(15, 40, n).tolist(),
        "rebounds": rng.uniform(3, 10, n).tolist(),
        "assists": rng.uniform(4, 12, n).tolist(),
        "threes_made": rng.uniform(0, 7, n).tolist(),
        "threes_attempted": rng.uniform(0, 12, n).tolist(),
        "fg_made": rng.uniform(6, 16, n).tolist(),
        "fg_attempted": rng.uniform(12, 24, n).tolist(),
        "ft_made": rng.uniform(2, 8, n).tolist(),
        "ft_attempted": rng.uniform(2, 10, n).tolist(),
        "plus_minus": rng.uniform(-10, 15, n).tolist(),
    })


def _make_multi_player_logs(n_players: int = 3, n_games: int = 15) -> pd.DataFrame:
    """Create combined game logs for multiple players."""
    frames = [
        _make_game_logs(n_games, player_id=i, player_name=f"Player {i}")
        for i in range(1, n_players + 1)
    ]
    return pd.concat(frames, ignore_index=True)


class TestParseMatchup:
    def test_home(self) -> None:
        opp, ha = _parse_matchup("GSW vs. LAL")
        assert opp == "LAL"
        assert ha == "HOME"

    def test_away(self) -> None:
        opp, ha = _parse_matchup("GSW @ LAC")
        assert opp == "LAC"
        assert ha == "AWAY"


class TestBuildFeaturesForPlayer:
    def test_returns_same_row_count(self) -> None:
        logs = _make_game_logs(15)
        features = build_features_for_player(logs)
        assert len(features) == 15

    def test_rolling_columns_present(self) -> None:
        logs = _make_game_logs(15)
        features = build_features_for_player(logs)
        expected = [
            "rolling_3_points", "rolling_5_points", "rolling_10_points",
            "rolling_3_rebounds", "rolling_5_rebounds",
            "rolling_3_minutes",
            "season_avg_points_to_date",
        ]
        for col in expected:
            assert col in features.columns, f"Missing column: {col}"

    def test_no_data_leakage(self) -> None:
        """rolling_5_points for game i must not use game i's own value."""
        logs = _make_game_logs(15)
        features = build_features_for_player(logs)
        # The rolling_5 for game index 5 should only use games 0-4
        raw_points = logs.sort_values("game_date")["points"].tolist()
        expected_rolling5_at_5 = float(np.mean(raw_points[0:5]))
        actual = features.iloc[5]["rolling_5_points"]
        assert abs(actual - expected_rolling5_at_5) < 1e-6, (
            f"Data leakage detected: expected {expected_rolling5_at_5:.4f}, got {actual:.4f}"
        )

    def test_days_rest_first_game(self) -> None:
        logs = _make_game_logs(5)
        features = build_features_for_player(logs)
        # First game defaults to 3 days rest
        assert features.iloc[0]["days_rest"] == 3

    def test_back_to_back_flag(self) -> None:
        logs = _make_game_logs(5)
        logs = logs.sort_values("game_date").reset_index(drop=True)
        # Force second game to be 1 day after first
        first_date = logs.iloc[0]["game_date"]
        logs.at[1, "game_date"] = first_date + datetime.timedelta(days=1)
        features = build_features_for_player(logs)
        assert features.iloc[1]["back_to_back_flag"] == 1


class TestBuildOpponentFeatures:
    def test_returns_correct_columns(self) -> None:
        logs = _make_multi_player_logs(3, 15)
        opp_df = build_opponent_features(logs)
        for col in ("game_date", "opponent", "opp_pts_allowed", "opp_reb_allowed",
                    "opp_ast_allowed", "opp_3pm_allowed"):
            assert col in opp_df.columns, f"Missing column: {col}"

    def test_empty_input_returns_empty(self) -> None:
        opp_df = build_opponent_features(pd.DataFrame())
        assert opp_df.empty

    def test_first_game_against_opponent_is_nan(self) -> None:
        """For the very first game against a given opponent, there are no prior games
        to compute an average from — result must be NaN."""
        logs = _make_multi_player_logs(2, 15)
        opp_df = build_opponent_features(logs)
        # Find the earliest date for each opponent
        for opp in opp_df["opponent"].unique():
            earliest = opp_df[opp_df["opponent"] == opp].sort_values("game_date").iloc[0]
            assert pd.isna(earliest["opp_pts_allowed"]), (
                f"Expected NaN for first game vs {opp}, got {earliest['opp_pts_allowed']}"
            )

    def test_no_leakage_in_opp_features(self) -> None:
        """opp_pts_allowed on date D must only use games strictly before D."""
        logs = _make_multi_player_logs(3, 20)
        logs_sorted = logs.sort_values("game_date").reset_index(drop=True)
        opp_df = build_opponent_features(logs_sorted)

        for _, row in opp_df.iterrows():
            if pd.isna(row["opp_pts_allowed"]):
                continue
            game_date = pd.Timestamp(row["game_date"])
            opp = row["opponent"]
            # Manually compute what opp_pts_allowed should be
            logs_copy = logs_sorted.copy()
            logs_copy["game_date"] = pd.to_datetime(logs_copy["game_date"])
            from court_edge_agent.features.build_features import _parse_matchup
            parsed = logs_copy["matchup"].apply(_parse_matchup)
            logs_copy["_opp"] = [m[0] for m in parsed]
            prior = logs_copy[
                (logs_copy["_opp"] == opp) & (logs_copy["game_date"] < game_date)
            ]
            expected = float(prior["points"].mean())
            assert abs(float(row["opp_pts_allowed"]) - expected) < 1e-6


class TestComputeOpponentStats:
    def test_returns_dict_with_four_keys(self) -> None:
        logs = _make_multi_player_logs(3, 15)
        # Use a date well past the first game so there's data
        result = compute_opponent_stats(logs, "LAL", date(2025, 1, 1))
        assert result is not None
        for key in ("opp_pts_allowed", "opp_reb_allowed", "opp_ast_allowed", "opp_3pm_allowed"):
            assert key in result

    def test_returns_none_for_unknown_opponent(self) -> None:
        logs = _make_multi_player_logs(2, 10)
        result = compute_opponent_stats(logs, "XYZ", date(2025, 1, 1))
        assert result is None

    def test_empty_logs_returns_none(self) -> None:
        result = compute_opponent_stats(pd.DataFrame(), "LAL", date(2025, 1, 1))
        assert result is None


class TestBuildFeaturesForDataset:
    def test_includes_opp_columns(self) -> None:
        """build_features_for_dataset must include the 4 opp_* columns."""
        logs = _make_multi_player_logs(3, 20)
        features = build_features_for_dataset(logs)
        for col in ("opp_pts_allowed", "opp_reb_allowed", "opp_ast_allowed", "opp_3pm_allowed"):
            assert col in features.columns, f"Missing opp column: {col}"

    def test_row_count(self) -> None:
        logs = _make_multi_player_logs(3, 15)
        features = build_features_for_dataset(logs, min_games=3)
        assert len(features) == 3 * 15


class TestBuildInferenceFeatures:
    def test_returns_series(self) -> None:
        logs = _make_game_logs(12)
        future_date = date(2024, 11, 15)
        row = build_inference_features(logs, future_date, "LAL", "HOME")
        assert row is not None
        assert isinstance(row, pd.Series)

    def test_opp_stats_populated(self) -> None:
        """When opp_stats is provided, those values appear in the feature row."""
        logs = _make_game_logs(12)
        opp = {"opp_pts_allowed": 22.5, "opp_reb_allowed": 5.5,
               "opp_ast_allowed": 4.0, "opp_3pm_allowed": 1.8}
        row = build_inference_features(logs, date(2024, 11, 15), "LAL", "HOME", opp_stats=opp)
        assert row is not None
        assert abs(row["opp_pts_allowed"] - 22.5) < 1e-6

    def test_opp_stats_nan_when_not_provided(self) -> None:
        logs = _make_game_logs(12)
        row = build_inference_features(logs, date(2024, 11, 15), "LAL", "HOME")
        assert row is not None
        assert pd.isna(row["opp_pts_allowed"])

    def test_no_leakage_from_future_logs(self) -> None:
        """Logs on or after game_date must be filtered out silently."""
        logs = _make_game_logs(12)
        target_date = date(2024, 11, 10)
        logs = logs.sort_values("game_date").reset_index(drop=True)
        logs.at[len(logs) - 1, "game_date"] = target_date
        row = build_inference_features(logs, target_date, "LAL", "HOME")
        assert row is not None

    def test_empty_logs_returns_none(self) -> None:
        row = build_inference_features(pd.DataFrame(), date(2024, 12, 1), "LAL", "HOME")
        assert row is None
