"""Client for The Odds API — fetches NBA player prop lines.

Usage requires ODDS_API_KEY in .env (optional; the rest of the system works
without it). If the key is absent, all public functions return empty lists and
log a warning instead of raising.

Market name mapping (Odds API → internal):
    player_points    → points
    player_rebounds  → rebounds
    player_assists   → assists
    player_threes    → threes_made
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings

logger = get_logger(__name__)

_ODDS_BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"
_ODDS_TIMEOUT = 20

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


def _get_events(api_key: str) -> list[dict]:
    """Fetch upcoming NBA events from The Odds API."""
    url = f"{_ODDS_BASE}/events"
    params = {"apiKey": api_key}
    resp = requests.get(url, params=params, timeout=_ODDS_TIMEOUT)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def _fetch_event_props(event_id: str, market_key: str, api_key: str) -> list[dict]:
    """Fetch player props for a single event and market."""
    url = f"{_ODDS_BASE}/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": market_key,
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=_ODDS_TIMEOUT)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def fetch_nba_player_props(market: str, max_retries: int = 3) -> list[dict]:
    """Fetch current NBA player prop lines for *market* from The Odds API.

    *market* is an internal market name: ``"points"``, ``"rebounds"``,
    ``"assists"``, or ``"threes_made"``.

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

    Returns ``[]`` if ODDS_API_KEY is not configured or on any unrecoverable error.
    """
    if not settings.odds_api_key:
        logger.warning("ODDS_API_KEY not set — skipping prop line fetch for market=%s", market)
        return []

    odds_market = _MARKET_MAP_REVERSE.get(market)
    if odds_market is None:
        logger.warning("Unknown market '%s'; valid values: %s", market, list(_MARKET_MAP_REVERSE))
        return []

    api_key = settings.odds_api_key
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            events = _get_events(api_key)
            results: list[dict] = []
            fetched_at = datetime.now(tz=timezone.utc).isoformat()  # noqa: UP017

            for event in events:
                event_id = event.get("id")
                if not event_id:
                    continue

                try:
                    data = _fetch_event_props(event_id, odds_market, api_key)
                except Exception as exc:
                    logger.debug("Could not fetch props for event %s: %s", event_id, exc)
                    continue

                # Iterate bookmakers → markets → outcomes
                for bookmaker in data.get("bookmakers", []):
                    bk_key = str(bookmaker.get("key", "unknown"))
                    for mkt in bookmaker.get("markets", []):
                        if mkt.get("key") != odds_market:
                            continue
                        for outcome in mkt.get("outcomes", []):
                            name = str(outcome.get("description", "")).strip()
                            side = str(outcome.get("name", "")).lower()
                            point = outcome.get("point")
                            price = outcome.get("price")

                            if not name or point is None or price is None:
                                continue

                            # Find or create the entry for this player/bookmaker combo
                            entry = next(
                                (
                                    r for r in results
                                    if r["player_name"] == name
                                    and r["bookmaker"] == bk_key
                                    and r["market"] == market
                                    and r["line"] == float(point)
                                ),
                                None,
                            )
                            if entry is None:
                                entry = {
                                    "player_name": name,
                                    "market": market,
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

            logger.info(
                "Fetched %d prop lines for market=%s across %d event(s)",
                len(results), market, len(events),
            )
            return results

        except Exception as exc:
            logger.warning(
                "Odds API attempt %d/%d failed for market=%s: %s",
                attempt, max_retries, market, exc,
            )
            last_exc = exc
            time.sleep(2 ** attempt)

    logger.error(
        "Failed to fetch prop lines for market=%s after %d attempts: %s",
        market, max_retries, last_exc,
    )
    return []
