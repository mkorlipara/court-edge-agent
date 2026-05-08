"""Prediction function: given a player + game context, return a projection."""

import contextlib
from dataclasses import dataclass
from datetime import date

import pandas as pd

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.data.nba_client import search_player_id
from court_edge_agent.data.storage import load_game_logs
from court_edge_agent.features.build_features import (
    build_inference_features,
    compute_opponent_stats,
)
from court_edge_agent.models.baseline import (
    RollingAverageBaseline,
    StatMarket,
    _feature_prefix,
)
from court_edge_agent.models.train import AnyModel, load_models

logger = get_logger(__name__)

# Approximate league-average stat rates for the top-50 player pool.
# Used to contextualise opponent defensive strength in the narrative.
_LEAGUE_AVG_OPP: dict[str, float] = {
    "points": 24.0,
    "rebounds": 6.5,
    "assists": 5.0,
    "threes_made": 2.0,
}

# Maps market name → opponent-allowed column name in the feature row
_OPP_STAT_COL: dict[str, str] = {
    "points": "opp_pts_allowed",
    "rebounds": "opp_reb_allowed",
    "assists": "opp_ast_allowed",
    "threes_made": "opp_3pm_allowed",
}


@dataclass
class Projection:
    player_name: str
    game_date: date
    market: str
    projection: float
    prop_line: float | None
    edge: float | None
    lean: str | None       # "over" | "under" | None
    confidence: str            # "high" | "medium" | "low"
    explanation: list[str]


def _confidence_from_edge(edge: float) -> str:
    abs_edge = abs(edge)
    if abs_edge >= settings.confidence_high_threshold:
        return "high"
    if abs_edge >= settings.confidence_medium_threshold:
        return "medium"
    return "low"


def _confidence_from_model_error(mae: float, projection: float) -> str:
    """When no prop line is given, use relative model error as a proxy."""
    if projection == 0:
        return "low"
    rel_error = mae / projection
    if rel_error < 0.1:
        return "high"
    if rel_error < 0.2:
        return "medium"
    return "low"


def _build_explanation(
    feature_row: pd.Series,
    market: str,
    projection: float,
    prop_line: float | None,
) -> list[str]:
    """Generate a 2–3 sentence narrative explanation from the feature row.

    Factors are ranked by absolute magnitude; only the top signals are mentioned.
    Back-to-back context is included only when it meaningfully suppresses the
    projection below the player's season average.
    """
    prefix = _feature_prefix(market)

    roll5 = feature_row.get(f"rolling_5_{prefix}")
    season_avg = feature_row.get(f"season_avg_{prefix}_to_date")
    days_rest = feature_row.get("days_rest")
    b2b = feature_row.get("back_to_back_flag")
    opponent = feature_row.get("opponent", "the opponent")

    opp_col = _OPP_STAT_COL.get(market)
    opp_allowed_raw = feature_row.get(opp_col) if opp_col else None
    opp_allowed: float | None = None
    if opp_allowed_raw is not None:
        try:
            v = float(opp_allowed_raw)
            opp_allowed = None if pd.isna(v) else v
        except (TypeError, ValueError):
            opp_allowed = None

    league_avg = _LEAGUE_AVG_OPP.get(market, projection)

    # --- Compute factor deltas ---
    trend_delta: float | None = None
    roll5_f: float | None = None
    season_avg_f: float | None = None
    if roll5 is not None and season_avg is not None:
        try:
            roll5_f = float(roll5)
            season_avg_f = float(season_avg)
            if not pd.isna(roll5_f) and not pd.isna(season_avg_f):
                trend_delta = roll5_f - season_avg_f
        except (TypeError, ValueError):
            pass

    opp_delta: float | None = None
    if opp_allowed is not None:
        opp_delta = opp_allowed - league_avg

    b2b_active = bool(b2b == 1)
    days_rest_int: int | None = None
    if days_rest is not None:
        with contextlib.suppress(TypeError, ValueError):
            days_rest_int = int(days_rest)

    # --- Rank factors by magnitude to pick top signals ---
    factor_magnitudes: list[tuple[str, float]] = []
    if trend_delta is not None:
        factor_magnitudes.append(("trend", abs(trend_delta)))
    if opp_delta is not None:
        factor_magnitudes.append(("opp", abs(opp_delta)))
    factor_magnitudes.sort(key=lambda x: x[1], reverse=True)
    top_factors = [f[0] for f in factor_magnitudes]

    market_label = market.replace("_", " ")
    sentences: list[str] = []

    # Sentence 1 — projection with primary factor
    if "trend" in top_factors[:1] and trend_delta is not None and roll5_f is not None and season_avg_f is not None:
        form_phrase = "in strong form" if trend_delta > 0 else "below their usual pace"
        direction_word = "above" if trend_delta > 0 else "below"
        sentences.append(
            f"Projecting {projection:.1f} {market_label} — "
            f"{feature_row.get('player_name', 'this player')} is {form_phrase}, "
            f"averaging {roll5_f:.1f} over the last 5 games ({abs(trend_delta):.1f} "
            f"{direction_word} their season average of {season_avg_f:.1f})."
        )
    elif roll5_f is not None and not pd.isna(roll5_f):
        sentences.append(
            f"Projecting {projection:.1f} {market_label} based on a recent "
            f"5-game average of {roll5_f:.1f}."
        )
    else:
        sentences.append(
            f"Projecting {projection:.1f} {market_label} based on available season data."
        )

    # Sentence 2 — opponent defensive context (only when delta is meaningful)
    if opp_delta is not None and abs(opp_delta) >= 0.5:
        if opp_delta > 0:
            sentences.append(
                f"{opponent} has been a soft matchup, allowing {opp_allowed:.1f} "
                f"{market_label} per game ({opp_delta:.1f} above league average), "
                f"supporting the over."
            )
        else:
            sentences.append(
                f"{opponent} plays stout {market_label} defense, allowing just "
                f"{opp_allowed:.1f} per game ({abs(opp_delta):.1f} below league average), "
                f"suppressing the projection."
            )

    # Sentence 3 — rest / back-to-back (only when meaningful)
    if b2b_active and season_avg_f is not None and projection < season_avg_f * 0.95:
        sentences.append(
            "This is a back-to-back game, which factors into the lower-than-average projection."
        )
    elif not b2b_active and days_rest_int is not None and days_rest_int >= 3:
        sentences.append(
            f"With {days_rest_int} days of rest, the player enters this game well-rested."
        )

    # Prop line comparison (appended when an edge exists)
    if prop_line is not None:
        edge = projection - prop_line
        if abs(edge) >= 1.0:
            direction = "above" if edge > 0 else "below"
            lean = "over" if edge > 0 else "under"
            sentences.append(
                f"The projection sits {abs(edge):.1f} {direction} the line of "
                f"{prop_line:.1f}, suggesting a lean {lean}."
            )

    return sentences if sentences else [f"Projection based on recent game history: {projection:.1f}"]


def predict(
    player_name: str,
    game_date: date,
    market: StatMarket,
    opponent: str,
    home_away: str,
    prop_line: float | None = None,
    models: dict[str, AnyModel] | None = None,
    season: str | None = None,
) -> Projection:
    """Core prediction function.

    Args:
        player_name: Full player name (e.g. "Stephen Curry").
        game_date: Date of the upcoming game.
        market: Stat to project ("points", "rebounds", "assists", "threes_made").
        opponent: 3-letter opponent abbreviation (e.g. "LAL").
        home_away: "HOME" or "AWAY".
        prop_line: Optional sportsbook line for comparison.
        models: Pre-loaded model dict; loaded from disk if not provided.
        season: NBA season string (defaults to settings.default_season).

    Returns:
        Projection dataclass with all prediction metadata.
    """
    season = season or settings.default_season

    # Load game logs for this player
    player_id = search_player_id(player_name, season)
    if player_id is None:
        raise ValueError(f"Player not found: '{player_name}'")

    game_logs = load_game_logs(player_id=player_id, season=season)
    if game_logs.empty:
        raise ValueError(
            f"No game logs found for player_id={player_id}. "
            "Run ingestion first: python scripts/ingest_player_logs.py"
        )

    # Compute opponent defensive stats from all available game logs (date-safe)
    opp_stats: dict[str, float] | None = None
    if opponent and opponent != "UNK":
        all_logs = load_game_logs()
        opp_stats = compute_opponent_stats(all_logs, opponent, game_date)

    feature_row = build_inference_features(
        game_logs, game_date, opponent, home_away, opp_stats
    )
    if feature_row is None:
        raise ValueError(
            f"Could not build inference features for {player_name} on {game_date}"
        )

    # Load models if not provided
    if models is None:
        models = load_models()

    # Prefer loaded model (HGB by default); fall back to rolling average baseline
    if market in models:
        model = models[market]
        projection = model.predict_single(feature_row)
    else:
        logger.warning("No model found for '%s'; using rolling-5 baseline", market)
        baseline = RollingAverageBaseline(window=5)
        proj_val = baseline.predict_single(feature_row, market)  # type: ignore[arg-type]
        if proj_val is None:
            raise ValueError(f"Cannot produce projection for market='{market}'")
        projection = proj_val

    # Edge / confidence
    edge: float | None = None
    lean: str | None = None
    if prop_line is not None:
        edge = round(projection - prop_line, 2)
        lean = "over" if edge > 0 else "under"
        confidence = _confidence_from_edge(edge)
    else:
        confidence = "medium"

    explanation = _build_explanation(feature_row, market, projection, prop_line)

    return Projection(
        player_name=player_name,
        game_date=game_date,
        market=market,
        projection=round(projection, 2),
        prop_line=prop_line,
        edge=edge,
        lean=lean,
        confidence=confidence,
        explanation=explanation,
    )
