"""Live context agent: fetches fresh NBA data and calls GPT-4o for reasoning.

Architecture
------------
For each /predict request the agent:
  1. Fetches (in parallel via asyncio.gather + to_thread):
       a. Player's last 5 games + season averages + vs-opponent splits
       b. Opponent's defensive profile (pts/reb/ast allowed, DRTG rank)
  2. Fetches the current injury report for both teams.
  3. Looks up any stored prop line for this player/date/market.
  4. Optionally includes the HGB model's numerical baseline as an anchor.
  5. Sends a structured context prompt to GPT-4o.
  6. Parses the JSON response into a LiveProjection object.

On any failure (API down, key missing, parse error) it falls back to the
existing HGB/Ridge offline model via ``predict()`` in models/predict.py.
"""

from __future__ import annotations

import asyncio
import json
import textwrap
from dataclasses import dataclass
from datetime import date

from openai import OpenAI

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.data.nba_client import (
    fetch_injury_report,
    fetch_opponent_defense,
    fetch_player_context,
    search_player_id,
)
from court_edge_agent.data.storage import load_prop_lines
from court_edge_agent.models.baseline import StatMarket

logger = get_logger(__name__)

_MARKET_LABEL: dict[str, str] = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "threes_made": "3-pointers made",
}

_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an NBA prop analyst. Given the context below, return a JSON object.

    Context provided:
    - player_name, game_date, market, prop_line (if any)
    - last_5_games: list of {date, pts/reb/ast/3pm, min}
    - season_averages: {pts, reb, ast, 3pm, min}
    - vs_opponent_this_season: {games, avg_stat, sample_size}
    - opponent_defense: {pts_allowed, reb_allowed, ast_allowed, drtg_rank}
    - injury_context: string (may be empty)
    - model_projection: float (statistical anchor — do not ignore this)
    - stored_prop_line: float | null (from odds data, if available)

    Rules:
    1. Your projection must be between model_projection * 0.75 and model_projection * 1.25.
       Do not produce a projection wildly different from the model anchor.
    2. explanation must be exactly 2-3 sentences. The first sentence states the projection
       and primary reason. The second sentence addresses the matchup. The third (if present)
       addresses a risk factor or injury note. Do not list independent snippets.
    3. If back-to-back is mentioned, it must adjust the projection downward and be
       explained as a reason. Do not flag it and then project over the line.
    4. confidence: "high" only if the last 5 games are consistent AND matchup is favorable.
       "low" if the injury report affects a key teammate or the vs-opponent sample is < 3 games.

    Return format:
    {
      "projection": float,
      "confidence": "high" | "medium" | "low",
      "lean": "over" | "under" | null,
      "explanation": ["sentence 1", "sentence 2", "sentence 3 (optional)"]
    }
""")


def _extract_player_team(player_ctx: dict) -> str | None:
    """Infer the player's team abbreviation from their most recent game matchup."""
    recent = player_ctx.get("recent_games", [])
    if not recent:
        return None
    matchup = str(recent[-1].get("matchup", ""))
    if " vs. " in matchup:
        return matchup.split(" vs. ")[0].strip()
    if " @ " in matchup:
        return matchup.split(" @ ")[0].strip()
    parts = matchup.split()
    return parts[0] if parts else None


def _format_injury_context(injury_report: dict[str, dict[str, str]]) -> str:
    """Format the injury dict into a readable string for the GPT-4o prompt."""
    if not injury_report:
        return ""
    lines = []
    for player, info in injury_report.items():
        team = info.get("team", "")
        status = info.get("status", "Unknown")
        reason = info.get("reason", "unknown")
        team_str = f" ({team})" if team else ""
        lines.append(f"- {player}{team_str}: {status} — {reason}")
    return "\n".join(lines)


def _format_context_prompt(
    player_name: str,
    market: str,
    game_date: date,
    opponent: str,
    home_away: str,
    prop_line: float | None,
    season: str,
    player_ctx: dict,
    opp_defense: dict,
    hgb_baseline: float | None,
    injury_context: str,
    stored_prop_line: float | None,
) -> str:
    market_label = _MARKET_LABEL.get(market, market)
    recent = player_ctx.get("recent_games", [])
    season_avgs = player_ctx.get("season_avgs", {})
    vs_opp = player_ctx.get("vs_opponent")

    # Recent games table
    if recent:
        header = "Date       | Matchup              | W/L | Pts | Reb | Ast | 3PM | Min"
        sep = "-" * len(header)
        rows = [header, sep]
        for g in recent:
            rows.append(
                f"{g.get('date',''):<10} | {str(g.get('matchup','')):<20} | "
                f"{str(g.get('wl','')):<3} | "
                f"{g.get('points', '-')!s:<3} | "
                f"{g.get('rebounds', '-')!s:<3} | "
                f"{g.get('assists', '-')!s:<3} | "
                f"{g.get('threes_made', '-')!s:<3} | "
                f"{g.get('minutes', '-')!s}"
            )
        recent_table = "\n".join(rows)
    else:
        recent_table = "No recent game data available."

    # Season averages
    sa = season_avgs
    season_avg_str = (
        f"Pts: {sa.get('points','?')}  Reb: {sa.get('rebounds','?')}  "
        f"Ast: {sa.get('assists','?')}  3PM: {sa.get('threes_made','?')}  "
        f"Min: {sa.get('minutes','?')}  (over {sa.get('games_played','?')} games)"
    )

    # vs-opponent
    if vs_opp:
        vo = vs_opp
        vs_opp_str = (
            f"Pts: {vo.get('points','?')}  Reb: {vo.get('rebounds','?')}  "
            f"Ast: {vo.get('assists','?')}  3PM: {vo.get('threes_made','?')}  "
            f"({vo.get('games_played','?')} game(s) this season)"
        )
    else:
        vs_opp_str = "First matchup vs this opponent this season — no split data available."

    # Opponent defense
    if opp_defense:
        od = opp_defense
        n = od.get("n_teams", 30)
        drtg = f"{od.get('drtg', 'N/A')}" if od.get("drtg") else "N/A"
        opp_str = (
            f"Team: {od.get('team_name', opponent)}\n"
            f"  Pts allowed/game: {od.get('pts_allowed','?')}  "
            f"Reb allowed/game: {od.get('reb_allowed','?')}  "
            f"Ast allowed/game: {od.get('ast_allowed','?')}\n"
            f"  Defensive Rating: {drtg}  "
            f"Def. rank (pts allowed, lower=tougher): #{od.get('drtg_rank','?')} of {n}"
        )
    else:
        opp_str = "Opponent defensive data unavailable."

    # Prop line
    prop_str = f"{prop_line:.1f}" if prop_line is not None else "not provided"

    # Model baseline
    baseline_str = f"{hgb_baseline:.1f} {market_label}" if hgb_baseline is not None else "unavailable"

    # Stored prop line from odds DB
    stored_str = f"{stored_prop_line:.1f}" if stored_prop_line is not None else "null"

    # Injury context
    injury_str = injury_context if injury_context else "(none)"

    return textwrap.dedent(f"""\
        ## Prediction Request
        Player: {player_name}
        Game:   {home_away} vs {opponent}  ({game_date})
        Market: {market_label}
        Prop line: {prop_str}
        Season: {season}

        ## Last 5 Games
        {recent_table}

        ## Season Averages
        {season_avg_str}

        ## vs {opponent} This Season
        {vs_opp_str}

        ## Opponent Defensive Profile ({opponent})
        {opp_str}

        ## Injury Report (this game)
        {injury_str}

        ## Statistical Model Baseline
        HGB model projection (model_projection): {baseline_str}
        Stored prop line from odds data (stored_prop_line): {stored_str}
        (Your projection must stay within 25% of model_projection.)

        ## Your Task
        Project {player_name}'s {market_label} total for this game.
        Follow all rules in the system prompt exactly.
        Respond with JSON only — no markdown, no preamble.
    """)


@dataclass
class LiveProjection:
    player_name: str
    game_date: date
    market: str
    projection: float
    prop_line: float | None
    edge: float | None
    lean: str | None
    confidence: str
    explanation: list[str]
    source: str  # "llm" | "hgb_fallback"


async def live_predict(
    player_name: str,
    game_date: date,
    market: StatMarket,
    opponent: str,
    home_away: str,
    prop_line: float | None = None,
    season: str | None = None,
) -> LiveProjection:
    """Fetch live NBA context and call GPT-4o to produce a projection.

    Player context and opponent defense are fetched in parallel via
    asyncio.gather + asyncio.to_thread. Falls back to the offline HGB model
    if OpenAI is unavailable or fails.
    """
    season = season or settings.default_season

    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set — falling back to HGB model")
        return _hgb_fallback(player_name, game_date, market, opponent, home_away, prop_line, season)

    # ------------------------------------------------------------------
    # 1. Resolve player ID
    # ------------------------------------------------------------------
    player_id = search_player_id(player_name, season)
    if player_id is None:
        raise ValueError(f"Player not found: '{player_name}'")

    # ------------------------------------------------------------------
    # 2. Fetch live context in parallel
    # ------------------------------------------------------------------
    logger.info("Fetching live context for %s vs %s (%s)…", player_name, opponent, season)
    try:
        player_ctx, opp_defense = await asyncio.gather(
            asyncio.to_thread(fetch_player_context, player_id, player_name, season, opponent),
            asyncio.to_thread(fetch_opponent_defense, opponent, season),
        )
    except Exception as exc:
        logger.warning("Failed to fetch player context: %s — falling back to HGB", exc)
        return _hgb_fallback(player_name, game_date, market, opponent, home_away, prop_line, season)

    # If player_ctx itself raised, the gather would have propagated it above.
    # But if opp_defense raised individually we still get an empty dict from
    # the gather (since it's in a separate task). Normalise here just in case.
    if not isinstance(opp_defense, dict):
        opp_defense = {}

    # ------------------------------------------------------------------
    # 3. Fetch injury report for both teams (sequential — fast ESPN call)
    # ------------------------------------------------------------------
    injury_report: dict[str, dict[str, str]] = {}
    try:
        player_team = _extract_player_team(player_ctx) if isinstance(player_ctx, dict) else None
        team_abbrs = [t for t in [player_team, opponent] if t]
        injury_report = await asyncio.to_thread(fetch_injury_report, team_abbrs)
    except Exception as exc:
        logger.warning("Injury report fetch failed: %s — continuing without it", exc)

    injury_context = _format_injury_context(injury_report)

    # ------------------------------------------------------------------
    # 4. Look up stored prop line (user-provided takes precedence)
    # ------------------------------------------------------------------
    stored_prop_line: float | None = None
    if prop_line is None:
        try:
            prop_df = load_prop_lines(player_name, str(game_date), str(market))
            if not prop_df.empty:
                stored_prop_line = float(prop_df.iloc[0]["line"])
                logger.info(
                    "Using stored prop line %.1f for %s %s on %s",
                    stored_prop_line, player_name, market, game_date,
                )
        except Exception as exc:
            logger.debug("Could not load stored prop line: %s", exc)

    effective_prop_line = prop_line if prop_line is not None else stored_prop_line

    # ------------------------------------------------------------------
    # 5. Get HGB baseline (silent — used as anchor in the prompt)
    # ------------------------------------------------------------------
    hgb_baseline: float | None = None
    try:
        from court_edge_agent.models.predict import predict as hgb_predict
        from court_edge_agent.models.train import load_models
        hgb_proj = hgb_predict(
            player_name=player_name,
            game_date=game_date,
            market=market,
            opponent=opponent,
            home_away=home_away,
            prop_line=None,
            models=load_models(),
            season=season,
        )
        hgb_baseline = hgb_proj.projection
    except Exception as exc:
        logger.debug("HGB baseline unavailable: %s", exc)

    # ------------------------------------------------------------------
    # 6. Build prompt and call GPT-4o
    # ------------------------------------------------------------------
    prompt = _format_context_prompt(
        player_name=player_name,
        market=market,
        game_date=game_date,
        opponent=opponent,
        home_away=home_away,
        prop_line=effective_prop_line,
        season=season,
        player_ctx=player_ctx if isinstance(player_ctx, dict) else {},
        opp_defense=opp_defense,
        hgb_baseline=hgb_baseline,
        injury_context=injury_context,
        stored_prop_line=stored_prop_line,
    )

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("LLM call failed: %s — falling back to HGB", exc)
        return _hgb_fallback(player_name, game_date, market, opponent, home_away, prop_line, season)

    # ------------------------------------------------------------------
    # 7. Parse LLM response into LiveProjection
    # ------------------------------------------------------------------
    try:
        projection = float(parsed["projection"])
        confidence = str(parsed.get("confidence", "medium"))
        lean_raw = parsed.get("lean")
        lean: str | None = str(lean_raw) if lean_raw and lean_raw != "null" else None
        explanation = parsed.get("explanation", [])
        if isinstance(explanation, str):
            explanation = [explanation]
        explanation = [str(s) for s in explanation]
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Could not parse LLM response (%s): %s — falling back", exc, raw[:200])
        return _hgb_fallback(player_name, game_date, market, opponent, home_away, prop_line, season)

    edge: float | None = None
    if effective_prop_line is not None:
        edge = round(projection - effective_prop_line, 2)
        if lean is None:
            lean = "over" if edge > 0 else "under"

    logger.info(
        "LLM projection: %s %s = %.1f (confidence=%s, lean=%s)",
        player_name, market, projection, confidence, lean,
    )

    return LiveProjection(
        player_name=player_name,
        game_date=game_date,
        market=market,
        projection=round(projection, 2),
        prop_line=effective_prop_line,
        edge=edge,
        lean=lean,
        confidence=confidence,
        explanation=explanation,
        source="llm",
    )


def _hgb_fallback(
    player_name: str,
    game_date: date,
    market: StatMarket,
    opponent: str,
    home_away: str,
    prop_line: float | None,
    season: str,
) -> LiveProjection:
    """Fall back to the offline HGB model when the LLM is unavailable."""
    from court_edge_agent.models.predict import predict as hgb_predict
    from court_edge_agent.models.train import load_models

    logger.info("Using HGB fallback for %s %s", player_name, market)
    proj = hgb_predict(
        player_name=player_name,
        game_date=game_date,
        market=market,
        opponent=opponent,
        home_away=home_away,
        prop_line=prop_line,
        models=load_models(),
        season=season,
    )
    return LiveProjection(
        player_name=proj.player_name,
        game_date=proj.game_date,
        market=proj.market,
        projection=proj.projection,
        prop_line=proj.prop_line,
        edge=proj.edge,
        lean=proj.lean,
        confidence=proj.confidence,
        explanation=proj.explanation,
        source="hgb_fallback",
    )
