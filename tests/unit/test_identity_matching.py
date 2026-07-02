import sqlite3

import pytest

from scouting_reports.db.connection import SCHEMA_PATH
from scouting_reports.identity.match import resolve_player_id


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_PATH.read_text())
    yield connection
    connection.close()


def test_exact_dob_and_name_auto_accepts(conn):
    pid1 = resolve_player_id(conn, "fbref", "f1", "Ben White", date_of_birth="1997-10-08", team_hint="Arsenal")
    pid2 = resolve_player_id(conn, "understat", "u1", "Ben White", date_of_birth="1997-10-08", team_hint="Arsenal")
    assert pid1 == pid2
    ref = conn.execute("SELECT match_method FROM player_source_ref WHERE source='understat'").fetchone()
    assert ref["match_method"] == "exact_dob_name"


def test_fuzzy_name_and_team_auto_accepts_accent_variant(conn):
    # Same name, differing only in accents/diacritics (unidecode normalizes these to identical
    # strings) plus a team-name-verbosity difference across sources -- should clear auto-accept.
    pid1 = resolve_player_id(conn, "fbref", "f1", "Raul Jimenez", team_hint="Fulham")
    pid2 = resolve_player_id(conn, "transfermarkt", "t1", "Raúl Jiménez", team_hint="Fulham Football Club")
    assert pid1 == pid2
    ref = conn.execute("SELECT match_method FROM player_source_ref WHERE source='transfermarkt'").fetchone()
    assert ref["match_method"] == "fuzzy_name_team"


def test_nickname_with_team_match_reaches_review_not_auto_accept(conn):
    # A looser nickname/full-name variant (as opposed to a pure accent difference) should not
    # cross the auto-accept bar even with a team match -- this mirrors real Premier League data
    # (Matty Cash / Matthew Cash) where auto-accepting would risk false-positive merges.
    resolve_player_id(conn, "fbref", "f1", "Matty Cash", team_hint="Aston Villa")
    result = resolve_player_id(conn, "transfermarkt", "t1", "Matthew Cash", team_hint="Aston Villa Football Club")
    assert result is None
    row = conn.execute("SELECT status FROM player_match_review_queue WHERE source='transfermarkt'").fetchone()
    assert row["status"] == "pending"


def test_ambiguous_match_goes_to_review_queue(conn):
    pid1 = resolve_player_id(conn, "fbref", "f1", "Joseph Gomez", team_hint="Liverpool")
    pid2 = resolve_player_id(conn, "understat", "u1", "Joe Gomez", team_hint="Liverpool")
    # name similarity alone (no exact DOB) lands in the review band, not auto-accept
    assert pid2 is None
    row = conn.execute("SELECT status FROM player_match_review_queue WHERE source='understat'").fetchone()
    assert row["status"] == "pending"


def test_same_name_different_team_still_reaches_review_not_silently_new(conn):
    resolve_player_id(conn, "fbref", "f1", "Axel Disasi", team_hint="Chelsea")
    result = resolve_player_id(conn, "transfermarkt", "t1", "Axel Disasi", team_hint="Aston Villa Football Club")
    assert result is None
    row = conn.execute("SELECT status, candidate_score FROM player_match_review_queue WHERE source='transfermarkt'").fetchone()
    assert row["status"] == "pending"
    assert row["candidate_score"] >= 0.75


def test_clearly_different_players_both_become_new(conn):
    pid1 = resolve_player_id(conn, "fbref", "f1", "Erling Haaland", team_hint="Manchester City")
    pid2 = resolve_player_id(conn, "fbref", "f2", "Mohamed Salah", team_hint="Liverpool")
    assert pid1 != pid2


def test_manual_override_forces_mapping(conn):
    pid1 = resolve_player_id(conn, "fbref", "f1", "Kevin De Bruyne", team_hint="Manchester City")
    conn.execute(
        "INSERT INTO player_alias_override (source, source_player_id, player_id, reason) VALUES (?, ?, ?, ?)",
        ("transfermarkt", "t99", pid1, "test override"),
    )
    result = resolve_player_id(conn, "transfermarkt", "t99", "Someone Else Entirely", team_hint="Chelsea")
    assert result == pid1


def test_manual_block_override_always_routes_to_review(conn):
    conn.execute(
        "INSERT INTO player_alias_override (source, source_player_id, player_id, reason) VALUES (?, ?, ?, ?)",
        ("transfermarkt", "t42", None, "known false positive, never auto-match"),
    )
    result = resolve_player_id(conn, "transfermarkt", "t42", "Some Player", team_hint="Some Team")
    assert result is None
    row = conn.execute("SELECT status FROM player_match_review_queue WHERE source_player_id='t42'").fetchone()
    assert row["status"] == "pending"


def test_repeat_calls_for_same_source_record_return_same_player(conn):
    pid1 = resolve_player_id(conn, "fbref", "f1", "Declan Rice", team_hint="Arsenal")
    pid2 = resolve_player_id(conn, "fbref", "f1", "Declan Rice", team_hint="Arsenal")
    assert pid1 == pid2
    count = conn.execute("SELECT COUNT(*) c FROM player_source_ref WHERE source='fbref' AND source_player_id='f1'").fetchone()["c"]
    assert count == 1
