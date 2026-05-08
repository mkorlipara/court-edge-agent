"""Tests for the MCP server tools — all external I/O is mocked."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_live_projection(**overrides):
    """Build a minimal LiveProjection-like MagicMock."""
    from court_edge_agent.agents.live_predict import LiveProjection

    defaults = dict(
        player_name="Jalen Brunson",
        game_date=date(2025, 4, 10),
        market="points",
        projection=27.4,
        prop_line=26.5,
        edge=0.9,
        lean="over",
        confidence="medium",
        explanation=["Projects 27.4 points in a favourable matchup."],
        source="llm",
    )
    defaults.update(overrides)
    return LiveProjection(**defaults)


# ---------------------------------------------------------------------------
# Tool 1: get_player_recent_games
# ---------------------------------------------------------------------------


class TestGetPlayerRecentGames:
    def test_player_not_found_in_nba_api_returns_error(self) -> None:
        """search_player_id returns None → clean error dict."""
        from court_edge_agent.mcp_server import get_player_recent_games

        with patch(
            "court_edge_agent.mcp_server.search_player_id",
            return_value=None,
        ):
            result = get_player_recent_games("Unknown Player XYZ")

        assert "error" in result
        assert "ingestion" in result["error"].lower() or "not found" in result["error"].lower()

    def test_player_found_but_empty_db_returns_error(self) -> None:
        """search_player_id succeeds but DB returns empty DataFrame → error dict."""
        from court_edge_agent.mcp_server import get_player_recent_games

        with (
            patch("court_edge_agent.mcp_server.search_player_id", return_value=1628384),
            patch(
                "court_edge_agent.mcp_server.load_game_logs",
                return_value=pd.DataFrame(),
            ),
        ):
            result = get_player_recent_games("Jalen Brunson")

        assert "error" in result

    def test_returns_correct_schema_when_data_exists(self) -> None:
        """When game logs exist, returns expected keys and respects n_games."""
        from court_edge_agent.mcp_server import get_player_recent_games

        sample_df = pd.DataFrame(
            [
                {
                    "game_date": date(2025, 3, d),
                    "matchup": "NYK vs. BOS",
                    "points": 25.0,
                    "rebounds": 3.0,
                    "assists": 7.0,
                    "threes_made": 3.0,
                    "minutes": 34.0,
                }
                for d in range(1, 8)
            ]
        )

        with (
            patch("court_edge_agent.mcp_server.search_player_id", return_value=1628384),
            patch("court_edge_agent.mcp_server.load_game_logs", return_value=sample_df),
        ):
            result = get_player_recent_games("Jalen Brunson", n_games=5)

        assert "error" not in result
        assert result["n"] == 5
        assert len(result["games"]) == 5
        first = result["games"][0]
        assert set(first.keys()) == {
            "game_date",
            "matchup",
            "points",
            "rebounds",
            "assists",
            "threes_made",
            "minutes",
        }


# ---------------------------------------------------------------------------
# Tool 2: get_player_projection — schema test
# ---------------------------------------------------------------------------


class TestGetPlayerProjection:
    @pytest.mark.asyncio
    async def test_response_has_all_required_keys(self) -> None:
        """mock live_predict and verify the returned dict has all required keys."""
        from court_edge_agent.mcp_server import get_player_projection

        mock_proj = _make_live_projection()

        with patch(
            "court_edge_agent.mcp_server.live_predict",
            new=AsyncMock(return_value=mock_proj),
        ):
            result = await get_player_projection(
                player_name="Jalen Brunson",
                game_date="2025-04-10",
                market="points",
                opponent="BOS",
                home_away="HOME",
                prop_line=26.5,
            )

        required_keys = {
            "player_name",
            "game_date",
            "market",
            "projection",
            "prop_line",
            "edge",
            "lean",
            "confidence",
            "explanation",
            "source",
        }
        assert required_keys.issubset(result.keys()), (
            f"Missing keys: {required_keys - result.keys()}"
        )

    @pytest.mark.asyncio
    async def test_invalid_date_returns_error(self) -> None:
        from court_edge_agent.mcp_server import get_player_projection

        result = await get_player_projection(
            player_name="Jalen Brunson",
            game_date="not-a-date",
            market="points",
            opponent="BOS",
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_market_returns_error(self) -> None:
        from court_edge_agent.mcp_server import get_player_projection

        result = await get_player_projection(
            player_name="Jalen Brunson",
            game_date="2025-04-10",
            market="touchdowns",
            opponent="BOS",
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_value_error_from_live_predict_returns_error_dict(self) -> None:
        from court_edge_agent.mcp_server import get_player_projection

        with patch(
            "court_edge_agent.mcp_server.live_predict",
            new=AsyncMock(side_effect=ValueError("Player not found: 'Ghost Player'")),
        ):
            result = await get_player_projection(
                player_name="Ghost Player",
                game_date="2025-04-10",
                market="points",
                opponent="BOS",
            )
        assert "error" in result
        assert "Ghost Player" in result["error"]


# ---------------------------------------------------------------------------
# Tool 3: get_prop_edges — no stored lines → empty list
# ---------------------------------------------------------------------------


class TestGetPropEdges:
    @pytest.mark.asyncio
    async def test_no_stored_lines_returns_empty_list(self) -> None:
        """When load_prop_lines always returns an empty DF, result is []."""
        from court_edge_agent.mcp_server import get_prop_edges

        with patch(
            "court_edge_agent.mcp_server.load_prop_lines",
            return_value=pd.DataFrame(),
        ):
            result = await get_prop_edges(
                player_market_pairs=[
                    {"player": "Jalen Brunson", "market": "points"},
                    {"player": "Jayson Tatum", "market": "rebounds"},
                ],
                game_date="2025-04-10",
                opponent_map={"Jalen Brunson": "BOS", "Jayson Tatum": "NYK"},
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_date_returns_empty_list(self) -> None:
        from court_edge_agent.mcp_server import get_prop_edges

        result = await get_prop_edges(
            player_market_pairs=[{"player": "Jalen Brunson", "market": "points"}],
            game_date="bad-date",
            opponent_map={},
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_sorted_by_abs_edge_descending(self) -> None:
        """When stored lines exist, results are sorted by |edge| desc."""
        from court_edge_agent.mcp_server import get_prop_edges
        from court_edge_agent.models.predict import Projection

        def _mock_prop_line(player_name, game_date, market, **kwargs):
            lines = {
                ("Jalen Brunson", "points"): 26.5,
                ("Jayson Tatum", "rebounds"): 8.0,
            }
            line_val = lines.get((player_name, market))
            if line_val is None:
                return pd.DataFrame()
            return pd.DataFrame([{"line": line_val}])

        def _mock_predict(player_name, game_date, market, opponent, home_away, prop_line, **kw):
            projections = {
                "Jalen Brunson": 30.0,  # edge = 3.5
                "Jayson Tatum": 7.0,    # edge = -1.0
            }
            proj_val = projections[player_name]
            return Projection(
                player_name=player_name,
                game_date=game_date,
                market=market,
                projection=proj_val,
                prop_line=prop_line,
                edge=round(proj_val - prop_line, 2),
                lean="over" if proj_val > prop_line else "under",
                confidence="medium",
                explanation=[],
            )

        with (
            patch("court_edge_agent.mcp_server.load_prop_lines", side_effect=_mock_prop_line),
            patch("court_edge_agent.mcp_server.predict", side_effect=_mock_predict),
            patch("court_edge_agent.mcp_server.load_models", return_value={}),
        ):
            result = await get_prop_edges(
                player_market_pairs=[
                    {"player": "Jalen Brunson", "market": "points"},
                    {"player": "Jayson Tatum", "market": "rebounds"},
                ],
                game_date="2025-04-10",
                opponent_map={"Jalen Brunson": "BOS", "Jayson Tatum": "NYK"},
            )

        assert len(result) == 2
        assert abs(result[0]["edge"]) >= abs(result[1]["edge"])
        assert result[0]["player"] == "Jalen Brunson"


# ---------------------------------------------------------------------------
# Tool 4: run_backtest — no features → error dict
# ---------------------------------------------------------------------------


class TestRunBacktest:
    def test_no_features_returns_error(self) -> None:
        """When the features table is empty, return a clean error dict."""
        from court_edge_agent.mcp_server import run_backtest

        with patch(
            "court_edge_agent.mcp_server.load_features",
            return_value=pd.DataFrame(),
        ):
            result = run_backtest(season="2024-25")

        assert "error" in result
        assert "features" in result["error"].lower() or "build_features" in result["error"]

    def test_returns_correct_schema_when_data_exists(self) -> None:
        """Verify result dict has 'season', 'cutoff', 'test_rows', 'results'."""
        from court_edge_agent.mcp_server import run_backtest

        dummy_features = pd.DataFrame(
            [{"game_date": "2025-01-01", "player_id": 1, "season": "2024-25"}]
        )
        dummy_test = pd.DataFrame(
            [{"game_date": "2025-02-01", "player_id": 1, "season": "2024-25"}]
        )
        dummy_report = pd.DataFrame(
            [{"market": "points", "model_type": "hgb", "mae": 3.1, "rmse": 4.2, "n": 50}]
        )

        with (
            patch("court_edge_agent.mcp_server.load_features", return_value=dummy_features),
            patch(
                "court_edge_agent.mcp_server.date_split",
                return_value=(dummy_features, dummy_test),
            ),
            patch("court_edge_agent.mcp_server.load_models", return_value={}),
            patch(
                "court_edge_agent.mcp_server.full_evaluation_report",
                return_value=dummy_report,
            ),
        ):
            result = run_backtest(season="2024-25", cutoff_date="2025-01-15")

        assert result["season"] == "2024-25"
        assert result["cutoff"] == "2025-01-15"
        assert result["test_rows"] == 1
        assert isinstance(result["results"], list)
