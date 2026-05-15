"""Seed mock prop lines for testing the Today page.

Pulls each player's rolling 5-game averages from the local DB, then creates
realistic prop lines with strategic offsets to simulate a mix of high, medium,
and low confidence edges — both over and under.

Usage
-----
    python scripts/seed_mock_today.py                  # seeds for 2025-04-13
    python scripts/seed_mock_today.py --date 2025-04-10
    python scripts/seed_mock_today.py --clear           # remove mock lines first

The mock lines use bookmaker "mock" so they're easy to identify.  After seeding,
visit the Today page with:
    http://localhost:3000/today?... (backend date param)

Or hit the API directly:
    curl "http://localhost:8000/today?date=2025-04-13"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the src package is importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from court_edge_agent.config import settings
from court_edge_agent.common.logging import get_logger

logger = get_logger(__name__)

DEFAULT_DATE = "2025-04-13"

# Hand-crafted lines: (player, market, offset_from_avg, bookmaker)
# Offset > 0 → line is ABOVE the rolling avg → model will lean UNDER
# Offset < 0 → line is BELOW the rolling avg → model will lean OVER
# Use .5 endings like real sportsbooks do.
#
# Mix of edge magnitudes:
#   |offset| >= 3.5 → high confidence
#   |offset| 1.5–3.5 → medium
#   |offset| < 1.5 → low / no edge

_LINE_SPECS: list[tuple[str, str, float, str]] = [
    # High-confidence OVER edges
    ("Anthony Edwards",   "points",       -4.5, "draftkings"),
    ("Victor Wembanyama", "rebounds",     -4.0, "draftkings"),
    ("Alperen Sengun",    "assists",      -3.5, "fanduel"),
    # High-confidence UNDER edges
    ("Jalen Brunson",     "points",       +4.5, "draftkings"),
    ("Anthony Davis",     "rebounds",     +4.0, "fanduel"),
    # Medium-confidence OVER
    ("Joel Embiid",       "points",       -2.5, "draftkings"),
    ("Austin Reaves",     "assists",      -2.0, "fanduel"),
    ("Bam Adebayo",       "rebounds",     -2.5, "draftkings"),
    ("Anfernee Simons",   "threes_made",  -2.0, "betmgm"),
    # Medium-confidence UNDER
    ("Aaron Gordon",      "points",       +2.5, "fanduel"),
    ("Andrew Wiggins",    "threes_made",  +2.0, "draftkings"),
    # Low-confidence / no edge (line matches avg closely)
    ("Anthony Edwards",   "rebounds",     +0.3, "draftkings"),
    ("Jalen Brunson",     "assists",      -0.5, "fanduel"),
    ("Bennedict Mathurin","points",       +0.5, "draftkings"),
    ("Aaron Nesmith",     "points",       -0.5, "fanduel"),
    # Extras — cover all markets for top players
    ("Anthony Edwards",   "assists",      -1.5, "fanduel"),
    ("Anthony Edwards",   "threes_made",  +0.5, "draftkings"),
    ("Alperen Sengun",    "points",       -1.5, "draftkings"),
    ("Alperen Sengun",    "rebounds",     +1.0, "fanduel"),
    ("Joel Embiid",       "rebounds",     -1.0, "draftkings"),
    ("Joel Embiid",       "assists",      +1.0, "fanduel"),
    ("Victor Wembanyama", "points",       -2.0, "draftkings"),
    ("Victor Wembanyama", "assists",      +0.5, "fanduel"),
    ("Austin Reaves",     "points",       -1.0, "draftkings"),
    ("Austin Reaves",     "threes_made",  +0.5, "fanduel"),
    ("Anfernee Simons",   "points",       -1.5, "draftkings"),
    ("Anfernee Simons",   "assists",      +0.5, "betmgm"),
    ("Bam Adebayo",       "points",       +0.5, "fanduel"),
    ("Bam Adebayo",       "assists",      -1.0, "draftkings"),
    ("Aaron Nesmith",     "threes_made",  -0.5, "fanduel"),
]

_MARKET_COL = {
    "points":      "points",
    "rebounds":    "rebounds",
    "assists":     "assists",
    "threes_made": "threes_made",
}


def _round_to_half(value: float) -> float:
    """Round to nearest 0.5 (real sportsbook lines always end in .0 or .5)."""
    return round(value * 2) / 2


def _rolling_avg(conn: sqlite3.Connection, player_name: str, stat: str, before_date: str, n: int = 5) -> float | None:
    """Return rolling N-game average for a player/stat ending before *before_date*."""
    col = _MARKET_COL.get(stat)
    if not col:
        return None
    rows = conn.execute(
        f"SELECT {col} FROM player_game_logs"
        " WHERE player_name = ? AND game_date < ?"
        " ORDER BY game_date DESC LIMIT ?",
        [player_name, before_date, n],
    ).fetchall()
    if not rows:
        return None
    values = [r[0] for r in rows if r[0] is not None]
    return sum(values) / len(values) if values else None


def _fake_odds(line: float, offset: float) -> tuple[int, int]:
    """Generate plausible American odds: juice depends on how far offset is from zero."""
    abs_offset = abs(offset)
    if abs_offset >= 3.5:
        # Strong lean — sharp-looking odds
        if offset < 0:  # over
            return (-130, +110)
        else:           # under
            return (+110, -130)
    elif abs_offset >= 1.5:
        return (-115, -105)
    else:
        return (-110, -110)


def seed(date: str, clear_first: bool = False) -> None:
    conn = sqlite3.connect(str(settings.db_path))
    fetched_at = datetime.now(tz=timezone.utc).isoformat()

    if clear_first:
        deleted = conn.execute(
            "DELETE FROM prop_lines WHERE bookmaker = 'mock' OR game_date = ?",
            [date],
        ).rowcount
        conn.commit()
        print(f"Cleared {deleted} existing lines for {date}.")

    rows_inserted = 0
    rows_skipped = 0

    for player_name, market, offset, bookmaker in _LINE_SPECS:
        avg = _rolling_avg(conn, player_name, market, date)
        if avg is None:
            print(f"  SKIP  {player_name:28s} {market:12s} — no game logs found")
            rows_skipped += 1
            continue

        raw_line = avg + offset
        if raw_line <= 0:
            raw_line = 0.5
        line = _round_to_half(raw_line)
        over_odds, under_odds = _fake_odds(line, offset)

        conn.execute(
            """
            INSERT OR REPLACE INTO prop_lines
                (player_name, game_date, market, line, over_odds, under_odds, bookmaker, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [player_name, date, market, line, over_odds, under_odds, bookmaker, fetched_at],
        )
        lean = "OVER" if offset < 0 else "UNDER"
        edge_label = f"edge ~{abs(offset):+.1f}"
        print(
            f"  {'✓':2s}  {player_name:28s} {market:12s} line={line:5.1f}  "
            f"{lean:5s}  {edge_label}  ({bookmaker})"
        )
        rows_inserted += 1

    conn.commit()
    conn.close()

    print()
    print(f"Seeded {rows_inserted} mock prop lines for {date}  ({rows_skipped} skipped)")
    print()
    print("Test the Today page:")
    print(f"  http://localhost:3000/today  (update date query if needed)")
    print(f"  curl 'http://localhost:8000/today?date={date}'")
    print()
    print("Note: mock lines use your real rolling averages + synthetic offsets.")
    print("      Bookmaker shown as 'draftkings' / 'fanduel' / 'betmgm' for realism.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed mock prop lines for the Today page")
    parser.add_argument("--date", default=DEFAULT_DATE, help=f"Game date (default: {DEFAULT_DATE})")
    parser.add_argument("--clear", action="store_true", help="Delete existing lines for this date first")
    args = parser.parse_args()

    print(f"Seeding mock prop lines for {args.date}…")
    print()
    seed(args.date, clear_first=args.clear)


if __name__ == "__main__":
    main()
