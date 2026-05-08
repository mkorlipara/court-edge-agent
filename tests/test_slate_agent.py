"""Tests for the slate analysis agent."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from court_edge_agent.agents.slate_agent import run_slate_analysis


@pytest.mark.asyncio
async def test_empty_slate_returns_error() -> None:
    with patch("court_edge_agent.agents.slate_agent.fetch_todays_slate", return_value=[]):
        result = await run_slate_analysis(game_date="2025-04-10")
    assert result == {"error": "No games scheduled", "date": "2025-04-10"}


@pytest.mark.asyncio
async def test_no_stored_lines_returns_empty_picks() -> None:
    slate = [
        {
            "game_id": "1",
            "game_date": "2025-04-10",
            "home_team": "NYK",
            "away_team": "PHI",
            "status": "scheduled",
        }
    ]

    with (
        patch("court_edge_agent.agents.slate_agent.fetch_todays_slate", return_value=slate),
        patch("court_edge_agent.agents.slate_agent.get_team_roster", return_value=["Jalen Brunson"]),
        patch("court_edge_agent.agents.slate_agent._player_has_logs", return_value=True),
        patch("court_edge_agent.agents.slate_agent.load_prop_lines", return_value=pd.DataFrame()),
        patch("court_edge_agent.agents.slate_agent.load_models", return_value={}),
    ):
        result = await run_slate_analysis(game_date="2025-04-10")

    assert result["top_picks"] == []
    assert "scripts/fetch_odds.py" in str(result.get("note", ""))


@pytest.mark.asyncio
async def test_no_candidate_logs_returns_specific_note() -> None:
    slate = [
        {
            "game_id": "1",
            "game_date": "2025-04-10",
            "home_team": "NYK",
            "away_team": "PHI",
            "status": "scheduled",
        }
    ]

    with (
        patch("court_edge_agent.agents.slate_agent.fetch_todays_slate", return_value=slate),
        patch("court_edge_agent.agents.slate_agent.get_team_roster", return_value=["Jalen Brunson"]),
        patch("court_edge_agent.agents.slate_agent._player_has_logs", return_value=False),
    ):
        result = await run_slate_analysis(game_date="2025-04-10")

    assert result["top_picks"] == []
    assert "ingest_player_logs.py" in str(result.get("note", ""))


@pytest.mark.asyncio
async def test_ranking_by_abs_edge() -> None:
    slate = [
        {
            "game_id": "1",
            "game_date": "2025-04-10",
            "home_team": "NYK",
            "away_team": "PHI",
            "status": "scheduled",
        }
    ]

    def _prop_line(player_name: str, game_date: str, market: str) -> pd.DataFrame:
        return pd.DataFrame([{"line": 20.0}])

    def _predict(player_name, game_date, market, opponent, home_away, prop_line, models):
        projections = {
            ("Jalen Brunson", "points"): 25.0,   # edge +5
            ("Jalen Brunson", "rebounds"): 18.0,  # edge -2
            ("Joel Embiid", "points"): 28.0,      # edge +8
            ("Joel Embiid", "rebounds"): 21.0,    # edge +1 (filtered by min_edge=1.5? no 1)
        }
        return SimpleNamespace(projection=projections[(player_name, market)])

    async def _live_predict(**kwargs):
        return SimpleNamespace(
            projection=kwargs["prop_line"] + 0.1,
            confidence="medium",
            explanation=["x", "y"],
        )

    with (
        patch("court_edge_agent.agents.slate_agent.fetch_todays_slate", return_value=slate),
        patch(
            "court_edge_agent.agents.slate_agent.get_team_roster",
            side_effect=[["Jalen Brunson"], ["Joel Embiid"]],
        ),
        patch("court_edge_agent.agents.slate_agent._player_has_logs", return_value=True),
        patch("court_edge_agent.agents.slate_agent.load_prop_lines", side_effect=_prop_line),
        patch("court_edge_agent.agents.slate_agent.predict", side_effect=_predict),
        patch("court_edge_agent.agents.slate_agent.live_predict", side_effect=_live_predict),
        patch("court_edge_agent.agents.slate_agent.load_models", return_value={}),
    ):
        result = await run_slate_analysis(
            game_date="2025-04-10",
            markets=["points", "rebounds"],
            min_edge=1.5,
            top_n=3,
        )

    edges = [abs(p["edge"]) for p in result["top_picks"]]
    assert edges == sorted(edges, reverse=True)


@pytest.mark.asyncio
async def test_top_picks_use_llm() -> None:
    slate = [
        {
            "game_id": "1",
            "game_date": "2025-04-10",
            "home_team": "NYK",
            "away_team": "PHI",
            "status": "scheduled",
        }
    ]

    def _predict(player_name, game_date, market, opponent, home_away, prop_line, models):
        base = {
            ("A", "points"): 30.0,
            ("A", "rebounds"): 27.0,
            ("B", "points"): 26.0,
            ("B", "rebounds"): 23.0,
        }
        return SimpleNamespace(projection=base[(player_name, market)])

    live_mock = AsyncMock(
        return_value=SimpleNamespace(
            projection=30.0, confidence="medium", explanation=["x", "y"]
        )
    )

    with (
        patch("court_edge_agent.agents.slate_agent.fetch_todays_slate", return_value=slate),
        patch(
            "court_edge_agent.agents.slate_agent.get_team_roster",
            side_effect=[["A"], ["B"]],
        ),
        patch("court_edge_agent.agents.slate_agent._player_has_logs", return_value=True),
        patch(
            "court_edge_agent.agents.slate_agent.load_prop_lines",
            return_value=pd.DataFrame([{"line": 20.0}]),
        ),
        patch("court_edge_agent.agents.slate_agent.predict", side_effect=_predict),
        patch("court_edge_agent.agents.slate_agent.live_predict", live_mock),
        patch("court_edge_agent.agents.slate_agent.load_models", return_value={}),
    ):
        await run_slate_analysis(
            game_date="2025-04-10",
            markets=["points", "rebounds"],
            min_edge=1.5,
            top_n=2,
        )

    assert live_mock.await_count == 2


@pytest.mark.asyncio
async def test_concurrency_cap() -> None:
    slate = [
        {
            "game_id": "1",
            "game_date": "2025-04-10",
            "home_team": "NYK",
            "away_team": "PHI",
            "status": "scheduled",
        }
    ]

    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def _live_predict(**kwargs):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return SimpleNamespace(
            projection=kwargs["prop_line"] + 2.0,
            confidence="medium",
            explanation=["x", "y"],
        )

    with (
        patch("court_edge_agent.agents.slate_agent.fetch_todays_slate", return_value=slate),
        patch(
            "court_edge_agent.agents.slate_agent.get_team_roster",
            side_effect=[["P1", "P2", "P3", "P4"], ["P5"]],
        ),
        patch("court_edge_agent.agents.slate_agent._player_has_logs", return_value=True),
        patch(
            "court_edge_agent.agents.slate_agent.load_prop_lines",
            return_value=pd.DataFrame([{"line": 20.0}]),
        ),
        patch(
            "court_edge_agent.agents.slate_agent.predict",
            return_value=SimpleNamespace(projection=23.0),
        ),
        patch("court_edge_agent.agents.slate_agent.live_predict", side_effect=_live_predict),
        patch("court_edge_agent.agents.slate_agent.load_models", return_value={}),
    ):
        await run_slate_analysis(
            game_date="2025-04-10",
            markets=["points"],
            min_edge=1.0,
            top_n=5,
        )

    assert max_active <= 3
