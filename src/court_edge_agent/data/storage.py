"""SQLite persistence layer using pandas + sqlite3.

Design decision: Use SQLite + pandas rather than a full ORM to keep
the stack minimal for MVP. Swap to Postgres by changing the connection string.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings

logger = get_logger(__name__)

# Table names
TABLE_GAME_LOGS = "player_game_logs"
TABLE_FEATURES = "player_features"
TABLE_PROP_LINES = "prop_lines"


def _get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, col_type: str
) -> None:
    """Add a column to an existing table only if it does not already exist."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        logger.info("Migrated: added column %s.%s", table, column)


def init_db(db_path: Path | None = None) -> None:
    """Create tables if they don't exist, and migrate schema additions."""
    conn = _get_conn(db_path)
    with conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_GAME_LOGS} (
                player_id    INTEGER NOT NULL,
                player_name  TEXT    NOT NULL,
                season       TEXT    NOT NULL,
                game_id      TEXT    NOT NULL,
                game_date    TEXT    NOT NULL,
                matchup      TEXT,
                wl           TEXT,
                minutes      REAL,
                points       REAL,
                rebounds     REAL,
                assists      REAL,
                threes_made  REAL,
                threes_attempted REAL,
                fg_made      REAL,
                fg_attempted REAL,
                ft_made      REAL,
                ft_attempted REAL,
                plus_minus   REAL,
                PRIMARY KEY (player_id, game_id)
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_FEATURES} (
                player_id    INTEGER NOT NULL,
                player_name  TEXT    NOT NULL,
                game_date    TEXT    NOT NULL,
                season       TEXT    NOT NULL,
                opponent     TEXT,
                home_away    TEXT,
                days_rest    INTEGER,
                back_to_back_flag INTEGER,
                rolling_3_points  REAL,
                rolling_5_points  REAL,
                rolling_10_points REAL,
                rolling_3_rebounds  REAL,
                rolling_5_rebounds  REAL,
                rolling_10_rebounds REAL,
                rolling_3_assists   REAL,
                rolling_5_assists   REAL,
                rolling_10_assists  REAL,
                rolling_3_threes    REAL,
                rolling_5_threes    REAL,
                rolling_10_threes   REAL,
                rolling_3_minutes   REAL,
                rolling_5_minutes   REAL,
                rolling_10_minutes  REAL,
                season_avg_points_to_date   REAL,
                season_avg_rebounds_to_date REAL,
                season_avg_assists_to_date  REAL,
                season_avg_threes_to_date   REAL,
                season_avg_minutes_to_date  REAL,
                opp_pts_allowed REAL,
                opp_reb_allowed REAL,
                opp_ast_allowed REAL,
                opp_3pm_allowed REAL,
                points      REAL,
                rebounds    REAL,
                assists     REAL,
                threes_made REAL,
                PRIMARY KEY (player_id, game_date)
            )
        """)
        # Migrate existing databases that predate the opp_* columns
        for col in ("opp_pts_allowed", "opp_reb_allowed", "opp_ast_allowed", "opp_3pm_allowed"):
            _add_column_if_missing(conn, TABLE_FEATURES, col, "REAL")

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_PROP_LINES} (
                player_name  TEXT NOT NULL,
                game_date    TEXT NOT NULL,
                market       TEXT NOT NULL,
                line         REAL NOT NULL,
                over_odds    INTEGER,
                under_odds   INTEGER,
                bookmaker    TEXT,
                fetched_at   TEXT NOT NULL,
                PRIMARY KEY (player_name, game_date, market, bookmaker)
            )
        """)
    logger.info("Database initialized at %s", db_path or settings.db_path)
    conn.close()


def upsert_game_logs(df: pd.DataFrame, db_path: Path | None = None) -> int:
    """Insert or replace game log rows. Returns number of rows written."""
    if df.empty:
        return 0
    conn = _get_conn(db_path)
    df = df.copy()
    df["game_date"] = df["game_date"].astype(str)
    # Delete existing rows for these players to avoid PRIMARY KEY conflicts on re-ingest
    player_ids = df["player_id"].unique().tolist()
    placeholders = ",".join("?" * len(player_ids))
    with conn:
        conn.execute(
            f"DELETE FROM {TABLE_GAME_LOGS} WHERE player_id IN ({placeholders})",
            player_ids,
        )
    df.to_sql(TABLE_GAME_LOGS, conn, if_exists="append", index=False, method="multi")
    count = len(df)
    conn.close()
    logger.info("Upserted %d game log rows", count)
    return count


def upsert_features(df: pd.DataFrame, db_path: Path | None = None) -> int:
    """Insert or replace feature rows."""
    if df.empty:
        return 0
    conn = _get_conn(db_path)
    df = df.copy()
    df["game_date"] = df["game_date"].astype(str)
    # Delete existing rows for these players to avoid PRIMARY KEY conflicts on rebuild
    player_ids = df["player_id"].unique().tolist()
    placeholders = ",".join("?" * len(player_ids))
    with conn:
        conn.execute(
            f"DELETE FROM {TABLE_FEATURES} WHERE player_id IN ({placeholders})",
            player_ids,
        )
    df.to_sql(TABLE_FEATURES, conn, if_exists="append", index=False, method="multi")
    count = len(df)
    conn.close()
    logger.info("Upserted %d feature rows", count)
    return count


def load_game_logs(
    player_id: int | None = None,
    season: str | None = None,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Load game logs with optional filters."""
    conn = _get_conn(db_path)
    query = f"SELECT * FROM {TABLE_GAME_LOGS} WHERE 1=1"
    params: list = []
    if player_id is not None:
        query += " AND player_id = ?"
        params.append(player_id)
    if season is not None:
        query += " AND season = ?"
        params.append(season)
    query += " ORDER BY game_date ASC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    return df


def load_features(
    player_id: int | None = None,
    season: str | None = None,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Load feature rows with optional filters."""
    conn = _get_conn(db_path)
    query = f"SELECT * FROM {TABLE_FEATURES} WHERE 1=1"
    params: list = []
    if player_id is not None:
        query += " AND player_id = ?"
        params.append(player_id)
    if season is not None:
        query += " AND season = ?"
        params.append(season)
    query += " ORDER BY game_date ASC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    return df


def upsert_prop_lines(df: pd.DataFrame, db_path: Path | None = None) -> int:
    """Insert or replace prop line rows from a DataFrame.

    Expected columns: player_name, game_date, market, line, over_odds,
    under_odds, bookmaker, fetched_at (all present in the flat list returned
    by ``fetch_nba_player_props``).

    Returns the number of rows written.
    """
    if df.empty:
        return 0

    conn = _get_conn(db_path)
    df = df.copy()
    df["game_date"] = df["game_date"].astype(str)

    # Ensure fetched_at is populated
    if "fetched_at" not in df.columns:
        df["fetched_at"] = datetime.now(tz=timezone.utc).isoformat()  # noqa: UP017

    required = {"player_name", "game_date", "market", "line", "bookmaker", "fetched_at"}
    missing = required - set(df.columns)
    if missing:
        logger.warning("upsert_prop_lines: missing columns %s — skipping", missing)
        conn.close()
        return 0

    with conn:
        for _, row in df.iterrows():
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {TABLE_PROP_LINES}
                    (player_name, game_date, market, line, over_odds, under_odds,
                     bookmaker, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["player_name"],
                    row["game_date"],
                    row["market"],
                    float(row["line"]),
                    int(row["over_odds"]) if row.get("over_odds") is not None else None,
                    int(row["under_odds"]) if row.get("under_odds") is not None else None,
                    row.get("bookmaker"),
                    row["fetched_at"],
                ),
            )
    count = len(df)
    conn.close()
    logger.info("Upserted %d prop line row(s)", count)
    return count


def load_prop_lines(
    player_name: str,
    game_date: str,
    market: str,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Load stored prop lines for a specific player / game date / market.

    Returns all matching rows (one per bookmaker). Returns an empty DataFrame
    when no data is found or the table does not yet exist.
    """
    conn = _get_conn(db_path)
    try:
        query = f"""
            SELECT * FROM {TABLE_PROP_LINES}
            WHERE player_name = ?
              AND game_date = ?
              AND market = ?
            ORDER BY fetched_at DESC
        """
        df = pd.read_sql_query(query, conn, params=[player_name, str(game_date), market])
    except Exception as exc:
        logger.debug("load_prop_lines query failed (table may not exist yet): %s", exc)
        df = pd.DataFrame()
    finally:
        conn.close()
    return df
