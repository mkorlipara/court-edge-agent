"""Training pipeline: date-based train/test split + model persistence."""

import pickle
from pathlib import Path

import pandas as pd

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings
from court_edge_agent.models.baseline import STAT_MARKETS, HGBModel, RidgeModel

logger = get_logger(__name__)

# Union type alias used by callers that accept either model flavour
AnyModel = RidgeModel | HGBModel


def date_split(
    features_df: pd.DataFrame,
    cutoff_date: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split features into train/test by date (never by random).

    All games *before* cutoff_date go to train; on/after go to test.
    """
    cutoff = pd.Timestamp(cutoff_date or settings.train_cutoff_date).date()
    df = features_df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    train = df[df["game_date"] < cutoff].copy()
    test = df[df["game_date"] >= cutoff].copy()
    logger.info(
        "Date split at %s → train=%d rows, test=%d rows", cutoff, len(train), len(test)
    )
    return train, test


def train_all_markets(
    features_df: pd.DataFrame,
    cutoff_date: str | None = None,
    save_dir: Path | None = None,
) -> dict[str, RidgeModel]:
    """Train one Ridge model per stat market.

    Args:
        features_df: Full feature DataFrame (all players, all games).
        cutoff_date: ISO date string; games before this date are used for training.
        save_dir: If provided, persist model artifacts to disk as ridge_*.pkl.

    Returns:
        Dict mapping market name to fitted RidgeModel.
    """
    train, _ = date_split(features_df, cutoff_date)
    models: dict[str, RidgeModel] = {}

    for market in STAT_MARKETS:
        if market not in train.columns:
            logger.warning("Target column '%s' not found; skipping", market)
            continue
        model = RidgeModel(target=market)  # type: ignore[arg-type]
        model.fit(train)
        models[market] = model

    if save_dir:
        _save_ridge_models(models, save_dir)

    return models


def train_hgb_markets(
    features_df: pd.DataFrame,
    cutoff_date: str | None = None,
    save_dir: Path | None = None,
) -> dict[str, HGBModel]:
    """Train one HGB model per stat market.

    HGB handles NaN natively, so no imputation preprocessing is needed.

    Args:
        features_df: Full feature DataFrame (all players, all games).
        cutoff_date: ISO date string; games before this date are used for training.
        save_dir: If provided, persist model artifacts to disk as hgb_*.pkl.

    Returns:
        Dict mapping market name to fitted HGBModel.
    """
    train, _ = date_split(features_df, cutoff_date)
    models: dict[str, HGBModel] = {}

    for market in STAT_MARKETS:
        if market not in train.columns:
            logger.warning("Target column '%s' not found; skipping", market)
            continue
        model = HGBModel(target=market)  # type: ignore[arg-type]
        model.fit(train)
        models[market] = model

    if save_dir:
        _save_hgb_models(models, save_dir)

    return models


def _save_ridge_models(models: dict[str, RidgeModel], save_dir: Path) -> None:
    """Persist Ridge models to disk as pickle files."""
    save_dir.mkdir(parents=True, exist_ok=True)
    for market, model in models.items():
        path = save_dir / f"ridge_{market}.pkl"
        with open(path, "wb") as f:
            pickle.dump(model, f)
        logger.info("Saved Ridge model: %s", path)


def _save_hgb_models(models: dict[str, HGBModel], save_dir: Path) -> None:
    """Persist HGB models to disk as pickle files."""
    save_dir.mkdir(parents=True, exist_ok=True)
    for market, model in models.items():
        path = save_dir / f"hgb_{market}.pkl"
        with open(path, "wb") as f:
            pickle.dump(model, f)
        logger.info("Saved HGB model: %s", path)


def load_models(save_dir: Path | None = None) -> dict[str, AnyModel]:
    """Load models from disk — HGB preferred, Ridge as fallback.

    Returns a dict mapping market name to the best available fitted model.
    """
    load_dir = save_dir or settings.models_dir
    models: dict[str, AnyModel] = {}
    for market in STAT_MARKETS:
        hgb_path = load_dir / f"hgb_{market}.pkl"
        ridge_path = load_dir / f"ridge_{market}.pkl"
        if hgb_path.exists():
            with open(hgb_path, "rb") as f:
                models[market] = pickle.load(f)
            logger.info("Loaded HGB model: %s", hgb_path)
        elif ridge_path.exists():
            with open(ridge_path, "rb") as f:
                models[market] = pickle.load(f)
            logger.info("Loaded Ridge model (fallback): %s", ridge_path)
        else:
            logger.warning("No model file found for market: %s", market)
    return models


def load_ridge_models(save_dir: Path | None = None) -> dict[str, RidgeModel]:
    """Load Ridge models explicitly (for evaluation / comparison)."""
    load_dir = save_dir or settings.models_dir
    models: dict[str, RidgeModel] = {}
    for market in STAT_MARKETS:
        path = load_dir / f"ridge_{market}.pkl"
        if not path.exists():
            logger.warning("Ridge model file not found: %s", path)
            continue
        with open(path, "rb") as f:
            models[market] = pickle.load(f)
        logger.info("Loaded Ridge model: %s", path)
    return models
