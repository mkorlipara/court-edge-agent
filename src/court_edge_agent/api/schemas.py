"""Pydantic request / response schemas for the FastAPI prediction service."""

from datetime import date as dt_date
from typing import Literal

from pydantic import BaseModel, Field


class PredictRequest(BaseModel):
    player_name: str = Field(..., examples=["Stephen Curry"])
    game_date: dt_date = Field(..., examples=["2025-01-15"])
    market: Literal["points", "rebounds", "assists", "threes_made"] = Field(
        ..., examples=["points"]
    )
    prop_line: float | None = Field(default=None, examples=[27.5])
    # Optional context hints; if omitted the API will attempt to infer
    opponent: str | None = Field(default=None, examples=["LAL"])
    home_away: Literal["HOME", "AWAY"] | None = Field(default=None, examples=["HOME"])


class PredictResponse(BaseModel):
    player_name: str
    game_date: dt_date
    market: str
    projection: float
    prop_line: float | None = None
    edge: float | None = None
    lean: Literal["over", "under"] | None = None
    confidence: Literal["high", "medium", "low"]
    explanation: list[str]
    source: Literal["llm", "hgb_fallback"] = "hgb_fallback"


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class SlateRequest(BaseModel):
    game_date: dt_date | None = Field(default=None, examples=["2025-04-10"])
    markets: list[Literal["points", "rebounds", "assists", "threes_made"]] | None = Field(
        default=None,
        examples=[["points", "rebounds"]],
    )
    min_edge: float = Field(default=1.5, ge=0.0, examples=[1.5])
    top_n: int = Field(default=10, ge=1, le=100, examples=[10])


class SlatePick(BaseModel):
    rank: int
    player_name: str
    team: str
    opponent: str
    home_away: Literal["HOME", "AWAY"]
    market: Literal["points", "rebounds", "assists", "threes_made"]
    prop_line: float
    hgb_projection: float
    llm_projection: float
    edge: float
    lean: Literal["over", "under"]
    confidence: Literal["high", "medium", "low"]
    explanation: list[str]


class SlateResponse(BaseModel):
    date: dt_date | None = None
    games_on_slate: int | None = None
    candidates_evaluated: int | None = None
    edges_above_threshold: int | None = None
    top_picks: list[SlatePick] = Field(default_factory=list)
    note: str | None = None
    error: str | None = None


class GameLogEntry(BaseModel):
    game_date: str
    matchup: str
    value: float


class PlayerHistoryResponse(BaseModel):
    player_name: str
    market: str
    games: list[GameLogEntry]


# ---------------------------------------------------------------------------
# Today endpoint
# ---------------------------------------------------------------------------

class TodayGame(BaseModel):
    home_team: str
    away_team: str
    game_time: str | None = None


class TodayLine(BaseModel):
    player_name: str
    team: str | None = None
    opponent: str | None = None
    home_away: Literal["HOME", "AWAY"] | None = None
    market: Literal["points", "rebounds", "assists", "threes_made"]
    line: float
    over_odds: int | None = None
    under_odds: int | None = None
    bookmaker: str
    # Populated when we have local HGB model data for this player
    projection: float | None = None
    edge: float | None = None
    lean: Literal["over", "under"] | None = None


class TodayResponse(BaseModel):
    date: str
    games: list[TodayGame] = Field(default_factory=list)
    top_edges: list[TodayLine] = Field(default_factory=list)
    all_lines: list[TodayLine] = Field(default_factory=list)
    total_lines: int = 0
    scored_lines: int = 0
    fetched_at: str
    odds_api_available: bool = False
    from_cache: bool = False
    note: str | None = None
