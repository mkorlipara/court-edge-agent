"""Feature engineering from raw player game logs.

Key invariant: for any game on date D, only games *strictly before* D
are used to compute features. This prevents any form of data leakage.
"""

from datetime import date

import numpy as np
import pandas as pd

from court_edge_agent.common.logging import get_logger

logger = get_logger(__name__)

# Rolling window sizes
WINDOWS = (3, 5, 10)

# Maps game-log column name → feature prefix used in output column names.
# e.g. "threes_made" → prefix "threes" → column "rolling_5_threes"
# Keep this in sync with FEATURE_COLUMNS, the DB schema, and REGRESSION_FEATURE_COLS.
ROLLING_STATS: dict[str, str] = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes_made": "threes",   # short prefix avoids "rolling_5_threes_made"
    "minutes": "minutes",
}

# Canonical output columns — must match the player_features table schema exactly
FEATURE_COLUMNS = [
    "player_id", "player_name", "game_date", "season",
    "opponent", "home_away", "days_rest", "back_to_back_flag",
    "rolling_3_points", "rolling_5_points", "rolling_10_points",
    "rolling_3_rebounds", "rolling_5_rebounds", "rolling_10_rebounds",
    "rolling_3_assists", "rolling_5_assists", "rolling_10_assists",
    "rolling_3_threes", "rolling_5_threes", "rolling_10_threes",
    "rolling_3_minutes", "rolling_5_minutes", "rolling_10_minutes",
    "season_avg_points_to_date", "season_avg_rebounds_to_date",
    "season_avg_assists_to_date", "season_avg_threes_to_date",
    "season_avg_minutes_to_date",
    # Opponent defensive features (dataset-level, date-safe)
    "opp_pts_allowed", "opp_reb_allowed", "opp_ast_allowed", "opp_3pm_allowed",
    # Targets
    "points", "rebounds", "assists", "threes_made",
]


def _parse_matchup(matchup: str) -> tuple[str, str]:
    """Extract opponent abbreviation and home/away from matchup string.

    nba_api matchup format: "GSW vs. LAL"  (home) or "GSW @ LAL" (away).
    Returns (opponent_abbr, "HOME"/"AWAY").
    """
    if " vs. " in matchup:
        opponent = matchup.split(" vs. ")[1].strip()
        home_away = "HOME"
    elif " @ " in matchup:
        opponent = matchup.split(" @ ")[1].strip()
        home_away = "AWAY"
    else:
        parts = matchup.split()
        opponent = parts[-1] if parts else "UNK"
        home_away = "UNK"
    return opponent, home_away


def _rolling_mean(series: pd.Series, window: int) -> pd.Series:
    """Shift-then-roll so game i only sees games 0..i-1."""
    return series.shift(1).rolling(window=window, min_periods=1).mean()


def _expanding_mean(series: pd.Series) -> pd.Series:
    """Season-to-date average: shift so game i sees games 0..i-1."""
    return series.shift(1).expanding(min_periods=1).mean()


def _days_rest(dates: pd.Series) -> pd.Series:
    """Days between consecutive games. First game of season gets 3 (neutral default)."""
    shifted = dates.shift(1)
    delta = (dates - shifted).dt.days
    return delta.fillna(3).astype(int)


def build_features_for_player(game_logs: pd.DataFrame) -> pd.DataFrame:
    """Build the full feature matrix for a single player.

    Args:
        game_logs: DataFrame with columns matching ``PlayerGameLog`` schema,
                   sorted ascending by game_date.

    Returns:
        DataFrame with one feature row per game, including target columns.
    """
    if game_logs.empty:
        logger.warning("No game logs provided — returning empty DataFrame")
        return pd.DataFrame()

    df = game_logs.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values("game_date").reset_index(drop=True)

    # --- Context features ------------------------------------------------
    matchup_parsed = df["matchup"].apply(_parse_matchup)
    df["opponent"] = [m[0] for m in matchup_parsed]
    df["home_away"] = [m[1] for m in matchup_parsed]
    df["days_rest"] = _days_rest(df["game_date"])
    df["back_to_back_flag"] = (df["days_rest"] == 1).astype(int)

    # --- Rolling window features -----------------------------------------
    for log_col, prefix in ROLLING_STATS.items():
        if log_col not in df.columns:
            logger.warning("Column '%s' not found; skipping rolling features", log_col)
            continue
        for window in WINDOWS:
            df[f"rolling_{window}_{prefix}"] = _rolling_mean(df[log_col], window)

    # --- Season-to-date averages (expanding, no leakage) -----------------
    season_avg_map = {
        "points": "points",
        "rebounds": "rebounds",
        "assists": "assists",
        "threes_made": "threes",
        "minutes": "minutes",
    }
    for log_col, prefix in season_avg_map.items():
        if log_col in df.columns:
            df[f"season_avg_{prefix}_to_date"] = _expanding_mean(df[log_col])

    # Normalize game_date back to date objects for schema compatibility
    df["game_date"] = df["game_date"].dt.date

    # Return only the canonical schema columns; drop raw log columns (game_id, wl, etc.)
    output_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    return df[output_cols]


def build_opponent_features(game_logs_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-opponent defensive averages, respecting the date-leakage rule.

    For each (game_date, opponent) pair present in the dataset, computes the
    mean points/rebounds/assists/threes_made scored against that opponent across
    ALL games in the dataset that occurred *strictly before* that date.

    Args:
        game_logs_df: Combined game logs for all players (all seasons).

    Returns:
        DataFrame with columns: game_date, opponent, opp_pts_allowed,
        opp_reb_allowed, opp_ast_allowed, opp_3pm_allowed.
    """
    _empty = pd.DataFrame(
        columns=["game_date", "opponent",
                 "opp_pts_allowed", "opp_reb_allowed",
                 "opp_ast_allowed", "opp_3pm_allowed"]
    )
    if game_logs_df.empty:
        return _empty

    df = game_logs_df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    matchup_parsed = df["matchup"].apply(_parse_matchup)
    df["_opp"] = [m[0] for m in matchup_parsed]
    df = df.sort_values("game_date").reset_index(drop=True)

    ref = df[["game_date", "_opp", "points", "rebounds", "assists", "threes_made"]].copy()

    records = []
    for (game_date, opp), _ in df.groupby(["game_date", "_opp"], sort=True):
        prior = ref[(ref["_opp"] == opp) & (ref["game_date"] < game_date)]
        if prior.empty:
            records.append({
                "game_date": game_date,
                "opponent": opp,
                "opp_pts_allowed": np.nan,
                "opp_reb_allowed": np.nan,
                "opp_ast_allowed": np.nan,
                "opp_3pm_allowed": np.nan,
            })
        else:
            records.append({
                "game_date": game_date,
                "opponent": opp,
                "opp_pts_allowed": float(prior["points"].mean()),
                "opp_reb_allowed": float(prior["rebounds"].mean()),
                "opp_ast_allowed": float(prior["assists"].mean()),
                "opp_3pm_allowed": float(prior["threes_made"].mean()),
            })

    result = pd.DataFrame(records)
    result["game_date"] = result["game_date"].dt.date
    return result


def compute_opponent_stats(
    game_logs_df: pd.DataFrame,
    opponent: str,
    before_date: date,
) -> dict[str, float] | None:
    """Compute defensive averages for a single opponent using games before a date.

    Used at inference time to populate opp_* feature values for an upcoming game.

    Args:
        game_logs_df: Combined game logs for all available players.
        opponent: Three-letter team abbreviation (e.g. "LAL").
        before_date: Only include games strictly before this date.

    Returns:
        Dict with keys opp_pts_allowed / opp_reb_allowed / opp_ast_allowed /
        opp_3pm_allowed, or None if no prior games are found.
    """
    if game_logs_df.empty:
        return None

    df = game_logs_df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    matchup_parsed = df["matchup"].apply(_parse_matchup)
    df["_opp"] = [m[0] for m in matchup_parsed]

    target_dt = pd.Timestamp(before_date)
    opp_games = df[(df["_opp"] == opponent) & (df["game_date"] < target_dt)]

    if opp_games.empty:
        return None

    return {
        "opp_pts_allowed": float(opp_games["points"].mean()),
        "opp_reb_allowed": float(opp_games["rebounds"].mean()),
        "opp_ast_allowed": float(opp_games["assists"].mean()),
        "opp_3pm_allowed": float(opp_games["threes_made"].mean()),
    }


def build_features_for_dataset(
    game_logs: pd.DataFrame,
    min_games: int = 3,
) -> pd.DataFrame:
    """Build features for all players in the dataset.

    Args:
        game_logs: Combined game logs for multiple players.
        min_games: Minimum games a player must have to be included.

    Returns:
        Concatenated feature DataFrame for all qualifying players,
        with opponent defensive features joined in.
    """
    if game_logs.empty:
        return pd.DataFrame()

    # Opponent defensive features — computed once from the full dataset
    opp_features = build_opponent_features(game_logs)

    results = []
    for player_id, player_df in game_logs.groupby("player_id"):
        if len(player_df) < min_games:
            logger.debug(
                "Skipping player_id=%s — only %d games (min=%d)",
                player_id, len(player_df), min_games,
            )
            continue
        features = build_features_for_player(player_df)
        results.append(features)

    if not results:
        logger.warning("No players had enough games to build features")
        return pd.DataFrame()

    combined = pd.concat(results, ignore_index=True)

    # Join opponent defensive features on (game_date, opponent)
    if not opp_features.empty:
        combined["game_date"] = pd.to_datetime(combined["game_date"])
        opp_features["game_date"] = pd.to_datetime(opp_features["game_date"])
        combined = combined.merge(opp_features, on=["game_date", "opponent"], how="left")
        combined["game_date"] = combined["game_date"].dt.date

    logger.info(
        "Built features: %d rows across %d players",
        len(combined),
        combined["player_id"].nunique(),
    )

    output_cols = [c for c in FEATURE_COLUMNS if c in combined.columns]
    return combined[output_cols]


def build_inference_features(
    game_logs: pd.DataFrame,
    game_date: date,
    opponent: str,
    home_away: str,
    opp_stats: dict[str, float] | None = None,
) -> pd.Series | None:
    """Build a single inference feature row for a future game.

    Uses all available game_logs (which must all be before game_date) to
    compute rolling stats and season averages.  Pass ``opp_stats`` (from
    :func:`compute_opponent_stats`) to populate the four opponent defensive
    columns; otherwise they are set to NaN.

    Returns a pd.Series with the feature values, or None if insufficient data.
    """
    if game_logs.empty:
        logger.error("Cannot build inference features: no game logs provided")
        return None

    df = game_logs.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values("game_date").reset_index(drop=True)

    # Validate: all logs must precede the target game_date
    target_dt = pd.Timestamp(game_date)
    future_rows = df[df["game_date"] >= target_dt]
    if not future_rows.empty:
        logger.warning(
            "Dropping %d game log rows that are >= game_date=%s to prevent leakage",
            len(future_rows), game_date,
        )
        df = df[df["game_date"] < target_dt].reset_index(drop=True)

    if df.empty:
        logger.error("No game logs before %s", game_date)
        return None

    last_game_date = df["game_date"].max()
    days_rest = (target_dt - last_game_date).days
    back_to_back = int(days_rest == 1)

    row: dict = {
        "player_id": int(df["player_id"].iloc[0]),
        "player_name": df["player_name"].iloc[0],
        "game_date": game_date,
        "season": df["season"].iloc[0],
        "opponent": opponent,
        "home_away": home_away,
        "days_rest": days_rest,
        "back_to_back_flag": back_to_back,
    }

    for log_col, prefix in ROLLING_STATS.items():
        if log_col not in df.columns:
            for w in WINDOWS:
                row[f"rolling_{w}_{prefix}"] = np.nan
            continue
        series = df[log_col]
        for w in WINDOWS:
            available = series.tail(w)
            row[f"rolling_{w}_{prefix}"] = float(available.mean()) if len(available) >= 1 else np.nan

    season_avg_map = {
        "points": "points",
        "rebounds": "rebounds",
        "assists": "assists",
        "threes_made": "threes",
        "minutes": "minutes",
    }
    for log_col, prefix in season_avg_map.items():
        if log_col in df.columns:
            row[f"season_avg_{prefix}_to_date"] = float(df[log_col].mean())
        else:
            row[f"season_avg_{prefix}_to_date"] = np.nan

    # Opponent defensive features
    if opp_stats is not None:
        row.update(opp_stats)
    else:
        row["opp_pts_allowed"] = np.nan
        row["opp_reb_allowed"] = np.nan
        row["opp_ast_allowed"] = np.nan
        row["opp_3pm_allowed"] = np.nan

    return pd.Series(row)
