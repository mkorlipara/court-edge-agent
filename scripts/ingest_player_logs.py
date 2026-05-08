"""Ingest historical NBA player game logs from nba_api and store in SQLite.

Usage:
    python scripts/ingest_player_logs.py --season 2024-25 --players "Stephen Curry" "LeBron James"
    python scripts/ingest_player_logs.py --season 2024-25 --top-n 50
"""

import argparse
import sys
import time
from pathlib import Path

# Make src/ importable when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.data.nba_client import (
    fetch_player_game_logs,
    get_active_players_df,
    normalize_game_logs,
    search_player_id,
)
from court_edge_agent.data.storage import init_db, upsert_game_logs

logger = get_logger("ingest")


def ingest_player(player_id: int, player_name: str, season: str) -> int:
    """Fetch and store game logs for a single player. Returns row count."""
    try:
        raw = fetch_player_game_logs(player_id, season)
        if raw.empty:
            logger.info("No games found for %s (%d) in %s", player_name, player_id, season)
            return 0
        normalized = normalize_game_logs(raw, player_id, player_name, season)
        rows = upsert_game_logs(normalized)
        logger.info("Ingested %d games for %s", rows, player_name)
        return rows
    except Exception as exc:
        logger.error("Failed to ingest %s (%d): %s", player_name, player_id, exc)
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest NBA player game logs")
    parser.add_argument("--season", default=settings.default_season, help="NBA season (e.g. 2024-25)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--players", nargs="+", help="Player names to ingest")
    group.add_argument(
        "--top-n", type=int, default=None,
        help="Ingest top-N currently active players (alphabetical by full name)",
    )
    args = parser.parse_args()

    settings.ensure_dirs()
    init_db()

    if args.players:
        # Resolve each name to a (player_id, canonical_name) pair using the static list
        targets: list[tuple[int, str]] = []
        for name in args.players:
            try:
                pid = search_player_id(name)
            except ValueError as exc:
                logger.error("%s", exc)
                continue
            if pid is None:
                logger.error("Could not resolve player: '%s' — skipping", name)
                continue
            targets.append((pid, name))

    elif args.top_n is not None:
        active_df = get_active_players_df()
        active_df = active_df.sort_values("full_name").head(args.top_n)
        targets = [(int(r["id"]), str(r["full_name"])) for _, r in active_df.iterrows()]
        logger.info("Selected top-%d active players for ingestion", len(targets))

    else:
        logger.info("No players specified. Use --players or --top-n.")
        logger.info("Example: python scripts/ingest_player_logs.py --players 'Stephen Curry'")
        sys.exit(0)

    if not targets:
        logger.error("No valid players to ingest.")
        sys.exit(1)

    total_rows = 0
    for pid, name in targets:
        total_rows += ingest_player(pid, name, args.season)
        time.sleep(settings.nba_api_delay_seconds)

    logger.info("Ingestion complete. Total rows inserted: %d", total_rows)


if __name__ == "__main__":
    main()
