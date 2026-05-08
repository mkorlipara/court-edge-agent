"""Tests for the live_predict agent — mocks all external dependencies."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from court_edge_agent.agents.live_predict import LiveProjection, live_predict

# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

_PLAYER_CTX = {
    "recent_games": [
        {
            "date": "2025-03-30",
            "matchup": "NYK vs. PHI",
            "wl": "W",
            "points": 28.0,
            "rebounds": 3.0,
            "assists": 7.0,
            "threes_made": 4.0,
            "minutes": 35.0,
        }
    ],
    "season_avgs": {
        "points": 26.5,
        "rebounds": 3.2,
        "assists": 6.8,
        "threes_made": 3.1,
        "minutes": 34.0,
        "games_played": 65,
    },
    "vs_opponent": None,
}

_OPP_DEFENSE = {
    "team_name": "Philadelphia 76ers",
    "pts_allowed": 112.0,
    "reb_allowed": 44.0,
    "ast_allowed": 25.0,
    "drtg": 113.5,
    "drtg_rank": 22,
    "n_teams": 30,
}

_LLM_RESPONSE = {
    "projection": 27.5,
    "confidence": "medium",
    "lean": "over",
    "explanation": [
        "Brunson projects to 27.5 points based on recent form and a favorable matchup.",
        "Philadelphia ranks 22nd in defensive rating, allowing significant scoring.",
    ],
}


def _make_openai_mock(response_dict: dict) -> MagicMock:
    """Build a mock OpenAI client that returns response_dict as JSON."""
    choice = MagicMock()
    choice.message.content = json.dumps(response_dict)

    completion = MagicMock()
    completion.choices = [choice]

    client = MagicMock()
    client.chat.completions.create.return_value = completion

    return client


# ---------------------------------------------------------------------------
# Helpers for patching the full live_predict stack
# ---------------------------------------------------------------------------

def _patch_stack(
    *,
    player_id: int = 1628384,
    player_ctx: dict | None = None,
    opp_defense: dict | None = None,
    injury_report: dict | None = None,
    llm_response: dict | None = None,
    llm_raises: Exception | None = None,
):
    """Return a context manager dict of all patches needed for live_predict."""
    player_ctx = player_ctx or _PLAYER_CTX
    opp_defense = opp_defense or _OPP_DEFENSE
    injury_report = injury_report if injury_report is not None else {}
    llm_response = llm_response or _LLM_RESPONSE

    patches = {
        "search_player_id": patch(
            "court_edge_agent.agents.live_predict.search_player_id",
            return_value=player_id,
        ),
        "fetch_player_context": patch(
            "court_edge_agent.agents.live_predict.fetch_player_context",
            return_value=player_ctx,
        ),
        "fetch_opponent_defense": patch(
            "court_edge_agent.agents.live_predict.fetch_opponent_defense",
            return_value=opp_defense,
        ),
        "fetch_injury_report": patch(
            "court_edge_agent.agents.live_predict.fetch_injury_report",
            return_value=injury_report,
        ),
        "load_prop_lines": patch(
            "court_edge_agent.agents.live_predict.load_prop_lines",
            return_value=__import__("pandas").DataFrame(),
        ),
        "settings": patch(
            "court_edge_agent.agents.live_predict.settings",
            openai_api_key="sk-test",
            openai_model="gpt-4o",
            default_season="2024-25",
        ),
    }

    if llm_raises is not None:
        patches["openai"] = patch(
            "court_edge_agent.agents.live_predict.OpenAI",
            side_effect=llm_raises,
        )
    else:
        patches["openai"] = patch(
            "court_edge_agent.agents.live_predict.OpenAI",
            return_value=_make_openai_mock(llm_response),
        )

    return patches


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLivePredictResponseSchema:
    @pytest.mark.asyncio
    async def test_returns_live_projection_instance(self) -> None:
        patches = _patch_stack()
        with (
            patches["settings"],
            patches["search_player_id"],
            patches["fetch_player_context"],
            patches["fetch_opponent_defense"],
            patches["fetch_injury_report"],
            patches["load_prop_lines"],
            patches["openai"],
        ):
            result = await live_predict(
                player_name="Jalen Brunson",
                game_date=date(2025, 4, 1),
                market="points",  # type: ignore[arg-type]
                opponent="PHI",
                home_away="HOME",
                prop_line=26.5,
            )

        assert isinstance(result, LiveProjection)

    @pytest.mark.asyncio
    async def test_source_is_llm_on_success(self) -> None:
        patches = _patch_stack()
        with (
            patches["settings"],
            patches["search_player_id"],
            patches["fetch_player_context"],
            patches["fetch_opponent_defense"],
            patches["fetch_injury_report"],
            patches["load_prop_lines"],
            patches["openai"],
        ):
            result = await live_predict(
                player_name="Jalen Brunson",
                game_date=date(2025, 4, 1),
                market="points",  # type: ignore[arg-type]
                opponent="PHI",
                home_away="HOME",
                prop_line=26.5,
            )

        assert result.source == "llm"

    @pytest.mark.asyncio
    async def test_full_response_schema(self) -> None:
        patches = _patch_stack()
        with (
            patches["settings"],
            patches["search_player_id"],
            patches["fetch_player_context"],
            patches["fetch_opponent_defense"],
            patches["fetch_injury_report"],
            patches["load_prop_lines"],
            patches["openai"],
        ):
            result = await live_predict(
                player_name="Jalen Brunson",
                game_date=date(2025, 4, 1),
                market="points",  # type: ignore[arg-type]
                opponent="PHI",
                home_away="HOME",
                prop_line=26.5,
            )

        assert isinstance(result.projection, float)
        assert result.confidence in {"high", "medium", "low"}
        assert result.lean in {"over", "under", None}
        assert isinstance(result.explanation, list)
        assert len(result.explanation) >= 1
        assert all(isinstance(s, str) for s in result.explanation)
        assert result.player_name == "Jalen Brunson"
        assert result.market == "points"

    @pytest.mark.asyncio
    async def test_edge_computed_from_prop_line(self) -> None:
        patches = _patch_stack(llm_response={**_LLM_RESPONSE, "projection": 28.0})
        with (
            patches["settings"],
            patches["search_player_id"],
            patches["fetch_player_context"],
            patches["fetch_opponent_defense"],
            patches["fetch_injury_report"],
            patches["load_prop_lines"],
            patches["openai"],
        ):
            result = await live_predict(
                player_name="Jalen Brunson",
                game_date=date(2025, 4, 1),
                market="points",  # type: ignore[arg-type]
                opponent="PHI",
                home_away="HOME",
                prop_line=26.5,
            )

        assert result.edge == pytest.approx(1.5, abs=0.01)


class TestLivePredictFallback:
    @pytest.mark.asyncio
    async def test_source_is_hgb_fallback_when_openai_raises(self) -> None:
        mock_proj = MagicMock()
        mock_proj.player_name = "Jalen Brunson"
        mock_proj.game_date = date(2025, 4, 1)
        mock_proj.market = "points"
        mock_proj.projection = 25.0
        mock_proj.prop_line = 26.5
        mock_proj.edge = -1.5
        mock_proj.lean = "under"
        mock_proj.confidence = "medium"
        mock_proj.explanation = ["HGB fallback explanation."]

        patches = _patch_stack(llm_raises=RuntimeError("OpenAI down"))

        with (
            patches["settings"],
            patches["search_player_id"],
            patches["fetch_player_context"],
            patches["fetch_opponent_defense"],
            patches["fetch_injury_report"],
            patches["load_prop_lines"],
            patches["openai"],
            patch(
                "court_edge_agent.agents.live_predict._hgb_fallback",
                return_value=LiveProjection(
                    player_name="Jalen Brunson",
                    game_date=date(2025, 4, 1),
                    market="points",
                    projection=25.0,
                    prop_line=26.5,
                    edge=-1.5,
                    lean="under",
                    confidence="medium",
                    explanation=["HGB fallback explanation."],
                    source="hgb_fallback",
                ),
            ),
        ):
            result = await live_predict(
                player_name="Jalen Brunson",
                game_date=date(2025, 4, 1),
                market="points",  # type: ignore[arg-type]
                opponent="PHI",
                home_away="HOME",
                prop_line=26.5,
            )

        assert result.source == "hgb_fallback"

    @pytest.mark.asyncio
    async def test_source_is_hgb_fallback_when_no_api_key(self) -> None:
        mock_fallback = LiveProjection(
            player_name="Jalen Brunson",
            game_date=date(2025, 4, 1),
            market="points",
            projection=25.0,
            prop_line=None,
            edge=None,
            lean=None,
            confidence="medium",
            explanation=["HGB fallback."],
            source="hgb_fallback",
        )

        with (
            patch(
                "court_edge_agent.agents.live_predict.settings",
                openai_api_key="",
                default_season="2024-25",
            ),
            patch(
                "court_edge_agent.agents.live_predict._hgb_fallback",
                return_value=mock_fallback,
            ),
        ):
            result = await live_predict(
                player_name="Jalen Brunson",
                game_date=date(2025, 4, 1),
                market="points",  # type: ignore[arg-type]
                opponent="PHI",
                home_away="HOME",
            )

        assert result.source == "hgb_fallback"


class TestLivePredictInjuryIntegration:
    @pytest.mark.asyncio
    async def test_injury_context_passed_to_prompt(self) -> None:
        """fetch_injury_report is called and its output flows into the prompt."""
        injury_data = {
            "Joel Embiid": {"status": "Out", "reason": "knee", "team": "PHI"},
        }
        captured_prompts: list[str] = []

        def _capture_create(**kwargs):
            captured_prompts.append(kwargs["messages"][1]["content"])
            choice = MagicMock()
            choice.message.content = json.dumps(_LLM_RESPONSE)
            completion = MagicMock()
            completion.choices = [choice]
            return completion

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _capture_create

        patches = _patch_stack(injury_report=injury_data)
        patches["openai"] = patch(
            "court_edge_agent.agents.live_predict.OpenAI",
            return_value=mock_client,
        )

        with (
            patches["settings"],
            patches["search_player_id"],
            patches["fetch_player_context"],
            patches["fetch_opponent_defense"],
            patches["fetch_injury_report"],
            patches["load_prop_lines"],
            patches["openai"],
        ):
            await live_predict(
                player_name="Jalen Brunson",
                game_date=date(2025, 4, 1),
                market="points",  # type: ignore[arg-type]
                opponent="PHI",
                home_away="HOME",
                prop_line=26.5,
            )

        assert len(captured_prompts) == 1
        assert "Joel Embiid" in captured_prompts[0]
        assert "Out" in captured_prompts[0]


class TestLivePredictStoredPropLine:
    @pytest.mark.asyncio
    async def test_stored_prop_line_used_when_no_user_line(self) -> None:
        import pandas as pd

        stored_df = pd.DataFrame([{
            "player_name": "Jalen Brunson",
            "game_date": "2025-04-01",
            "market": "points",
            "line": 25.5,
            "over_odds": -110,
            "under_odds": -110,
            "bookmaker": "draftkings",
            "fetched_at": "2025-04-01T09:00:00+00:00",
        }])

        patches = _patch_stack()
        with (
            patches["settings"],
            patches["search_player_id"],
            patches["fetch_player_context"],
            patches["fetch_opponent_defense"],
            patches["fetch_injury_report"],
            patch(
                "court_edge_agent.agents.live_predict.load_prop_lines",
                return_value=stored_df,
            ),
            patches["openai"],
        ):
            result = await live_predict(
                player_name="Jalen Brunson",
                game_date=date(2025, 4, 1),
                market="points",  # type: ignore[arg-type]
                opponent="PHI",
                home_away="HOME",
                prop_line=None,  # no user-provided line
            )

        # The stored prop line (25.5) should be used
        assert result.prop_line == 25.5

    @pytest.mark.asyncio
    async def test_user_prop_line_takes_precedence_over_stored(self) -> None:
        import pandas as pd

        stored_df = pd.DataFrame([{
            "player_name": "Jalen Brunson",
            "game_date": "2025-04-01",
            "market": "points",
            "line": 25.5,
            "over_odds": -110,
            "under_odds": -110,
            "bookmaker": "draftkings",
            "fetched_at": "2025-04-01T09:00:00+00:00",
        }])

        patches = _patch_stack()
        with (
            patches["settings"],
            patches["search_player_id"],
            patches["fetch_player_context"],
            patches["fetch_opponent_defense"],
            patches["fetch_injury_report"],
            patch(
                "court_edge_agent.agents.live_predict.load_prop_lines",
                return_value=stored_df,
            ),
            patches["openai"],
        ):
            result = await live_predict(
                player_name="Jalen Brunson",
                game_date=date(2025, 4, 1),
                market="points",  # type: ignore[arg-type]
                opponent="PHI",
                home_away="HOME",
                prop_line=26.5,  # user-provided takes precedence
            )

        assert result.prop_line == 26.5
