"""Train Ridge and HGB models for all stat markets.

Both model types are trained and persisted. HGB (hgb_*.pkl) is the default
used by the prediction API; Ridge (ridge_*.pkl) is retained as a named baseline.

Usage:
    python scripts/train_baseline.py --season 2024-25 --cutoff 2025-01-01
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.data.storage import load_features
from court_edge_agent.models.evaluate import full_evaluation_report, timeseries_cv_evaluation
from court_edge_agent.models.train import date_split, train_all_markets, train_hgb_markets

logger = get_logger("train_baseline")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Ridge and HGB baseline models")
    parser.add_argument("--season", default=None, help="Season to load features for (default: all seasons)")
    parser.add_argument("--cutoff", default=settings.train_cutoff_date, help="Train/test cutoff date (ISO)")
    args = parser.parse_args()

    settings.ensure_dirs()

    logger.info("Loading features%s...", f" for season {args.season}" if args.season else "")
    features = load_features(season=args.season)

    if features.empty:
        logger.error("No features found. Run build_features.py first.")
        sys.exit(1)

    logger.info("Training Ridge models with cutoff=%s ...", args.cutoff)
    ridge_models = train_all_markets(
        features_df=features,
        cutoff_date=args.cutoff,
        save_dir=settings.models_dir,
    )

    logger.info("Training HGB models with cutoff=%s ...", args.cutoff)
    hgb_models = train_hgb_markets(
        features_df=features,
        cutoff_date=args.cutoff,
        save_dir=settings.models_dir,
    )

    # Single-cutoff evaluation on the held-out test set (HGB)
    _, test = date_split(features, args.cutoff)
    if test.empty:
        logger.warning("Test set is empty — no evaluation possible with cutoff=%s", args.cutoff)
        return

    logger.info("=== Single-cutoff evaluation (HGB) ===")
    report = full_evaluation_report(hgb_models, test)
    if not report.empty:
        logger.info("\n%s", report.to_string(index=False))

    # Time-series cross-validation (primary metric)
    logger.info("=== Time-series cross-validation (HGB, 5 folds) ===")
    cv_report = timeseries_cv_evaluation(features, n_splits=5)
    if not cv_report.empty:
        logger.info("\n%s", cv_report.to_string(index=False))

    logger.info(
        "Training complete. Ridge + HGB models saved to %s", settings.models_dir
    )

    _ = ridge_models  # retained for logging; saved to disk above


if __name__ == "__main__":
    main()
