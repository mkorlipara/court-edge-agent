"""Walk-forward backtesting: evaluate predictions game-by-game on held-out data.

This is not a rolling retrain (too slow for MVP). Instead it:
  1. Trains on all games before --cutoff.
  2. Evaluates predictions on all games after --cutoff.
  3. Outputs per-market MAE / RMSE vs. rolling baselines.

Usage:
    python scripts/run_backtest.py --season 2024-25 --cutoff 2025-01-01
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.data.storage import load_features
from court_edge_agent.models.evaluate import full_evaluation_report
from court_edge_agent.models.train import date_split, train_all_markets

logger = get_logger("backtest")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtest evaluation")
    parser.add_argument("--season", default=settings.default_season)
    parser.add_argument("--cutoff", default=settings.train_cutoff_date)
    parser.add_argument("--output", default=None, help="Optional CSV path to save report")
    args = parser.parse_args()

    settings.ensure_dirs()

    logger.info("Loading features for season %s...", args.season)
    features = load_features(season=args.season)

    if features.empty:
        logger.error("No features found. Run build_features.py first.")
        sys.exit(1)

    train, test = date_split(features, args.cutoff)
    logger.info("Train: %d rows | Test: %d rows", len(train), len(test))

    if test.empty:
        logger.error("Test set is empty. Adjust --cutoff to an earlier date.")
        sys.exit(1)

    models = train_all_markets(features_df=features, cutoff_date=args.cutoff)
    report = full_evaluation_report(models, test)

    print("\n=== Backtest Report ===")
    print(report.to_string(index=False))

    if args.output:
        report.to_csv(args.output, index=False)
        logger.info("Report saved to %s", args.output)


if __name__ == "__main__":
    main()
