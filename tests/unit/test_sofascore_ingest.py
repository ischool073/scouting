from unittest.mock import patch

from scouting_reports.ingest.sofascore_ingest import SofascoreIngestor, _to_sofascore_year


def test_to_sofascore_year_format():
    assert _to_sofascore_year("2025-2026") == "25/26"
    assert _to_sofascore_year("2024-2025") == "24/25"


def test_find_player_disambiguates_by_team_when_multiple_name_matches():
    ingestor = SofascoreIngestor(tournament_id=17, players=[])
    search_results = {
        "results": [
            {"type": "player", "entity": {"id": 1, "name": "Erling Haaland", "team": {"name": "Manchester City"}}},
            {"type": "player", "entity": {"id": 2, "name": "Erling Haaland", "team": {"name": "Ukumari"}}},
        ]
    }
    with patch.object(ingestor, "_get", return_value=search_results):
        hit = ingestor._find_player("Erling Haaland", "Manchester City")
    assert hit["id"] == 1


def test_find_player_returns_none_below_confidence_threshold():
    ingestor = SofascoreIngestor(tournament_id=17, players=[])
    search_results = {
        "results": [
            {"type": "player", "entity": {"id": 99, "name": "Djordje Petrovic", "team": {"name": "RK Kikinda Grindex"}}},
        ]
    }
    with patch.object(ingestor, "_get", return_value=search_results):
        hit = ingestor._find_player("Djordje Petrovic", "Association Football Club Bournemouth")
    assert hit is None


def test_find_player_returns_none_when_search_has_no_player_results():
    ingestor = SofascoreIngestor(tournament_id=17, players=[])
    with patch.object(ingestor, "_get", return_value={"results": []}):
        hit = ingestor._find_player("Nobody Real", "Some FC")
    assert hit is None


def test_find_player_handles_search_request_failure_gracefully():
    ingestor = SofascoreIngestor(tournament_id=17, players=[])
    with patch.object(ingestor, "_get", side_effect=Exception("network error")):
        hit = ingestor._find_player("Mohamed Salah", "Liverpool")
    assert hit is None
