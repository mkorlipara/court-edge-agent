"""Thin wrapper around nba_api for fetching player game logs.

Network calls bypass nba_api's endpoint classes and use a requests.Session
directly. This gives us full control over headers, timeouts, and retries,
which is necessary because stats.nba.com requires a browser-like fingerprint
and can hang without Sec-Fetch-* headers.
"""

import time
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests
from nba_api.stats.endpoints.commonteamroster import CommonTeamRoster
from nba_api.stats.static import players as static_players
from nba_api.stats.static import teams as static_teams

from court_edge_agent.common.logging import get_logger
from court_edge_agent.config import settings

logger = get_logger(__name__)

_NBA_STATS_URL = "https://stats.nba.com/stats/playergamelog"
_NBA_TEAM_STATS_URL = "https://stats.nba.com/stats/leaguedashteamstats"

# Path to the Basketball Reference net ratings reference file
_NET_RATINGS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "reference" / "nba_net_ratings.xlsx"

# Full team name → 3-letter NBA abbreviation
_TEAM_NAME_TO_ABBR: dict[str, str] = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}


@lru_cache(maxsize=1)
def _load_net_ratings() -> pd.DataFrame:
    """Load the Basketball Reference net ratings xlsx into a keyed DataFrame.

    The file has a merged header row; actual column names are in the second row.
    Returns a DataFrame indexed by 3-letter team abbreviation with columns:
    drtg, ortg, nrtg, drtg_rank, w, l.
    Returns an empty DataFrame if the file is missing.
    """
    if not _NET_RATINGS_PATH.exists():
        logger.warning("Net ratings reference file not found at %s", _NET_RATINGS_PATH)
        return pd.DataFrame()

    try:
        # skiprows=1 skips the merged "Unadjusted / Adjusted" header row
        raw = pd.read_excel(_NET_RATINGS_PATH, skiprows=1, engine="openpyxl")

        # Rename to clean column names
        raw.columns = [
            "rk", "team", "conf", "div", "w", "l", "wl_pct",
            "mov", "ortg", "drtg", "nrtg",
            "mov_a", "ortg_a", "drtg_a", "nrtg_a",
        ]

        # Drop any trailing empty rows
        raw = raw.dropna(subset=["team"]).copy()
        raw["drtg"] = pd.to_numeric(raw["drtg"], errors="coerce")
        raw["ortg"] = pd.to_numeric(raw["ortg"], errors="coerce")
        raw["nrtg"] = pd.to_numeric(raw["nrtg"], errors="coerce")

        # Compute drtg_rank: rank 1 = best defense = lowest DRtg
        raw = raw.sort_values("drtg", ascending=True).reset_index(drop=True)
        raw["drtg_rank"] = raw.index + 1

        # Map full names to abbreviations
        raw["abbr"] = raw["team"].map(_TEAM_NAME_TO_ABBR)
        unmapped = raw[raw["abbr"].isna()]["team"].tolist()
        if unmapped:
            logger.warning("Unmapped team names in net ratings file: %s", unmapped)
        raw = raw.dropna(subset=["abbr"]).set_index("abbr")

        logger.info("Loaded net ratings for %d teams from reference file", len(raw))
        return raw

    except Exception as exc:
        logger.warning("Failed to load net ratings reference file: %s", exc)
        return pd.DataFrame()


def get_team_defense_from_reference(team_abbr: str) -> dict:
    """Look up a team's defensive stats from the local Basketball Reference file.

    Returns a dict with drtg, ortg, nrtg, drtg_rank, n_teams, or empty dict
    if the team is not found.
    """
    df = _load_net_ratings()
    if df.empty or team_abbr not in df.index:
        return {}

    row = df.loc[team_abbr]
    return {
        "team_name": team_abbr,
        "drtg": float(row["drtg"]),
        "ortg": float(row["ortg"]),
        "nrtg": float(row["nrtg"]),
        "drtg_rank": int(row["drtg_rank"]),
        "n_teams": len(df),
        "source": "reference",
    }

# Full browser fingerprint required by stats.nba.com.
# Requests missing Referer or Sec-Fetch-* often hang at the TCP read phase.
_NBA_HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Google Chrome";v="124", "Not:A-Brand";v="8", "Chromium";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}

_REQUEST_TIMEOUT = 60  # seconds — NBA API can be legitimately slow


def _make_session() -> requests.Session:
    """Create a requests Session pre-loaded with NBA headers."""
    session = requests.Session()
    session.headers.update(_NBA_HEADERS)
    return session


def _sleep() -> None:
    """Respect nba_api rate limits."""
    time.sleep(settings.nba_api_delay_seconds)


def _strip_smart_quotes(name: str) -> str:
    """Remove Unicode curly/smart quotes that macOS Terminal can inject.

    macOS auto-correct can replace ASCII " with \u201c/\u201d when the
    'Use smart quotes' setting is enabled, causing shell argument splitting
    to include the quote character as part of the string.
    """
    # Normalize to NFKD, then strip any remaining quote-like characters
    name = unicodedata.normalize("NFKD", name)
    return name.replace("\u201c", "").replace("\u201d", "").replace("\u2018", "").replace("\u2019", "").strip()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_all_players_df() -> pd.DataFrame:
    """Return all historical NBA players from nba_api's local static data.

    No network call — the JSON is bundled with the package.
    Columns: id, full_name, first_name, last_name, is_active.
    """
    return pd.DataFrame(static_players.get_players())


def get_active_players_df() -> pd.DataFrame:
    """Return currently active players from nba_api's local static data."""
    return pd.DataFrame(static_players.get_active_players())


def fetch_player_game_logs(
    player_id: int,
    season: str | None = None,
    season_type: str = "Regular Season",
    max_retries: int = 3,
) -> pd.DataFrame:
    """Fetch game-by-game logs for a single player in a season.

    Hits stats.nba.com directly via a requests.Session so we have full
    control over headers. Retries with exponential back-off on failure.

    Returns a DataFrame with raw NBA API column names (all-caps).
    """
    season = season or settings.default_season
    logger.info("Fetching game logs: player_id=%d  season=%s", player_id, season)

    params = {
        "PlayerID": player_id,
        "Season": season,
        "SeasonType": season_type,
        "LeagueID": "00",
    }

    session = _make_session()
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        _sleep()
        try:
            response = session.get(_NBA_STATS_URL, params=params, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            result_set = data["resultSets"][0]
            columns: list[str] = result_set["headers"]
            rows: list[list] = result_set["rowSet"]

            if not rows:
                logger.warning(
                    "No rows returned for player_id=%d season=%s (attempt %d/%d)",
                    player_id, season, attempt, max_retries,
                )
                last_exc = ValueError("Empty rowSet from NBA API")
                time.sleep(2 ** attempt)
                continue

            df = pd.DataFrame(rows, columns=columns)
            logger.info(
                "Received %d game log rows for player_id=%d", len(df), player_id
            )
            return df

        except Exception as exc:
            logger.warning(
                "API error player_id=%d attempt %d/%d: %s",
                player_id, attempt, max_retries, exc,
            )
            last_exc = exc
            time.sleep(2 ** attempt)

    raise RuntimeError(
        f"Failed to fetch game logs for player_id={player_id} after {max_retries} attempts"
    ) from last_exc


def search_player_id(player_name: str, season: str | None = None) -> int | None:  # noqa: ARG001
    """Return the NBA player_id for a player name using the local static list.

    Matching is case-insensitive. Partial names work (e.g. "Curry" finds
    "Stephen Curry"). Smart/curly quotes from macOS Terminal are stripped
    automatically.

    Raises ValueError if multiple players match the query.
    The ``season`` parameter is accepted for API compatibility but unused.
    """
    player_name = _strip_smart_quotes(player_name)
    name_query = player_name.lower()

    # Exact full-name match first — fastest, unambiguous
    exact = static_players.find_players_by_full_name(f"^{name_query}$")
    if len(exact) == 1:
        pid = int(exact[0]["id"])
        logger.info("Resolved '%s' -> player_id=%d", player_name, pid)
        return pid

    # Fallback: substring search across all historical players
    all_df = get_all_players_df()
    mask = all_df["full_name"].str.lower().str.contains(name_query, na=False, regex=False)
    matches = all_df[mask]

    if len(matches) == 0:
        logger.warning("No player found matching '%s'", player_name)
        return None
    if len(matches) > 1:
        names = matches["full_name"].tolist()
        raise ValueError(
            f"Multiple players matched '{player_name}': {names}. "
            "Please use a more specific name."
        )
    pid = int(matches.iloc[0]["id"])
    logger.info("Resolved '%s' -> player_id=%d", player_name, pid)
    return pid


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _parse_minutes(value: object) -> float:
    """Convert NBA API minutes string to float decimal minutes.

    The API returns either "38:22" (MM:SS) or a plain numeric string.
    """
    s = str(value).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            return float(parts[0]) + float(parts[1]) / 60
        except (ValueError, IndexError):
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _team_id_from_abbr(abbreviation: str) -> int | None:
    """Resolve a 3-letter team abbreviation to an NBA team_id using local static data."""
    from nba_api.stats.static import teams as static_teams
    all_teams = static_teams.get_teams()
    for t in all_teams:
        if t.get("abbreviation", "").upper() == abbreviation.upper():
            return int(t["id"])
    return None


def fetch_opponent_defense(
    opponent_abbr: str,
    season: str | None = None,
    max_retries: int = 3,
) -> dict[str, object]:
    """Return defensive stats for a team.

    Checks the local Basketball Reference reference file first (instant, no
    network call). Falls back to stats.nba.com if the reference file is missing
    or the team is not found in it.

    drtg_rank, team_name. Falls back to empty dict on failure.

    Note: stats.nba.com returns HTTP 500 when any filter param is absent,
    even optional ones. All known params must be supplied explicitly.
    We filter by TEAM_ID (integer, always present) rather than TEAM_ABBREVIATION
    which may be absent from the Defense measure-type response.
    """
    season = season or settings.default_season

    # Fast path: local Basketball Reference reference file (no network call)
    ref = get_team_defense_from_reference(opponent_abbr)
    if ref:
        logger.debug("Resolved defense for %s from reference file", opponent_abbr)
        # Reference file has drtg/ortg/nrtg/drtg_rank but not pts/reb/ast allowed.
        # Populate those from the live API as a best-effort supplement, but don't
        # block on failure — the drtg context is already sufficient for the prompt.
        ref.setdefault("pts_allowed", None)
        ref.setdefault("reb_allowed", None)
        ref.setdefault("ast_allowed", None)
        return ref

    logger.debug("Reference file miss for %s — falling back to stats.nba.com", opponent_abbr)
    team_id = _team_id_from_abbr(opponent_abbr)
    if team_id is None:
        logger.warning("Could not resolve team abbreviation '%s' to a team_id", opponent_abbr)
        return {}

    params = {
        "Season": season,
        "SeasonType": "Regular Season",
        "MeasureType": "Defense",
        "PerMode": "PerGame",
        "LeagueID": "00",
        "PaceAdjust": "N",
        "PlusMinus": "N",
        "Rank": "N",
        # Required empty-string / zero filters — omitting any causes HTTP 500
        "Conference": "",
        "DateFrom": "",
        "DateTo": "",
        "Division": "",
        "GameScope": "",
        "GameSegment": "",
        "LastNGames": 0,
        "Location": "",
        "Month": 0,
        "OpponentTeamID": 0,
        "Outcome": "",
        "PORound": 0,
        "Period": 0,
        "PlayerExperience": "",
        "PlayerPosition": "",
        "SeasonSegment": "",
        "StarterBench": "",
        "TwoWay": 0,
        "VsConference": "",
        "VsDivision": "",
    }
    session = _make_session()
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        _sleep()
        try:
            response = session.get(_NBA_TEAM_STATS_URL, params=params, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            # Find the result set that contains team rows (has TEAM_ID column)
            target_rs = None
            for rs in data.get("resultSets", []):
                if "TEAM_ID" in rs.get("headers", []) and rs.get("rowSet"):
                    target_rs = rs
                    break

            if target_rs is None:
                logger.warning(
                    "No result set with TEAM_ID found; available sets: %s",
                    [rs.get("name") for rs in data.get("resultSets", [])],
                )
                last_exc = ValueError("No TEAM_ID result set in response")
                time.sleep(2 ** attempt)
                continue

            columns = target_rs["headers"]
            rows = target_rs["rowSet"]
            df = pd.DataFrame(rows, columns=columns)

            row = df[df["TEAM_ID"] == team_id]
            if row.empty:
                logger.warning(
                    "team_id=%d (%s) not found in league stats; columns=%s",
                    team_id, opponent_abbr, columns[:8],
                )
                return {}

            r = row.iloc[0]

            # Rank by DEF_RATING ascending (lower = tougher defense = rank #1)
            if "DEF_RATING" in df.columns:
                df_sorted = df.sort_values("DEF_RATING", ascending=True).reset_index(drop=True)
                drtg_rank = int(df_sorted[df_sorted["TEAM_ID"] == team_id].index[0]) + 1
            elif "PTS" in df.columns:
                df_sorted = df.sort_values("PTS", ascending=True).reset_index(drop=True)
                drtg_rank = int(df_sorted[df_sorted["TEAM_ID"] == team_id].index[0]) + 1
            else:
                drtg_rank = None

            # Resolve team name — may or may not be in this result set
            team_name = str(r.get("TEAM_NAME", opponent_abbr)) if "TEAM_NAME" in columns else opponent_abbr

            # Fetch per-game opponent allowed stats (pts/reb/ast) from MeasureType=Opponent
            pts_allowed: float | None = None
            reb_allowed: float | None = None
            ast_allowed: float | None = None
            opp_params = {**params, "MeasureType": "Opponent"}
            try:
                opp_resp = session.get(_NBA_TEAM_STATS_URL, params=opp_params, timeout=_REQUEST_TIMEOUT)
                opp_resp.raise_for_status()
                opp_data = opp_resp.json()
                for rs in opp_data.get("resultSets", []):
                    if "TEAM_ID" in rs.get("headers", []) and rs.get("rowSet"):
                        opp_df = pd.DataFrame(rs["rowSet"], columns=rs["headers"])
                        opp_row = opp_df[opp_df["TEAM_ID"] == team_id]
                        if not opp_row.empty:
                            opp_r = opp_row.iloc[0]
                            pts_allowed = float(opp_r["PTS"]) if "PTS" in rs["headers"] else None
                            reb_allowed = float(opp_r["REB"]) if "REB" in rs["headers"] else None
                            ast_allowed = float(opp_r["AST"]) if "AST" in rs["headers"] else None
                        break
            except Exception as exc:
                logger.debug("Could not fetch Opponent measure stats for %s: %s", opponent_abbr, exc)

            return {
                "team_name": team_name,
                "pts_allowed": pts_allowed,
                "reb_allowed": reb_allowed,
                "ast_allowed": ast_allowed,
                "drtg": float(r["DEF_RATING"]) if "DEF_RATING" in columns else None,
                "drtg_rank": drtg_rank,
                "n_teams": len(df),
            }
        except Exception as exc:
            logger.warning("Team stats error attempt %d/%d: %s", attempt, max_retries, exc)
            last_exc = exc
            time.sleep(2 ** attempt)

    logger.error("Failed to fetch opponent defense for '%s': %s", opponent_abbr, last_exc)
    return {}


def fetch_player_context(
    player_id: int,
    player_name: str,
    season: str,
    opponent_abbr: str,
    last_n_games: int = 5,
) -> dict[str, object]:
    """Fetch all live context needed for a single prediction.

    Returns a structured dict with:
      - recent_games: list of last N game dicts
      - season_avgs: per-game averages for the full season so far
      - vs_opponent: per-game averages vs this opponent this season (or None)
      - opponent_defense: defensive stats for the opponent team
    """
    raw = fetch_player_game_logs(player_id, season)
    if raw.empty:
        return {}

    normalized = normalize_game_logs(raw, player_id, player_name, season)
    normalized = normalized.sort_values("game_date")

    # --- Season averages ---
    stat_cols = ["points", "rebounds", "assists", "threes_made", "minutes"]
    avail = [c for c in stat_cols if c in normalized.columns]
    season_avgs = {col: round(float(normalized[col].mean()), 1) for col in avail}
    season_avgs["games_played"] = len(normalized)

    # --- Last N games ---
    recent = normalized.tail(last_n_games)
    recent_games = []
    for _, row in recent.iterrows():
        game: dict[str, object] = {
            "date": str(row["game_date"]),
            "matchup": str(row.get("matchup", "")),
            "wl": str(row.get("wl", "")),
        }
        for col in avail:
            game[col] = round(float(row[col]), 1) if col in row else None
        recent_games.append(game)

    # --- vs. this opponent (current season) ---
    def _opp_from_matchup(matchup: str) -> str:
        if " vs. " in matchup:
            return matchup.split(" vs. ")[1].strip()
        if " @ " in matchup:
            return matchup.split(" @ ")[1].strip()
        parts = matchup.split()
        return parts[-1] if parts else "UNK"

    matchup_parsed = normalized["matchup"].apply(_opp_from_matchup)
    normalized["_opp"] = matchup_parsed
    vs_opp = normalized[normalized["_opp"] == opponent_abbr]
    vs_opponent: dict[str, object] | None = None
    if not vs_opp.empty:
        vs_opponent = {col: round(float(vs_opp[col].mean()), 1) for col in avail}
        vs_opponent["games_played"] = len(vs_opp)

    return {
        "recent_games": recent_games,
        "season_avgs": season_avgs,
        "vs_opponent": vs_opponent,
    }


_ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
_ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
_ESPN_SEARCH_URL = "https://site.api.espn.com/apis/common/v3/search"
_ESPN_GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}/gamelog"
_ESPN_TIMEOUT = 15  # ESPN is generally faster than stats.nba.com

# Maps our internal market names → ESPN label strings
_ESPN_MARKET_LABELS: dict[str, str] = {
    "points": "PTS",
    "rebounds": "REB",
    "assists": "AST",
    "threes_made": "3PT",
}


def _parse_espn_stat(value: str) -> float:
    """Parse an ESPN stat value — handles both plain numbers and 'made-attempted' format."""
    s = str(value).strip()
    if "-" in s:
        # e.g. "3-7" → 3.0 (made)
        try:
            return float(s.split("-")[0])
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def search_espn_athlete_id(player_name: str) -> str | None:
    """Resolve a player name to an ESPN athlete ID via the ESPN search API.

    Returns the first matching athlete ID string, or None if not found.
    No API key required.
    """
    session = requests.Session()
    try:
        resp = session.get(
            _ESPN_SEARCH_URL,
            params={"query": player_name, "limit": 5, "sport": "basketball", "league": "nba", "type": "player"},
            timeout=_ESPN_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if not items:
            logger.warning("ESPN search returned no results for '%s'", player_name)
            return None
        # Pick the best match: prefer an exact display name match, else take first
        query_lower = player_name.lower()
        for item in items:
            if item.get("displayName", "").lower() == query_lower:
                return str(item["id"])
        return str(items[0]["id"])
    except Exception as exc:
        logger.warning("ESPN athlete ID search failed for '%s': %s", player_name, exc)
        return None


def fetch_player_game_logs_espn(
    player_name: str,
    market: str,
    limit: int = 5,
    before_date: str | None = None,
) -> list[dict[str, object]]:
    """Fetch recent game logs for a player from ESPN (no API key, no headers needed).

    Returns a list of dicts with keys: game_date (YYYY-MM-DD), matchup (str), value (float).
    List is in chronological order (oldest → newest), limited to *limit* entries.

    Falls back to an empty list on any failure — caller should handle this gracefully.
    """
    from datetime import date as _date, datetime as _datetime, timezone as _timezone

    athlete_id = search_espn_athlete_id(player_name)
    if athlete_id is None:
        logger.warning("Could not resolve ESPN athlete ID for '%s'", player_name)
        return []

    label = _ESPN_MARKET_LABELS.get(market)
    if label is None:
        logger.warning("Unknown market '%s' for ESPN fetch", market)
        return []

    session = requests.Session()
    try:
        resp = session.get(
            _ESPN_GAMELOG_URL.format(athlete_id=athlete_id),
            timeout=_ESPN_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("ESPN gamelog fetch failed for athlete_id=%s: %s", athlete_id, exc)
        return []

    labels: list[str] = data.get("labels", [])
    if label not in labels:
        logger.warning("Label '%s' not found in ESPN gamelog labels: %s", label, labels)
        return []
    stat_idx = labels.index(label)

    events_meta: dict[str, dict] = data.get("events", {})
    cutoff: _date | None = _date.fromisoformat(before_date) if before_date else None

    # Collect game entries across all season types (regular + playoffs)
    entries: list[tuple[str, str, float]] = []  # (game_date, matchup, value)
    for season_type in data.get("seasonTypes", []):
        for category in season_type.get("categories", []):
            for ev in category.get("events", []):
                event_id = str(ev.get("eventId", ""))
                stats: list = ev.get("stats", [])
                if stat_idx >= len(stats):
                    continue

                meta = events_meta.get(event_id, {})
                raw_date = str(meta.get("gameDate", ""))
                if not raw_date:
                    continue

                # Parse ISO date → YYYY-MM-DD (strip time component)
                try:
                    game_dt = _datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    game_date_str = game_dt.astimezone(_timezone.utc).strftime("%Y-%m-%d")
                    game_date = _date.fromisoformat(game_date_str)
                except ValueError:
                    game_date_str = raw_date[:10]
                    game_date = _date.fromisoformat(game_date_str)

                if cutoff and game_date >= cutoff:
                    continue

                at_vs = str(meta.get("atVs", "vs"))
                opp_abbr = str(meta.get("opponent", {}).get("abbreviation", "?"))
                matchup = f"{at_vs} {opp_abbr}"

                value = _parse_espn_stat(str(stats[stat_idx]))
                entries.append((game_date_str, matchup, value))

    # De-duplicate (same game can appear in multiple categories)
    seen: set[str] = set()
    unique: list[tuple[str, str, float]] = []
    for entry in entries:
        if entry[0] not in seen:
            seen.add(entry[0])
            unique.append(entry)

    # Sort descending by date, take limit, then reverse for chronological order
    unique.sort(key=lambda x: x[0], reverse=True)
    recent = unique[:limit]
    recent.reverse()

    return [{"game_date": g, "matchup": m, "value": v} for g, m, v in recent]


def fetch_injury_report(
    team_abbreviations: list[str],
    max_retries: int = 3,
) -> dict[str, dict[str, str]]:
    """Fetch current NBA injuries from the ESPN public endpoint (no API key needed).

    Returns a dict keyed by player display name::

        {
            "Joel Embiid": {"status": "Out", "reason": "knee", "team": "PHI"},
            "Tyrese Maxey": {"status": "Questionable", "reason": "hamstring", "team": "PHI"},
        }

    If *team_abbreviations* is non-empty, only players from those teams are included.
    On any failure or empty response, returns ``{}``.
    """
    abbrs_upper = {a.upper() for a in team_abbreviations}
    session = requests.Session()
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(_ESPN_INJURIES_URL, timeout=_ESPN_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            result: dict[str, dict[str, str]] = {}
            for team_entry in data.get("injuries", []):
                for injury in team_entry.get("injuries", []):
                    athlete = injury.get("athlete", {})

                    # Team abbreviation lives inside the athlete object
                    team_abbr = str(
                        athlete.get("team", {}).get("abbreviation", "")
                    ).upper()

                    if abbrs_upper and team_abbr not in abbrs_upper:
                        continue

                    player_name = str(athlete.get("displayName", "")).strip()
                    if not player_name:
                        continue

                    # Status: prefer type.description ("out", "questionable", …)
                    status = str(
                        injury.get("type", {}).get("description", "")
                        or injury.get("status", "Unknown")
                    ).strip().title()

                    # Reason: prefer details.type (body part), fall back to shortComment
                    details = injury.get("details", {})
                    reason = (
                        str(details.get("type", ""))
                        or str(injury.get("shortComment", ""))
                    ).strip()

                    result[player_name] = {
                        "status": status,
                        "reason": reason.lower() if reason else "unknown",
                        "team": team_abbr,
                    }

            logger.info(
                "Fetched %d injured player(s) for teams %s",
                len(result),
                team_abbreviations or "all",
            )
            return result

        except Exception as exc:
            logger.warning(
                "ESPN injury fetch attempt %d/%d failed: %s", attempt, max_retries, exc
            )
            last_exc = exc
            time.sleep(2 ** attempt)

    logger.error("Failed to fetch injury report after %d attempts: %s", max_retries, last_exc)
    return {}


def fetch_todays_slate(game_date: str | None = None) -> list[dict[str, str]]:
    """Fetch NBA slate from ESPN scoreboard.

    Returns only scheduled games in a flat shape:
      [{"game_id", "game_date", "home_team", "away_team", "status"}, ...]

    If game_date is provided (YYYY-MM-DD), ESPN is queried for that date.
    On any failure, returns an empty list and logs a warning.
    """
    session = requests.Session()
    try:
        params: dict[str, str] = {}
        if game_date:
            params["dates"] = game_date.replace("-", "")
        response = session.get(_ESPN_SCOREBOARD_URL, params=params, timeout=_ESPN_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("Failed to fetch ESPN scoreboard slate: %s", exc)
        return []

    games: list[dict[str, str]] = []
    for event in data.get("events", []):
        try:
            competitions = event.get("competitions", [])
            if not competitions:
                continue
            competition = competitions[0]
            status_type = competition.get("status", {}).get("type", {})
            status_state = str(status_type.get("state", "")).lower()
            status_name = str(status_type.get("name", "")).upper()
            is_completed = bool(status_type.get("completed", False))
            is_scheduled = (
                status_state == "pre"
                or status_name in {"STATUS_SCHEDULED", "STATUS_PRE_GAME"}
                or (not is_completed and status_state not in {"in", "post"})
            )
            if not is_scheduled:
                continue

            home_team = ""
            away_team = ""
            for competitor in competition.get("competitors", []):
                team_abbr = str(competitor.get("team", {}).get("abbreviation", "")).upper()
                if competitor.get("homeAway") == "home":
                    home_team = team_abbr
                elif competitor.get("homeAway") == "away":
                    away_team = team_abbr

            date_raw = str(event.get("date", "")).strip()
            parsed_game_date = date_raw[:10] if len(date_raw) >= 10 else ""
            if not home_team or not away_team:
                continue

            games.append(
                {
                    "game_id": str(event.get("id", "")),
                    "game_date": game_date if game_date else parsed_game_date,
                    "home_team": home_team,
                    "away_team": away_team,
                    "status": "scheduled",
                }
            )
        except Exception:
            continue

    return games


def get_team_roster(team_abbreviation: str) -> list[str]:
    """Return active player full names for an NBA team abbreviation."""
    team_abbr_upper = team_abbreviation.upper()
    team_id: int | None = None
    for team in static_teams.get_teams():
        if str(team.get("abbreviation", "")).upper() == team_abbr_upper:
            team_id = int(team["id"])
            break
    if team_id is None:
        logger.warning("Could not resolve team abbreviation '%s'", team_abbreviation)
        return []

    try:
        _sleep()
        endpoint = CommonTeamRoster(team_id=team_id, season=settings.default_season)
        df = endpoint.get_data_frames()[0]
    except Exception as exc:
        logger.warning("Failed to fetch team roster for %s: %s", team_abbreviation, exc)
        return []

    if df.empty or "PLAYER" not in df.columns:
        return []
    roster = [str(name).strip() for name in df["PLAYER"].tolist() if str(name).strip()]
    return roster


def normalize_game_logs(
    raw_df: pd.DataFrame,
    player_id: int,
    player_name: str,
    season: str,
) -> pd.DataFrame:
    """Map raw NBA API columns to our internal snake_case schema."""
    col_map = {
        "GAME_ID": "game_id",
        "GAME_DATE": "game_date",
        "MATCHUP": "matchup",
        "WL": "wl",
        "MIN": "minutes",
        "PTS": "points",
        "REB": "rebounds",
        "AST": "assists",
        "FG3M": "threes_made",
        "FG3A": "threes_attempted",
        "FGM": "fg_made",
        "FGA": "fg_attempted",
        "FTM": "ft_made",
        "FTA": "ft_attempted",
        "PLUS_MINUS": "plus_minus",
    }
    df = raw_df.copy()
    df.columns = [c.upper() for c in df.columns]

    available = {k: v for k, v in col_map.items() if k in df.columns}
    missing = set(col_map.keys()) - set(available.keys())
    if missing:
        logger.warning("Columns missing from API response: %s", missing)

    df = df.rename(columns=available)[list(available.values())].copy()
    df["player_id"] = player_id
    df["player_name"] = player_name
    df["season"] = season
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date

    if "minutes" in df.columns:
        df["minutes"] = df["minutes"].apply(_parse_minutes)

    for col in ["points", "rebounds", "assists", "threes_made", "threes_attempted",
                "fg_made", "fg_attempted", "ft_made", "ft_attempted", "plus_minus"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df
