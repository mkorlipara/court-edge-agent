"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from court_edge_agent.api.schemas import (
    GameLogEntry,
    HealthResponse,
    PlayerHistoryResponse,
    PredictRequest,
    PredictResponse,
    SlateRequest,
    SlateResponse,
)
from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.models.train import AnyModel, load_models

logger = get_logger(__name__)

# HGB model cache — loaded once on startup, used as fallback when LLM is unavailable
_models: dict[str, AnyModel] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load HGB fallback models at startup; clean up on shutdown."""
    global _models
    settings.ensure_dirs()
    try:
        _models = load_models()
        logger.info("Loaded %d HGB fallback model(s) from disk", len(_models))
    except Exception as exc:
        logger.warning("Could not load fallback models at startup: %s", exc)
    if settings.openai_api_key:
        logger.info("OpenAI live agent enabled (model=%s)", settings.openai_model)
    else:
        logger.warning(
            "OPENAI_API_KEY not set — predictions will use HGB fallback only. "
            "Add it to .env to enable the live context agent."
        )
    yield
    _models.clear()


app = FastAPI(
    title="Court Edge Agent",
    description="NBA player prop intelligence — live context agent + HGB fallback",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Service liveness probe."""
    return HealthResponse(version=app.version)


@app.post("/predict", response_model=PredictResponse, tags=["predictions"])
async def predict_endpoint(request: PredictRequest) -> PredictResponse:
    """Generate a player prop projection.

    Primary path: fetches live NBA data and calls GPT-4o for contextual reasoning.
    Fallback path: uses the offline HGB model when OpenAI is unavailable.
    """
    from court_edge_agent.agents.live_predict import live_predict

    opponent = request.opponent or "UNK"
    home_away = request.home_away or "HOME"

    try:
        result = await live_predict(
            player_name=request.player_name,
            game_date=request.game_date,
            market=request.market,  # type: ignore[arg-type]
            opponent=opponent,
            home_away=home_away,
            prop_line=request.prop_line,
            season=settings.default_season,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Prediction failed for request=%s", request)
        raise HTTPException(status_code=500, detail="Internal prediction error") from exc

    return PredictResponse(
        player_name=result.player_name,
        game_date=result.game_date,
        market=result.market,
        projection=result.projection,
        prop_line=result.prop_line,
        edge=result.edge,
        lean=result.lean,
        confidence=result.confidence,
        explanation=result.explanation,
        source=result.source,
    )


def _season_for_date(date_str: str | None) -> str:
    """Return the NBA season string (e.g. '2025-26') that contains the given date.

    NBA seasons start in October. If date_str is None, uses today.
    """
    from datetime import date as _date
    d = _date.fromisoformat(date_str) if date_str else _date.today()
    year = d.year
    if d.month >= 10:
        return f"{year}-{str(year + 1)[-2:]}"
    return f"{year - 1}-{str(year)[-2:]}"


@app.get("/player/{player_name}/history", response_model=PlayerHistoryResponse, tags=["players"])
async def player_history(
    player_name: str,
    market: str = Query(default="points", pattern="^(points|rebounds|assists|threes_made)$"),
    before_date: str | None = Query(default=None, description="ISO date — return games strictly before this date"),
    limit: int = Query(default=5, ge=1, le=20),
) -> PlayerHistoryResponse:
    """Return the last N game log entries for a player / market combo.

    Strategy:
      1. Query the local SQLite DB (fast, covers stored seasons).
      2. If fewer than *limit* rows are found, fall back to a live fetch from
         stats.nba.com for the season that contains *before_date* (or today).
    """
    import asyncio
    import sqlite3

    from court_edge_agent.data.storage import TABLE_GAME_LOGS

    # --- 1. Try ESPN first — always current, covers all seasons ---
    try:
        from court_edge_agent.data.nba_client import fetch_player_game_logs_espn

        espn_entries = await asyncio.to_thread(
            fetch_player_game_logs_espn, player_name, market, limit, before_date
        )

        if espn_entries:
            return PlayerHistoryResponse(
                player_name=player_name,
                market=market,
                games=[
                    GameLogEntry(game_date=e["game_date"], matchup=str(e["matchup"]), value=float(e["value"]))
                    for e in espn_entries
                ],
            )
        logger.info("ESPN returned no entries for '%s' — falling back to DB", player_name)

    except Exception as exc:
        logger.warning("ESPN fetch failed for '%s': %s — falling back to DB", player_name, exc)

    # --- 2. Fall back to local DB ---
    conn = sqlite3.connect(str(settings.db_path))
    try:
        db_params: list = [player_name]
        db_query = (
            f"SELECT game_date, matchup, {market} FROM {TABLE_GAME_LOGS}"
            " WHERE player_name = ?"
        )
        if before_date:
            db_query += " AND game_date < ?"
            db_params.append(before_date)
        db_query += " ORDER BY game_date DESC LIMIT ?"
        db_params.append(limit)
        rows = conn.execute(db_query, db_params).fetchall()
    finally:
        conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No game logs found for '{player_name}'")

    games = [
        GameLogEntry(game_date=r[0], matchup=r[1] or "", value=float(r[2]) if r[2] is not None else 0.0)
        for r in reversed(rows)
    ]
    return PlayerHistoryResponse(player_name=player_name, market=market, games=games)


@app.post("/slate", response_model=SlateResponse, tags=["predictions"])
async def slate_endpoint(request: SlateRequest) -> SlateResponse:
    """Run full-slate edge analysis and return ranked picks."""
    from court_edge_agent.agents.slate_agent import run_slate_analysis

    try:
        result = await run_slate_analysis(
            game_date=str(request.game_date) if request.game_date else None,
            markets=request.markets,
            min_edge=request.min_edge,
            top_n=request.top_n,
        )
    except Exception as exc:
        logger.exception("Slate analysis failed for request=%s", request)
        raise HTTPException(status_code=500, detail="Internal slate analysis error") from exc

    return SlateResponse.model_validate(result)
