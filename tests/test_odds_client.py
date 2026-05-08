"""Tests for odds_client and prop_lines storage."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from court_edge_agent.data.odds_client import fetch_nba_player_props
from court_edge_agent.data.storage import init_db, load_prop_lines, upsert_prop_lines

# ---------------------------------------------------------------------------
# Sample Odds API response fixtures
# ---------------------------------------------------------------------------

_EVENTS_SAMPLE = [
    {"id": "event-001", "home_team": "Philadelphia 76ers", "away_team": "Boston Celtics"},
]

_ODDS_SAMPLE = {
    "id": "event-001",
    "bookmakers": [
        {
            "key": "draftkings",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {
                            "description": "Jalen Brunson",
                            "name": "Over",
                            "point": 26.5,
                            "price": -115,
                        },
                        {
                            "description": "Jalen Brunson",
                            "name": "Under",
                            "point": 26.5,
                            "price": -105,
                        },
                        {
                            "description": "Joel Embiid",
                            "name": "Over",
                            "point": 27.5,
                            "price": -110,
                        },
                        {
                            "description": "Joel Embiid",
                            "name": "Under",
                            "point": 27.5,
                            "price": -110,
                        },
                    ],
                }
            ],
        }
    ],
}


def _make_get_side_effect(events: list, odds: dict):
    """Return a side_effect function that routes GET calls to fixtures."""
    def _side_effect(url: str, **kwargs):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        if "/events" in url and "/odds" not in url:
            mock_resp.json.return_value = events
        else:
            mock_resp.json.return_value = odds
        return mock_resp
    return _side_effect


# ---------------------------------------------------------------------------
# fetch_nba_player_props tests
# ---------------------------------------------------------------------------

class TestFetchNbaPlayerProps:
    @patch("court_edge_agent.data.odds_client.settings")
    @patch("court_edge_agent.data.odds_client.requests.get")
    def test_returns_flat_list(self, mock_get: MagicMock, mock_settings: MagicMock) -> None:
        mock_settings.odds_api_key = "test-key"
        mock_get.side_effect = _make_get_side_effect(_EVENTS_SAMPLE, _ODDS_SAMPLE)

        result = fetch_nba_player_props("points")

        assert isinstance(result, list)
        assert len(result) > 0

    @patch("court_edge_agent.data.odds_client.settings")
    @patch("court_edge_agent.data.odds_client.requests.get")
    def test_output_shape(self, mock_get: MagicMock, mock_settings: MagicMock) -> None:
        mock_settings.odds_api_key = "test-key"
        mock_get.side_effect = _make_get_side_effect(_EVENTS_SAMPLE, _ODDS_SAMPLE)

        result = fetch_nba_player_props("points")

        required_keys = {"player_name", "market", "line", "over_odds", "under_odds",
                         "bookmaker", "timestamp"}
        for row in result:
            assert required_keys.issubset(row.keys()), f"Missing keys in row: {row}"

    @patch("court_edge_agent.data.odds_client.settings")
    @patch("court_edge_agent.data.odds_client.requests.get")
    def test_market_mapped_to_internal_name(self, mock_get: MagicMock, mock_settings: MagicMock) -> None:
        mock_settings.odds_api_key = "test-key"
        mock_get.side_effect = _make_get_side_effect(_EVENTS_SAMPLE, _ODDS_SAMPLE)

        result = fetch_nba_player_props("points")

        for row in result:
            assert row["market"] == "points", f"Expected 'points', got '{row['market']}'"

    @patch("court_edge_agent.data.odds_client.settings")
    @patch("court_edge_agent.data.odds_client.requests.get")
    def test_correct_player_names_and_lines(self, mock_get: MagicMock, mock_settings: MagicMock) -> None:
        mock_settings.odds_api_key = "test-key"
        mock_get.side_effect = _make_get_side_effect(_EVENTS_SAMPLE, _ODDS_SAMPLE)

        result = fetch_nba_player_props("points")

        names = {r["player_name"] for r in result}
        assert "Jalen Brunson" in names
        assert "Joel Embiid" in names

        brunson = next(r for r in result if r["player_name"] == "Jalen Brunson")
        assert brunson["line"] == 26.5
        assert brunson["over_odds"] == -115
        assert brunson["under_odds"] == -105
        assert brunson["bookmaker"] == "draftkings"

    @patch("court_edge_agent.data.odds_client.settings")
    def test_returns_empty_list_when_key_not_set(self, mock_settings: MagicMock) -> None:
        mock_settings.odds_api_key = ""

        result = fetch_nba_player_props("points")

        assert result == []

    @patch("court_edge_agent.data.odds_client.settings")
    def test_returns_empty_list_for_unknown_market(self, mock_settings: MagicMock) -> None:
        mock_settings.odds_api_key = "test-key"

        result = fetch_nba_player_props("turnovers")

        assert result == []

    @patch("court_edge_agent.data.odds_client.settings")
    @patch("court_edge_agent.data.odds_client.requests.get")
    def test_network_error_returns_empty_list(self, mock_get: MagicMock, mock_settings: MagicMock) -> None:
        mock_settings.odds_api_key = "test-key"
        mock_get.side_effect = ConnectionError("Odds API unreachable")

        with patch("time.sleep"):
            result = fetch_nba_player_props("points")

        assert result == []


# ---------------------------------------------------------------------------
# Storage: upsert_prop_lines / load_prop_lines tests
# ---------------------------------------------------------------------------

class TestPropLinesStorage:
    def _tmp_db(self) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            path = Path(tmp.name)
        init_db(db_path=path)
        return path

    def test_upsert_and_load_roundtrip(self) -> None:
        db = self._tmp_db()

        df = pd.DataFrame([
            {
                "player_name": "Jalen Brunson",
                "game_date": "2025-04-01",
                "market": "points",
                "line": 26.5,
                "over_odds": -115,
                "under_odds": -105,
                "bookmaker": "draftkings",
                "fetched_at": "2025-04-01T10:00:00+00:00",
            }
        ])

        written = upsert_prop_lines(df, db_path=db)
        assert written == 1

        loaded = load_prop_lines("Jalen Brunson", "2025-04-01", "points", db_path=db)
        assert len(loaded) == 1
        assert loaded.iloc[0]["line"] == 26.5
        assert loaded.iloc[0]["bookmaker"] == "draftkings"

    def test_upsert_replaces_on_conflict(self) -> None:
        db = self._tmp_db()

        row = {
            "player_name": "Joel Embiid",
            "game_date": "2025-04-01",
            "market": "points",
            "line": 27.5,
            "over_odds": -110,
            "under_odds": -110,
            "bookmaker": "fanduel",
            "fetched_at": "2025-04-01T09:00:00+00:00",
        }
        upsert_prop_lines(pd.DataFrame([row]), db_path=db)

        # Update with a new line
        row["line"] = 28.5
        row["fetched_at"] = "2025-04-01T11:00:00+00:00"
        upsert_prop_lines(pd.DataFrame([row]), db_path=db)

        loaded = load_prop_lines("Joel Embiid", "2025-04-01", "points", db_path=db)
        assert len(loaded) == 1
        assert loaded.iloc[0]["line"] == 28.5

    def test_load_returns_empty_when_no_match(self) -> None:
        db = self._tmp_db()
        loaded = load_prop_lines("Unknown Player", "2025-04-01", "points", db_path=db)
        assert loaded.empty

    def test_upsert_empty_df_returns_zero(self) -> None:
        db = self._tmp_db()
        written = upsert_prop_lines(pd.DataFrame(), db_path=db)
        assert written == 0

    def test_multiple_bookmakers_stored_separately(self) -> None:
        db = self._tmp_db()

        rows = [
            {
                "player_name": "Jalen Brunson",
                "game_date": "2025-04-01",
                "market": "points",
                "line": 26.5,
                "over_odds": -115,
                "under_odds": -105,
                "bookmaker": "draftkings",
                "fetched_at": "2025-04-01T10:00:00+00:00",
            },
            {
                "player_name": "Jalen Brunson",
                "game_date": "2025-04-01",
                "market": "points",
                "line": 26.5,
                "over_odds": -120,
                "under_odds": -100,
                "bookmaker": "fanduel",
                "fetched_at": "2025-04-01T10:00:00+00:00",
            },
        ]
        upsert_prop_lines(pd.DataFrame(rows), db_path=db)

        loaded = load_prop_lines("Jalen Brunson", "2025-04-01", "points", db_path=db)
        assert len(loaded) == 2
        bookmakers = set(loaded["bookmaker"].tolist())
        assert bookmakers == {"draftkings", "fanduel"}
