"""Build rolling features from ingested game logs and store to SQLite.

Usage:
    python scripts/build_features.py --season 2024-25
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.data.storage import init_db, load_game_logs, upsert_features
from court_edge_agent.features.build_features import build_features_for_dataset

logger = get_logger("build_features")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rolling features from game logs")
    parser.add_argument("--season", default=settings.default_season)
    args = parser.parse_args()

    settings.ensure_dirs()
    init_db()

    logger.info("Loading game logs for season %s...", args.season)
    game_logs = load_game_logs(season=args.season)

    if game_logs.empty:
        logger.error(
            "No game logs found for season %s. Run ingest_player_logs.py first.",
            args.season,
        )
        sys.exit(1)

    logger.info("Loaded %d game log rows for %d players", len(game_logs), game_logs["player_id"].nunique())

    features = build_features_for_dataset(game_logs)
    if features.empty:
        logger.error("Feature building produced no rows.")
        sys.exit(1)

    rows = upsert_features(features)
    logger.info("Feature build complete. Stored %d rows.", rows)


if __name__ == "__main__":
    main()
