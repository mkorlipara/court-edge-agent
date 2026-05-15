"""Client for The Odds API — fetches NBA player prop lines.

Usage requires ODDS_API_KEY in .env (optional; the rest of the system works
without it). If the key is absent, all public functions return empty lists and
log a warning instead of raising.

Market name mapping (Odds API → internal):
    player_points    → points
    player_rebounds  → rebounds
    player_assists   → assists
    player_threes    → threes_made

API efficiency notes:
- ``fetch_all_markets_today`` batches all 4 markets in a single per-event call,
  saving ~75% of monthly quota vs. the per-market approach.
- ``get_cached_lines_if_fresh`` checks the local DB before hitting the API;
  lines fetched within the last 2 hours are re-used automatically.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import requests

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings

logger = get_logger(__name__)

_ODDS_BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"
_ODDS_TIMEOUT = 20
_CACHE_TTL_HOURS = 2  # re-use stored lines within this window

# Maps Odds API market key → our internal market name
_MARKET_MAP: dict[str, str] = {
    "player_points": "points",
    "player_rebounds": "rebounds",
    "player_assists": "assists",
    "player_threes": "threes_made",
}

# Reverse: internal → Odds API key
_MARKET_MAP_REVERSE: dict[str, str] = {v: k for k, v in _MARKET_MAP.items()}

_ALL_ODDS_MARKETS = ",".join(_MARKET_MAP.keys())


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _get_events(api_key: str) -> list[dict]:
    """Fetch upcoming NBA events from The Odds API."""
    url = f"{_ODDS_BASE}/events"
    resp = requests.get(url, params={"apiKey": api_key}, timeout=_ODDS_TIMEOUT)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def _fetch_event_props(event_id: str, markets_csv: str, api_key: str) -> dict:
    """Fetch player props for a single event; *markets_csv* may be comma-separated."""
    url = f"{_ODDS_BASE}/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": markets_csv,
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=_ODDS_TIMEOUT)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def _parse_outcomes(data: dict, fetched_at: str) -> list[dict]:
    """Extract a flat list of prop-line dicts from a single event's API response."""
    results: list[dict] = []
    for bookmaker in data.get("bookmakers", []):
        bk_key = str(bookmaker.get("key", "unknown"))
        for mkt in bookmaker.get("markets", []):
            mkt_key = mkt.get("key", "")
            internal_market = _MARKET_MAP.get(mkt_key)
            if internal_market is None:
                continue
            for outcome in mkt.get("outcomes", []):
                name = str(outcome.get("description", "")).strip()
                side = str(outcome.get("name", "")).lower()
                point = outcome.get("point")
                price = outcome.get("price")
                if not name or point is None or price is None:
                    continue

                entry = next(
                    (
                        r for r in results
                        if r["player_name"] == name
                        and r["bookmaker"] == bk_key
                        and r["market"] == internal_market
                        and r["line"] == float(point)
                    ),
                    None,
                )
                if entry is None:
                    entry = {
                        "player_name": name,
                        "market": internal_market,
                        "line": float(point),
                        "over_odds": None,
                        "under_odds": None,
                        "bookmaker": bk_key,
                        "timestamp": fetched_at,
                    }
                    results.append(entry)

                if "over" in side:
                    entry["over_odds"] = int(price)
                elif "under" in side:
                    entry["under_odds"] = int(price)
    return results


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def get_cached_lines_if_fresh(game_date: str, markets: list[str]) -> list[dict]:
    """Return prop lines stored in SQLite for *game_date* if they were fetched
    within the last ``_CACHE_TTL_HOURS`` hours.  Returns ``[]`` on cache miss.
    """
    from court_edge_agent.data.storage import TABLE_PROP_LINES

    cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)).isoformat()
    placeholders = ",".join("?" * len(markets))
    query = (
        f"SELECT player_name, market, line, over_odds, under_odds, bookmaker, fetched_at"
        f" FROM {TABLE_PROP_LINES}"
        f" WHERE game_date = ? AND market IN ({placeholders}) AND fetched_at >= ?"
    )
    try:
        conn = sqlite3.connect(str(settings.db_path))
        rows = conn.execute(query, [game_date, *markets, cutoff]).fetchall()
        conn.close()
    except Exception as exc:
        logger.debug("Cache read failed: %s", exc)
        return []

    if not rows:
        return []

    logger.info(
        "Cache hit: %d prop lines for date=%s markets=%s (TTL=%dh)",
        len(rows), game_date, markets, _CACHE_TTL_HOURS,
    )
    return [
        {
            "player_name": r[0],
            "market": r[1],
            "line": r[2],
            "over_odds": r[3],
            "under_odds": r[4],
            "bookmaker": r[5],
            "fetched_at": r[6],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_all_markets_today(
    markets: list[str] | None = None,
    game_date: str | None = None,
    skip_cache: bool = False,
    max_retries: int = 3,
) -> list[dict]:
    """Fetch player prop lines for all *markets* in a single pass.

    Batches all requested markets in one API call per event (vs. one call per
    market per event), saving ~75% of monthly quota.

    Checks the local DB cache first; if fresh lines are available (within
    ``_CACHE_TTL_HOURS``) they are returned without hitting the API.

    Args:
        markets: internal market names to fetch; defaults to all four.
        game_date: ISO date string for caching purposes; defaults to today.
        skip_cache: force a fresh API fetch even if cache is warm.

    Returns a flat list of dicts::

        [
            {
                "player_name": "Jalen Brunson",
                "market": "points",
                "line": 26.5,
                "over_odds": -115,
                "under_odds": -105,
                "bookmaker": "draftkings",
                "timestamp": "2025-04-01T12:00:00+00:00",
            },
            ...
        ]
    """
    from datetime import date as _date

    target_markets = markets or list(_MARKET_MAP_REVERSE.keys())
    target_date = game_date or _date.today().isoformat()

    # --- Cache check ---
    if not skip_cache:
        cached = get_cached_lines_if_fresh(target_date, target_markets)
        if cached:
            return cached

    if not settings.odds_api_key:
        logger.warning("ODDS_API_KEY not set — cannot fetch prop lines")
        return []

    # Build comma-separated Odds API market keys
    odds_markets_csv = ",".join(
        _MARKET_MAP_REVERSE[m] for m in target_markets if m in _MARKET_MAP_REVERSE
    )
    if not odds_markets_csv:
        logger.warning("No valid markets requested: %s", target_markets)
        return []

    api_key = settings.odds_api_key
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            events = _get_events(api_key)
            all_results: list[dict] = []
            fetched_at = datetime.now(tz=timezone.utc).isoformat()

            for event in events:
                event_id = event.get("id")
                if not event_id:
                    continue
                try:
                    data = _fetch_event_props(event_id, odds_markets_csv, api_key)
                    all_results.extend(_parse_outcomes(data, fetched_at))
                except Exception as exc:
                    logger.debug("Could not fetch props for event %s: %s", event_id, exc)

            logger.info(
                "Fetched %d prop lines across %d events for markets=%s",
                len(all_results), len(events), target_markets,
            )
            return all_results

        except Exception as exc:
            logger.warning("Odds API attempt %d/%d failed: %s", attempt, max_retries, exc)
            last_exc = exc
            time.sleep(2 ** attempt)

    logger.error("Failed to fetch prop lines after %d attempts: %s", max_retries, last_exc)
    return []


def fetch_nba_player_props(market: str, max_retries: int = 3) -> list[dict]:
    """Fetch prop lines for a single *market*.  Delegates to ``fetch_all_markets_today``.

    Kept for backwards compatibility with ``scripts/fetch_odds.py``.
    """
    results = fetch_all_markets_today(markets=[market], max_retries=max_retries, skip_cache=True)
    return [r for r in results if r["market"] == market]
