"""Incremental data refresh + retrain pipeline.

Designed to run on a weekly or monthly schedule to keep the system fresh.

What it does:
  1. Discovers every player already tracked in the database.
  2. Skips any player whose most recent game log is newer than --stale-days
     (avoids hammering the API when data is already up to date).
  3. Re-fetches the full current season for stale players and upserts.
  4. Rebuilds features for the current season (which also re-joins the
     latest opponent defensive stats across the updated dataset).
  5. Retrains both Ridge and HGB models and runs time-series CV.

Usage:
    # Weekly: skip players whose data is < 7 days old
    python scripts/update_pipeline.py --stale-days 7

    # Force full refresh regardless of freshness
    python scripts/update_pipeline.py --stale-days 0

    # Monthly, only current season
    python scripts/update_pipeline.py --stale-days 30 --season 2024-25

Scheduling (macOS cron — run every Monday at 06:00):
    crontab -e
    0 6 * * 1 cd /path/to/court-edge-agent && .venv/bin/python scripts/update_pipeline.py >> logs/update.log 2>&1

Scheduling (macOS launchd — see docs/update_pipeline.plist.example):
    cp docs/update_pipeline.plist.example ~/Library/LaunchAgents/com.court-edge-agent.update.plist
    launchctl load ~/Library/LaunchAgents/com.court-edge-agent.update.plist
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.data.nba_client import fetch_player_game_logs, normalize_game_logs
from court_edge_agent.data.storage import (
    init_db,
    load_features,
    load_game_logs,
    upsert_features,
    upsert_game_logs,
)
from court_edge_agent.features.build_features import build_features_for_dataset
from court_edge_agent.models.evaluate import timeseries_cv_evaluation
from court_edge_agent.models.train import train_all_markets, train_hgb_markets

logger = get_logger("update_pipeline")


def _last_game_date(player_id: int, season: str) -> date | None:
    """Return the most recent game_date for this player/season in the DB."""
    logs = load_game_logs(player_id=player_id, season=season)
    if logs.empty:
        return None
    return logs["game_date"].max()


def _is_stale(player_id: int, season: str, stale_days: int) -> bool:
    """Return True if the player's data is older than stale_days."""
    if stale_days == 0:
        return True  # force-refresh mode
    last = _last_game_date(player_id, season)
    if last is None:
        return True
    return (date.today() - last).days > stale_days


def refresh_player(player_id: int, player_name: str, season: str) -> int:
    """Re-fetch and upsert game logs for one player. Returns rows written."""
    try:
        raw = fetch_player_game_logs(player_id, season)
        if raw.empty:
            logger.info("No games returned for %s (%d) in %s", player_name, player_id, season)
            return 0
        normalized = normalize_game_logs(raw, player_id, player_name, season)
        rows = upsert_game_logs(normalized)
        logger.info("Refreshed %d games for %s (%s)", rows, player_name, season)
        return rows
    except Exception as exc:
        logger.error("Failed to refresh %s (%d): %s", player_name, player_id, exc)
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Incremental data refresh and model retrain")
    parser.add_argument(
        "--season",
        default=settings.default_season,
        help="Season to refresh (default: current season from config)",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=7,
        dest="stale_days",
        help="Only re-fetch players whose last game is older than this many days (0 = always refresh)",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="Refresh data only; skip model retraining",
    )
    args = parser.parse_args()

    settings.ensure_dirs()
    init_db()

    # -------------------------------------------------------------------------
    # Step 1: Discover all tracked players for this season
    # -------------------------------------------------------------------------
    all_logs = load_game_logs(season=args.season)
    if all_logs.empty:
        logger.error(
            "No game logs found for season %s. Run ingest_player_logs.py first.", args.season
        )
        sys.exit(1)

    tracked = (
        all_logs[["player_id", "player_name"]]
        .drop_duplicates()
        .sort_values("player_name")
        .reset_index(drop=True)
    )
    logger.info(
        "Found %d tracked players for season %s", len(tracked), args.season
    )

    # -------------------------------------------------------------------------
    # Step 2: Re-fetch stale players
    # -------------------------------------------------------------------------
    stale = [
        (int(row["player_id"]), str(row["player_name"]))
        for _, row in tracked.iterrows()
        if _is_stale(int(row["player_id"]), args.season, args.stale_days)
    ]
    fresh_count = len(tracked) - len(stale)

    if fresh_count > 0:
        logger.info(
            "Skipping %d player(s) — data is < %d days old", fresh_count, args.stale_days
        )
    if not stale:
        logger.info("All players are up to date. Nothing to refresh.")
        if args.skip_train:
            return
    else:
        logger.info("Refreshing %d stale player(s)...", len(stale))
        total_rows = 0
        for pid, name in stale:
            total_rows += refresh_player(pid, name, args.season)
            time.sleep(settings.nba_api_delay_seconds)
        logger.info("Refresh complete — %d game log rows upserted", total_rows)

    if args.skip_train:
        logger.info("--skip-train set; exiting without retraining.")
        return

    # -------------------------------------------------------------------------
    # Step 3: Rebuild features for this season (includes updated opp stats)
    # -------------------------------------------------------------------------
    logger.info("Rebuilding features for season %s...", args.season)
    game_logs = load_game_logs(season=args.season)
    features = build_features_for_dataset(game_logs)
    if features.empty:
        logger.error("Feature build produced no rows — aborting retrain.")
        sys.exit(1)
    rows_written = upsert_features(features)
    logger.info("Stored %d feature rows", rows_written)

    # -------------------------------------------------------------------------
    # Step 4: Retrain on ALL available seasons (more data = better models)
    # -------------------------------------------------------------------------
    logger.info("Loading all features (all seasons) for training...")
    all_features = load_features()  # no season filter → cross-season
    if all_features.empty:
        logger.error("No features available for training.")
        sys.exit(1)

    logger.info("Training Ridge + HGB models on %d rows...", len(all_features))
    train_all_markets(all_features, save_dir=settings.models_dir)
    train_hgb_markets(all_features, save_dir=settings.models_dir)

    # -------------------------------------------------------------------------
    # Step 5: Time-series CV report (primary quality metric)
    # -------------------------------------------------------------------------
    logger.info("Running time-series CV evaluation...")
    cv = timeseries_cv_evaluation(all_features, n_splits=5)
    if not cv.empty:
        logger.info("CV results (mean ± std MAE):\n%s", cv.to_string(index=False))

    logger.info(
        "Update complete. Models saved to %s. Next run recommended in %d days.",
        settings.models_dir,
        args.stale_days or 7,
    )


if __name__ == "__main__":
    main()
