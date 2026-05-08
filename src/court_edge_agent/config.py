"""Central configuration loaded from environment variables / .env file."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the project root (two levels up from this file:
# src/court_edge_agent/config.py → src/court_edge_agent → src → project root).
# Using an anchor here means all default paths are CWD-independent, which
# matters for the MCP server that Cursor launches from an arbitrary directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    app_env: str = "development"
    log_level: str = "INFO"

    # Paths — absolute by default; override via env vars if needed
    data_dir: Path = _DATA_DIR
    raw_dir: Path = _DATA_DIR / "raw"
    processed_dir: Path = _DATA_DIR / "processed"
    models_dir: Path = _DATA_DIR / "models"
    db_path: Path = _DATA_DIR / "court_edge.db"

    # NBA API
    nba_api_delay_seconds: float = Field(default=0.6, ge=0.0)

    # Ingestion
    default_season: str = "2024-25"

    # Model / evaluation
    train_cutoff_date: str = "2025-01-01"
    test_start_date: str = "2025-01-01"

    # Confidence thresholds (absolute edge vs. line)
    confidence_high_threshold: float = 3.0
    confidence_medium_threshold: float = 1.5

    # OpenAI — used by the live context agent
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # The Odds API — optional; prop lines are skipped when this is empty
    odds_api_key: str = ""

    # API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    def ensure_dirs(self) -> None:
        """Create all data directories if they don't exist."""
        for d in (self.data_dir, self.raw_dir, self.processed_dir, self.models_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
