"""Fetch NBA player prop lines from The Odds API and store them in SQLite.

Requires ODDS_API_KEY in .env. If the key is absent the script logs a
warning and exits cleanly — it never crashes the API server.

Usage::

    python scripts/fetch_odds.py
    python scripts/fetch_odds.py --date 2025-04-15   # tag rows with a specific date
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import pandas as pd

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.data.odds_client import fetch_nba_player_props
from court_edge_agent.data.storage import init_db, upsert_prop_lines

logger = get_logger(__name__)

_MARKETS = ["points", "rebounds", "assists", "threes_made"]


def main(game_date: str | None = None, markets: list[str] | None = None) -> None:
    if not settings.odds_api_key:
        logger.warning(
            "ODDS_API_KEY is not set — skipping prop line ingestion. "
            "Add it to .env to enable this feature."
        )
        sys.exit(0)

    today = game_date or str(date.today())
    init_db()

    selected_markets = markets or _MARKETS
    invalid = sorted(set(selected_markets) - set(_MARKETS))
    if invalid:
        logger.error("Invalid market(s): %s. Allowed: %s", invalid, _MARKETS)
        sys.exit(1)

    total = 0
    for market in selected_markets:
        logger.info("Fetching prop lines for market=%s …", market)
        props = fetch_nba_player_props(market)
        if not props:
            logger.info("No prop lines returned for market=%s", market)
            continue

        df = pd.DataFrame(props)
        df["game_date"] = today

        written = upsert_prop_lines(df)
        total += written
        logger.info("Stored %d prop line(s) for market=%s", written, market)

    logger.info("fetch_odds complete — %d total row(s) written for date=%s", total, today)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch NBA prop lines from The Odds API")
    parser.add_argument(
        "--date",
        default=None,
        help="Game date to tag rows with (YYYY-MM-DD, default: today)",
    )
    parser.add_argument(
        "--markets",
        nargs="+",
        default=None,
        help=f"Optional subset of markets. Allowed: {_MARKETS}",
    )
    args = parser.parse_args()
    main(game_date=args.date, markets=args.markets)
