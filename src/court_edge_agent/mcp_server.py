"""MCP server exposing court-edge-agent projection tools to Cursor.

Run via:
    python -m court_edge_agent.mcp_server

Transport: stdio (required by Cursor's local MCP integration).
"""

from __future__ import annotations

import asyncio
from datetime import date

import pandas as pd
from mcp.server.fastmcp import FastMCP

from court_edge_agent.agents.live_predict import _extract_player_team, live_predict
from court_edge_agent.agents.slate_agent import run_slate_analysis as run_slate_analysis_agent
from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.data.nba_client import (
    fetch_injury_report,
    fetch_opponent_defense,
    fetch_player_context,
    search_player_id,
)
from court_edge_agent.data.storage import load_features, load_game_logs, load_prop_lines
from court_edge_agent.features.build_features import (
    build_inference_features,
    compute_opponent_stats,
)
from court_edge_agent.models.baseline import _feature_prefix
from court_edge_agent.models.evaluate import full_evaluation_report
from court_edge_agent.models.predict import predict
from court_edge_agent.models.train import date_split, load_models

logger = get_logger(__name__)

mcp = FastMCP("court-edge-agent")


# ---------------------------------------------------------------------------
# Tool 1 — get_player_recent_games
# ---------------------------------------------------------------------------


@mcp.tool()
def get_player_recent_games(player_name: str, n_games: int = 5) -> dict:
    """Returns the last N game log rows for a player from the local database.

    Use this to show recent performance, scoring trends, or minutes trends.
    Returns a list of dicts with keys: game_date, matchup, points, rebounds,
    assists, threes_made, minutes. If the player has no stored data, returns
    an error dict prompting the user to run ingestion first.
    """
    player_id = search_player_id(player_name, settings.default_season)
    if player_id is None:
        return {"error": "Player not found. Run ingestion first."}

    df = load_game_logs(player_id=player_id)
    if df.empty:
        return {"error": "Player not found. Run ingestion first."}

    tail = df.tail(n_games)
    rows = []
    for _, row in tail.iterrows():
        gd = row.get("game_date")
        rows.append(
            {
                "game_date": str(gd) if gd is not None else None,
                "matchup": row.get("matchup"),
                "points": row.get("points"),
                "rebounds": row.get("rebounds"),
                "assists": row.get("assists"),
                "threes_made": row.get("threes_made"),
                "minutes": row.get("minutes"),
            }
        )
    return {"player_name": player_name, "games": rows, "n": len(rows)}


# ---------------------------------------------------------------------------
# Tool 2 — get_player_projection
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_player_projection(
    player_name: str,
    game_date: str,
    market: str,
    opponent: str,
    home_away: str = "HOME",
    prop_line: float | None = None,
) -> dict:
    """Generates a full player prop projection for an upcoming game.

    Returns projection, edge vs. line, lean (over/under), confidence level,
    and a 2-3 sentence explanation. Uses live NBA context + GPT-4o if
    available, falls back to the offline HGB model automatically.

    Args:
        player_name: Full player name, e.g. "Jalen Brunson".
        game_date: ISO date string, e.g. "2025-04-10".
        market: Stat market — "points", "rebounds", "assists", or "threes_made".
        opponent: 3-letter team abbreviation, e.g. "BOS".
        home_away: "HOME" or "AWAY" (default "HOME").
        prop_line: Optional sportsbook line for edge calculation.
    """
    try:
        parsed_date = date.fromisoformat(game_date)
    except ValueError:
        return {"error": f"Invalid game_date format '{game_date}'. Use ISO format: YYYY-MM-DD."}

    valid_markets = {"points", "rebounds", "assists", "threes_made"}
    if market not in valid_markets:
        return {"error": f"Invalid market '{market}'. Must be one of: {sorted(valid_markets)}."}

    try:
        result = await live_predict(
            player_name=player_name,
            game_date=parsed_date,
            market=market,  # type: ignore[arg-type]
            opponent=opponent,
            home_away=home_away.upper(),
            prop_line=prop_line,
        )
        return {
            "player_name": result.player_name,
            "game_date": str(result.game_date),
            "market": result.market,
            "projection": result.projection,
            "prop_line": result.prop_line,
            "edge": result.edge,
            "lean": result.lean,
            "confidence": result.confidence,
            "explanation": result.explanation,
            "source": result.source,
        }
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.warning("get_player_projection failed: %s", exc)
        return {"error": f"Projection failed: {exc}"}


# ---------------------------------------------------------------------------
# Tool 3 — get_prop_edges
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_prop_edges(
    player_market_pairs: list[dict],
    game_date: str,
    opponent_map: dict[str, str],
) -> list[dict]:
    """Takes a list of player/market pairs and returns them ranked by edge.

    Compares each player's HGB model projection against the stored prop line
    in the database. Only includes players where a stored prop line exists.
    Uses the offline HGB model (not GPT-4o) to avoid burning API credits
    across a large slate.

    Args:
        player_market_pairs: List of dicts with keys "player" and "market",
            e.g. [{"player": "Jalen Brunson", "market": "points"}, ...].
        game_date: ISO date string for the game slate, e.g. "2025-04-10".
        opponent_map: Dict mapping player name to 3-letter opponent abbreviation,
            e.g. {"Jalen Brunson": "BOS", "Jayson Tatum": "NYK"}.
    """
    try:
        parsed_date = date.fromisoformat(game_date)
    except ValueError:
        return []

    models = load_models()
    results: list[dict] = []

    for pair in player_market_pairs:
        player = pair.get("player", "")
        market = pair.get("market", "")
        if not player or not market:
            continue

        prop_df = load_prop_lines(player, game_date, market)
        if prop_df.empty:
            continue

        stored_line = float(prop_df.iloc[0]["line"])
        opponent = opponent_map.get(player, "UNK")

        try:
            proj = predict(
                player_name=player,
                game_date=parsed_date,
                market=market,  # type: ignore[arg-type]
                opponent=opponent,
                home_away="HOME",
                prop_line=stored_line,
                models=models,
            )
            results.append(
                {
                    "player": player,
                    "market": market,
                    "projection": proj.projection,
                    "line": stored_line,
                    "edge": proj.edge,
                    "lean": proj.lean,
                    "confidence": proj.confidence,
                }
            )
        except Exception as exc:
            logger.warning("get_prop_edges: skipping %s %s — %s", player, market, exc)
            continue

    results.sort(key=lambda r: abs(r.get("edge") or 0.0), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Tool 4 — run_backtest
# ---------------------------------------------------------------------------


@mcp.tool()
def run_backtest(
    season: str = "2024-25",
    cutoff_date: str | None = None,
) -> dict:
    """Runs the backtesting evaluation pipeline and returns MAE/RMSE per market.

    Evaluates Ridge, HGB, and rolling-average baselines on held-out test data.
    Use this to understand current model performance before trusting projections.

    Args:
        season: NBA season string, e.g. "2024-25" (default).
        cutoff_date: ISO date string for the train/test split. Defaults to the
            value in settings (train_cutoff_date).
    """
    features_df = load_features(season=season)
    if features_df.empty:
        return {"error": "No features found. Run build_features.py first."}

    _, test_df = date_split(features_df, cutoff_date)
    if test_df.empty:
        return {"error": "No test data after cutoff. Try an earlier cutoff_date."}

    models = load_models()
    report_df = full_evaluation_report(models, test_df)

    effective_cutoff = cutoff_date or settings.train_cutoff_date
    return {
        "season": season,
        "cutoff": effective_cutoff,
        "test_rows": len(test_df),
        "results": report_df.to_dict(orient="records"),
    }


# ---------------------------------------------------------------------------
# Tool 5 — explain_projection
# ---------------------------------------------------------------------------


@mcp.tool()
async def explain_projection(
    player_name: str,
    game_date: str,
    market: str,
    opponent: str,
    home_away: str = "HOME",
    prop_line: float | None = None,
) -> dict:
    """Returns a verbose breakdown of a projection with factor-level attribution.

    More detailed than get_player_projection. Breaks the projection down into:
    the HGB model anchor, rolling vs season trend delta, opponent defensive
    context (DRTG rank and points allowed), injury flags, and a list of named
    factors with direction (up/down), magnitude, and explanatory notes.

    Args:
        player_name: Full player name, e.g. "Jalen Brunson".
        game_date: ISO date string, e.g. "2025-04-10".
        market: Stat market — "points", "rebounds", "assists", or "threes_made".
        opponent: 3-letter team abbreviation, e.g. "BOS".
        home_away: "HOME" or "AWAY" (default "HOME").
        prop_line: Optional sportsbook line for edge context.
    """
    try:
        parsed_date = date.fromisoformat(game_date)
    except ValueError:
        return {"error": f"Invalid game_date format '{game_date}'. Use ISO format: YYYY-MM-DD."}

    valid_markets = {"points", "rebounds", "assists", "threes_made"}
    if market not in valid_markets:
        return {"error": f"Invalid market '{market}'. Must be one of: {sorted(valid_markets)}."}

    # ------------------------------------------------------------------
    # 1. Resolve player and build HGB model anchor
    # ------------------------------------------------------------------
    player_id = search_player_id(player_name, settings.default_season)
    if player_id is None:
        return {"error": f"Player not found: '{player_name}'. Run ingestion first."}

    game_logs = load_game_logs(player_id=player_id)
    if game_logs.empty:
        return {"error": f"No game logs for '{player_name}'. Run ingestion first."}

    models = load_models()
    try:
        proj = predict(
            player_name=player_name,
            game_date=parsed_date,
            market=market,  # type: ignore[arg-type]
            opponent=opponent,
            home_away=home_away.upper(),
            prop_line=prop_line,
            models=models,
        )
        model_anchor = proj.projection
    except Exception as exc:
        return {"error": f"Could not compute model projection: {exc}"}

    # ------------------------------------------------------------------
    # 2. Extract rolling vs. season stats from the feature row
    # ------------------------------------------------------------------
    opp_stats = None
    if opponent and opponent != "UNK":
        all_logs = load_game_logs()
        opp_stats = compute_opponent_stats(all_logs, opponent, parsed_date)

    feature_row = build_inference_features(
        game_logs, parsed_date, opponent, home_away.upper(), opp_stats
    )

    prefix = _feature_prefix(market)
    rolling_5: float | None = None
    season_avg: float | None = None
    back_to_back = False

    if feature_row is not None:
        _r5 = feature_row.get(f"rolling_5_{prefix}")
        _sa = feature_row.get(f"season_avg_{prefix}_to_date")
        _b2b = feature_row.get("back_to_back_flag")
        if _r5 is not None:
            try:
                v = float(_r5)
                rolling_5 = None if pd.isna(v) else v
            except (TypeError, ValueError):
                pass
        if _sa is not None:
            try:
                v = float(_sa)
                season_avg = None if pd.isna(v) else v
            except (TypeError, ValueError):
                pass
        if _b2b is not None:
            back_to_back = bool(_b2b == 1)

    trend_delta: float | None = (
        round(rolling_5 - season_avg, 2)
        if rolling_5 is not None and season_avg is not None
        else None
    )

    # ------------------------------------------------------------------
    # 3. Fetch opponent defense + injury flags (best-effort)
    # ------------------------------------------------------------------
    opp_defense: dict = {}
    injury_flags: list[str] = []

    try:
        opp_defense = await asyncio.to_thread(
            fetch_opponent_defense, opponent, settings.default_season
        )
    except Exception as exc:
        logger.warning("explain_projection: opp defense fetch failed: %s", exc)

    try:
        player_ctx = await asyncio.to_thread(
            fetch_player_context, player_id, player_name, settings.default_season, opponent
        )
        player_team = _extract_player_team(player_ctx) if isinstance(player_ctx, dict) else None
        team_abbrs = [t for t in [player_team, opponent] if t]
        injury_report = await asyncio.to_thread(fetch_injury_report, team_abbrs)
        for name, info in injury_report.items():
            status = info.get("status", "Unknown")
            injury_flags.append(f"{name}: {status}")
    except Exception as exc:
        logger.warning("explain_projection: injury/context fetch failed: %s", exc)

    # ------------------------------------------------------------------
    # 4. Build factor list
    # ------------------------------------------------------------------
    factors: list[dict] = []

    if trend_delta is not None and rolling_5 is not None and season_avg is not None:
        direction = "up" if trend_delta > 0 else "down"
        factors.append(
            {
                "name": "recent_form",
                "direction": direction,
                "magnitude": abs(trend_delta),
                "note": (
                    f"Last 5 avg {rolling_5:.1f} — "
                    f"{'above' if trend_delta > 0 else 'below'} "
                    f"season avg of {season_avg:.1f} by {abs(trend_delta):.1f}"
                ),
            }
        )

    opp_drtg_rank: int | None = opp_defense.get("drtg_rank")
    opp_pts_allowed: float | None = opp_defense.get("pts_allowed")
    if opp_drtg_rank is not None:
        # Higher rank (closer to 30) = worse defense = easier matchup
        n_teams = opp_defense.get("n_teams", 30)
        midpoint = n_teams / 2
        direction = "up" if opp_drtg_rank > midpoint else "down"
        magnitude = abs(opp_drtg_rank - midpoint) * 0.1
        factors.append(
            {
                "name": "opponent_defense",
                "direction": direction,
                "magnitude": round(magnitude, 2),
                "note": (
                    f"{opponent} ranks #{opp_drtg_rank} in defensive rating "
                    f"({'soft' if direction == 'up' else 'tough'} matchup)"
                ),
            }
        )

    if back_to_back:
        factors.append(
            {
                "name": "back_to_back",
                "direction": "down",
                "magnitude": 0.8,
                "note": "Second game of a back-to-back — fatigue factor applied",
            }
        )

    # Compute final projection as anchor + signed factor adjustments
    total_adjustment = sum(
        f["magnitude"] if f["direction"] == "up" else -f["magnitude"]
        for f in factors
    )
    final_projection = round(model_anchor + total_adjustment, 2)

    return {
        "player_name": player_name,
        "market": market,
        "model_anchor": model_anchor,
        "season_average": season_avg,
        "rolling_5_average": rolling_5,
        "trend_delta": trend_delta,
        "opponent_rank": opp_drtg_rank,
        "opp_pts_allowed": opp_pts_allowed,
        "injury_flags": injury_flags,
        "factors": factors,
        "final_projection": final_projection,
        "prop_line": prop_line,
        "edge": round(final_projection - prop_line, 2) if prop_line is not None else None,
    }


@mcp.tool()
async def run_slate_analysis(
    game_date: str | None = None,
    markets: list[str] | None = None,
    min_edge: float = 1.5,
    top_n: int = 10,
) -> dict:
    """
    Analyzes today's full NBA slate and returns the top projected edges
    vs. stored prop lines. Evaluates all players on all scheduled games,
    filters to edges above min_edge, and enriches the top picks with
    live GPT-4o projections and explanations. Use this to find the best
    prop bets on today's slate.
    """
    return await run_slate_analysis_agent(
        game_date=game_date,
        markets=markets,
        min_edge=min_edge,
        top_n=top_n,
    )


if __name__ == "__main__":
    mcp.run()
