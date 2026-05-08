"""Batch slate analyzer for ranking top NBA prop edges."""

from __future__ import annotations

import asyncio
from datetime import date

from court_edge_agent.agents.live_predict import live_predict
from court_edge_agent.common.logging import get_logger
from court_edge_agent.data.nba_client import fetch_todays_slate, get_team_roster, search_player_id
from court_edge_agent.data.storage import load_game_logs, load_prop_lines
from court_edge_agent.models.predict import predict
from court_edge_agent.models.train import load_models

logger = get_logger(__name__)

DEFAULT_MARKETS = ["points", "rebounds", "assists", "threes_made"]


async def run_slate_analysis(
    game_date: str | None = None,
    markets: list[str] | None = None,
    min_edge: float = 1.5,
    top_n: int = 10,
) -> dict:
    """Analyze the slate and return top projected edges."""
    target_date = game_date or date.today().isoformat()
    selected_markets = markets or DEFAULT_MARKETS

    slate = fetch_todays_slate(target_date)
    if not slate:
        return {"error": "No games scheduled", "date": target_date}

    candidates: list[dict[str, str]] = []
    seen_players: set[str] = set()
    known_players: set[str] = set()
    missing_players: set[str] = set()

    for game in slate:
        for team_key, opponent_key, home_away in (
            ("home_team", "away_team", "HOME"),
            ("away_team", "home_team", "AWAY"),
        ):
            team_abbr = str(game.get(team_key, "")).upper()
            opponent_abbr = str(game.get(opponent_key, "")).upper()
            if not team_abbr or not opponent_abbr:
                continue

            roster = get_team_roster(team_abbr)
            for player_name in roster:
                if player_name in missing_players:
                    continue
                if player_name not in known_players:
                    if _player_has_logs(player_name):
                        known_players.add(player_name)
                    else:
                        missing_players.add(player_name)
                        continue

                for market in selected_markets:
                    key = f"{player_name}|{market}|{opponent_abbr}|{home_away}"
                    if key in seen_players:
                        continue
                    seen_players.add(key)
                    candidates.append(
                        {
                            "player_name": player_name,
                            "team": team_abbr,
                            "opponent": opponent_abbr,
                            "home_away": home_away,
                            "market": market,
                        }
                    )

    if not candidates:
        return {
            "date": target_date,
            "games_on_slate": len(slate),
            "candidates_evaluated": 0,
            "edges_above_threshold": 0,
            "top_picks": [],
            "note": (
                "No slate players matched local game logs. "
                "Run scripts/ingest_player_logs.py (and feature/model pipeline) first."
            ),
        }

    models = load_models()
    evaluated: list[dict] = []
    lines_found = 0
    parsed_game_date = date.fromisoformat(target_date)

    for candidate in candidates:
        prop_df = load_prop_lines(
            candidate["player_name"],
            target_date,
            candidate["market"],
        )
        if prop_df.empty:
            continue
        lines_found += 1
        prop_line = float(prop_df.iloc[0]["line"])
        try:
            projection = predict(
                player_name=candidate["player_name"],
                game_date=parsed_game_date,
                market=candidate["market"],  # type: ignore[arg-type]
                opponent=candidate["opponent"],
                home_away=candidate["home_away"],
                prop_line=prop_line,
                models=models,
            )
        except Exception as exc:
            logger.warning(
                "Skipping candidate %s %s: %s",
                candidate["player_name"],
                candidate["market"],
                exc,
            )
            continue

        edge = projection.projection - prop_line
        if abs(edge) < min_edge:
            continue

        evaluated.append(
            {
                **candidate,
                "prop_line": prop_line,
                "hgb_projection": projection.projection,
                "edge": round(edge, 2),
                "lean": "over" if edge > 0 else "under",
            }
        )

    evaluated.sort(key=lambda row: abs(float(row["edge"])), reverse=True)
    top_candidates = evaluated[:top_n]

    semaphore = asyncio.Semaphore(3)

    async def enrich(candidate: dict) -> dict:
        async with semaphore:
            result = await live_predict(
                player_name=candidate["player_name"],
                game_date=parsed_game_date,
                market=candidate["market"],  # type: ignore[arg-type]
                opponent=candidate["opponent"],
                home_away=candidate["home_away"],
                prop_line=float(candidate["prop_line"]),
            )
            return {
                **candidate,
                "llm_projection": result.projection,
                "confidence": result.confidence,
                "explanation": result.explanation,
            }

    enriched: list[dict] = []
    if top_candidates:
        enriched = list(await asyncio.gather(*(enrich(candidate) for candidate in top_candidates)))

    top_picks: list[dict] = []
    for idx, pick in enumerate(enriched, start=1):
        top_picks.append(
            {
                "rank": idx,
                "player_name": pick["player_name"],
                "team": pick["team"],
                "opponent": pick["opponent"],
                "home_away": pick["home_away"],
                "market": pick["market"],
                "prop_line": round(float(pick["prop_line"]), 2),
                "hgb_projection": round(float(pick["hgb_projection"]), 2),
                "llm_projection": round(float(pick["llm_projection"]), 2),
                "edge": round(float(pick["edge"]), 2),
                "lean": pick["lean"],
                "confidence": pick["confidence"],
                "explanation": pick["explanation"],
            }
        )

    result: dict[str, object] = {
        "date": target_date,
        "games_on_slate": len(slate),
        "candidates_evaluated": len(candidates),
        "edges_above_threshold": len(evaluated),
        "top_picks": top_picks,
    }
    if lines_found == 0:
        result["note"] = "No stored prop lines found. Run scripts/fetch_odds.py first."
    return result


def _player_has_logs(player_name: str) -> bool:
    """Return true when the player has locally stored game logs."""
    player_id = search_player_id(player_name)
    if player_id is None:
        return False
    return not load_game_logs(player_id=player_id).empty
