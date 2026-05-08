"""Pydantic schemas for raw and processed data records."""

from datetime import date

from pydantic import BaseModel


class PlayerGameLog(BaseModel):
    """One row of a player's game log as returned by nba_api."""

    player_id: int
    player_name: str
    season: str
    game_id: str
    game_date: date
    matchup: str  # e.g. "GSW vs. LAL" or "GSW @ LAL"
    wl: str  # "W" or "L"
    minutes: float
    points: float
    rebounds: float
    assists: float
    threes_made: float
    threes_attempted: float
    fg_made: float
    fg_attempted: float
    ft_made: float
    ft_attempted: float
    plus_minus: float

    class Config:
        from_attributes = True


class FeatureRow(BaseModel):
    """Feature vector for one player-game observation.

    All rolling features are computed over games *strictly before* game_date
    to prevent data leakage.
    """

    player_id: int
    player_name: str
    game_date: date
    season: str
    opponent: str
    home_away: str  # "HOME" or "AWAY"
    days_rest: int
    back_to_back_flag: int  # 0 or 1

    # Rolling averages — points
    rolling_3_points: float | None = None
    rolling_5_points: float | None = None
    rolling_10_points: float | None = None

    # Rolling averages — rebounds
    rolling_3_rebounds: float | None = None
    rolling_5_rebounds: float | None = None
    rolling_10_rebounds: float | None = None

    # Rolling averages — assists
    rolling_3_assists: float | None = None
    rolling_5_assists: float | None = None
    rolling_10_assists: float | None = None

    # Rolling averages — threes made
    rolling_3_threes: float | None = None
    rolling_5_threes: float | None = None
    rolling_10_threes: float | None = None

    # Rolling averages — minutes
    rolling_3_minutes: float | None = None
    rolling_5_minutes: float | None = None
    rolling_10_minutes: float | None = None

    # Season-to-date averages (expanding window, no leakage)
    season_avg_points_to_date: float | None = None
    season_avg_rebounds_to_date: float | None = None
    season_avg_assists_to_date: float | None = None
    season_avg_threes_to_date: float | None = None
    season_avg_minutes_to_date: float | None = None

    # Targets (None when building inference features for future games)
    points: float | None = None
    rebounds: float | None = None
    assists: float | None = None
    threes_made: float | None = None

    class Config:
        from_attributes = True


# Supported stat markets
STAT_MARKETS = ("points", "rebounds", "assists", "threes_made")
