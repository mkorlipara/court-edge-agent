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
    TodayGame,
    TodayLine,
    TodayResponse,
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


@app.get("/next-slate-date", tags=["meta"])
async def next_slate_date_endpoint(
    from_date: str | None = Query(default=None, description="Start searching from this ISO date; defaults to today"),
) -> dict:
    """Return the nearest calendar date (today or future) that has NBA games on ESPN.

    Searches up to 7 days ahead. Used by the Today page to auto-select the right date
    rather than defaulting to today when the season is over or games haven't been posted yet.
    """
    import asyncio
    from datetime import date as _date, timedelta

    from court_edge_agent.data.nba_client import fetch_todays_slate

    start = _date.fromisoformat(from_date) if from_date else _date.today()
    for i in range(8):
        check = start + timedelta(days=i)
        slate = await asyncio.to_thread(fetch_todays_slate, check.isoformat())
        if slate:
            return {"date": check.isoformat()}

    return {"date": None, "note": "No games found in the next 7 days"}


@app.get("/today", response_model=TodayResponse, tags=["predictions"])
async def today_endpoint(
    date: str | None = Query(default=None, description="ISO date (YYYY-MM-DD); defaults to today"),
    markets: str = Query(default="points,rebounds,assists,threes_made", description="Comma-separated markets"),
    skip_cache: bool = Query(default=False, description="Force fresh Odds API fetch"),
) -> TodayResponse:
    """Return today's slate, live prop lines, and HGB-scored edges in one shot.

    Designed for the Today dashboard: visit the page and everything auto-loads.
    Lines are cached in SQLite for up to 2 hours to conserve Odds API quota.
    Players without local game log data are still shown (line only, no edge).
    """
    import asyncio
    import pandas as pd
    from datetime import date as _date, datetime, timezone

    from court_edge_agent.data.nba_client import fetch_todays_slate, get_team_roster, search_player_id
    from court_edge_agent.data.odds_client import fetch_all_markets_today, get_cached_lines_if_fresh
    from court_edge_agent.data.storage import load_game_logs, upsert_prop_lines
    from court_edge_agent.models.predict import predict

    target_date = date or _date.today().isoformat()
    market_list = [m.strip() for m in markets.split(",") if m.strip()]

    # 1. Today's slate (ESPN)
    slate = await asyncio.to_thread(fetch_todays_slate, target_date)
    games: list[TodayGame] = [
        TodayGame(home_team=g["home_team"], away_team=g["away_team"])
        for g in slate
    ]

    # 2. Build player → game context map from rosters
    player_game_map: dict[str, dict] = {}
    for game in slate:
        home, away = game["home_team"], game["away_team"]
        for team_abbr, opponent_abbr, home_away in [
            (home, away, "HOME"),
            (away, home, "AWAY"),
        ]:
            try:
                roster = await asyncio.to_thread(get_team_roster, team_abbr)
                for player in roster:
                    if player not in player_game_map:
                        player_game_map[player] = {
                            "team": team_abbr,
                            "opponent": opponent_abbr,
                            "home_away": home_away,
                        }
            except Exception as exc:
                logger.debug("Roster fetch failed for %s: %s", team_abbr, exc)

    # 3. Fetch prop lines — cache-first, API fallback
    from_cache = False
    raw_lines: list[dict] = []

    if not skip_cache:
        raw_lines = await asyncio.to_thread(get_cached_lines_if_fresh, target_date, market_list)
        if raw_lines:
            from_cache = True

    if not raw_lines:
        raw_lines = await asyncio.to_thread(
            fetch_all_markets_today,
            market_list,
            target_date,
            True,  # skip_cache inside the function since we already checked
        )
        # Persist to DB for cache + later slate analysis
        if raw_lines:
            lines_df = pd.DataFrame(raw_lines)
            lines_df["game_date"] = target_date
            try:
                await asyncio.to_thread(upsert_prop_lines, lines_df)
            except Exception as exc:
                logger.warning("Failed to cache prop lines: %s", exc)

    # 4. Deduplicate: one consensus line per player+market
    #    Prefer DraftKings, then FanDuel, then first in list
    _PREFERRED_BOOKS = ("draftkings", "fanduel", "betmgm", "pointsbet")

    def _pick_line(group: list[dict]) -> dict:
        for book in _PREFERRED_BOOKS:
            for entry in group:
                if entry["bookmaker"] == book:
                    return entry
        return group[0]

    grouped: dict[tuple, list[dict]] = {}
    for line in raw_lines:
        key = (line["player_name"], line["market"])
        grouped.setdefault(key, []).append(line)

    deduped = [_pick_line(v) for v in grouped.values()]

    # 5. Score each deduplicated line with HGB model
    import sqlite3 as _sqlite3

    models = load_models()
    parsed_date = _date.fromisoformat(target_date)

    def _has_logs(player_name: str) -> bool:
        pid = search_player_id(player_name)
        return pid is not None and not load_game_logs(player_id=pid).empty

    def _team_from_logs(player_name: str) -> str | None:
        """Derive team abbreviation from the player's most recent game log matchup.
        Matchup format is 'NYK vs. BOS' or 'NYK @ BOS' — first 3 chars = player's team.
        """
        try:
            conn = _sqlite3.connect(str(settings.db_path))
            row = conn.execute(
                "SELECT matchup FROM player_game_logs"
                " WHERE player_name = ? AND game_date < ?"
                " ORDER BY game_date DESC LIMIT 1",
                [player_name, target_date],
            ).fetchone()
            conn.close()
            if row and row[0]:
                return str(row[0]).strip()[:3]
        except Exception:
            pass
        return None

    all_lines: list[TodayLine] = []
    scored = 0

    for entry in deduped:
        player_name = entry["player_name"]
        market = entry["market"]
        line_val = float(entry["line"])
        # Use roster-derived context if available; fall back to game-log team derivation
        # so matchup + scoring still work for mock/historical dates with no ESPN slate.
        game_ctx = player_game_map.get(player_name, {})
        if not game_ctx:
            derived_team = _team_from_logs(player_name)
            if derived_team:
                game_ctx = {"team": derived_team, "opponent": None, "home_away": "HOME"}
        score_opponent = game_ctx.get("opponent") or "UNK"
        score_home_away = game_ctx.get("home_away") or "HOME"

        projection: float | None = None
        edge: float | None = None
        lean: str | None = None

        if _has_logs(player_name):
            try:
                result = predict(
                    player_name=player_name,
                    game_date=parsed_date,
                    market=market,  # type: ignore[arg-type]
                    opponent=score_opponent,
                    home_away=score_home_away,
                    prop_line=line_val,
                    models=models,
                )
                projection = round(result.projection, 1)
                edge = round(result.projection - line_val, 2)
                lean = "over" if edge > 0 else "under"
                scored += 1
            except Exception as exc:
                logger.debug("HGB scoring failed for %s %s: %s", player_name, market, exc)

        all_lines.append(TodayLine(
            player_name=player_name,
            team=game_ctx.get("team"),
            opponent=game_ctx.get("opponent"),  # may be None for historical/mock dates
            home_away=game_ctx.get("home_away"),  # type: ignore[arg-type]
            market=market,  # type: ignore[arg-type]
            line=line_val,
            over_odds=entry.get("over_odds"),
            under_odds=entry.get("under_odds"),
            bookmaker=entry.get("bookmaker", ""),
            projection=projection,
            edge=edge,
            lean=lean,  # type: ignore[arg-type]
        ))

    # 6. Top edges: scored lines sorted by |edge|
    top_edges = sorted(
        [l for l in all_lines if l.edge is not None],
        key=lambda x: abs(x.edge),  # type: ignore[arg-type]
        reverse=True,
    )[:20]

    note: str | None = None
    if not settings.odds_api_key:
        note = "ODDS_API_KEY not set — no live lines available. Add it to .env."
    elif not raw_lines and not from_cache:
        note = "No prop lines returned from Odds API. There may be no games today or the API quota is exhausted."
    elif scored == 0 and raw_lines:
        note = "Lines fetched but no players matched local game logs. Run scripts/ingest_player_logs.py first."

    return TodayResponse(
        date=target_date,
        games=games,
        top_edges=top_edges,
        all_lines=all_lines,
        total_lines=len(all_lines),
        scored_lines=scored,
        fetched_at=datetime.now(tz=timezone.utc).isoformat(),
        odds_api_available=bool(settings.odds_api_key),
        from_cache=from_cache,
        note=note,
    )
