"""Tests for fetch_injury_report — ESPN public injuries endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from court_edge_agent.data.nba_client import fetch_injury_report

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_injury(display_name: str, team_abbr: str, status: str, reason: str) -> dict:
    """Build a single injury entry matching the real ESPN response shape."""
    return {
        "athlete": {
            "displayName": display_name,
            "team": {"abbreviation": team_abbr, "displayName": team_abbr},
        },
        "status": status,
        "type": {"description": status.lower()},
        "details": {"type": reason},
        "shortComment": "",
        "longComment": "",
    }


_ESPN_SAMPLE = {
    "injuries": [
        {
            "displayName": "Philadelphia 76ers",
            "injuries": [
                _make_injury("Joel Embiid", "PHI", "Out", "knee"),
                _make_injury("Tyrese Maxey", "PHI", "Questionable", "hamstring"),
            ],
        },
        {
            "displayName": "Boston Celtics",
            "injuries": [
                _make_injury("Jaylen Brown", "BOS", "Probable", "ankle"),
            ],
        },
    ]
}


def _mock_espn_response(json_data: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFetchInjuryReport:
    @patch("court_edge_agent.data.nba_client.requests.Session")
    def test_returns_dict_keyed_by_player_name(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _mock_espn_response(_ESPN_SAMPLE)

        result = fetch_injury_report([])

        assert isinstance(result, dict)
        assert "Joel Embiid" in result
        assert "Tyrese Maxey" in result
        assert "Jaylen Brown" in result

    @patch("court_edge_agent.data.nba_client.requests.Session")
    def test_parsed_shape_matches_expected(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _mock_espn_response(_ESPN_SAMPLE)

        result = fetch_injury_report(["PHI"])

        embiid = result["Joel Embiid"]
        assert embiid["status"] == "Out"
        assert "knee" in embiid["reason"]
        assert embiid["team"] == "PHI"

        maxey = result["Tyrese Maxey"]
        assert maxey["status"] == "Questionable"
        assert "hamstring" in maxey["reason"]
        assert maxey["team"] == "PHI"

    @patch("court_edge_agent.data.nba_client.requests.Session")
    def test_team_filter_excludes_other_teams(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _mock_espn_response(_ESPN_SAMPLE)

        result = fetch_injury_report(["PHI"])

        assert "Joel Embiid" in result
        assert "Tyrese Maxey" in result
        assert "Jaylen Brown" not in result

    @patch("court_edge_agent.data.nba_client.requests.Session")
    def test_empty_team_list_returns_all_players(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _mock_espn_response(_ESPN_SAMPLE)

        result = fetch_injury_report([])

        assert len(result) == 3

    @patch("court_edge_agent.data.nba_client.requests.Session")
    def test_network_error_returns_empty_dict(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = ConnectionError("ESPN down")

        result = fetch_injury_report(["PHI"])

        assert result == {}

    @patch("court_edge_agent.data.nba_client.requests.Session")
    def test_empty_injuries_list_returns_empty_dict(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _mock_espn_response({"injuries": []})

        result = fetch_injury_report(["PHI"])

        assert result == {}

    @patch("court_edge_agent.data.nba_client.requests.Session")
    def test_case_insensitive_team_filter(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _mock_espn_response(_ESPN_SAMPLE)

        result_lower = fetch_injury_report(["phi"])
        result_upper = fetch_injury_report(["PHI"])

        assert set(result_lower.keys()) == set(result_upper.keys())

    @patch("court_edge_agent.data.nba_client.requests.Session")
    def test_multiple_teams_filter(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = _mock_espn_response(_ESPN_SAMPLE)

        result = fetch_injury_report(["PHI", "BOS"])

        assert "Joel Embiid" in result
        assert "Jaylen Brown" in result

    @patch("court_edge_agent.data.nba_client.requests.Session")
    def test_retries_on_failure_then_succeeds(self, mock_session_cls: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = [
            ConnectionError("timeout"),
            _mock_espn_response(_ESPN_SAMPLE),
        ]

        with patch("time.sleep"):
            result = fetch_injury_report(["PHI"])

        assert "Joel Embiid" in result
