import sqlite3

import pytest

from scouting_reports.db.connection import SCHEMA_PATH
from scouting_reports.stats.percentiles import percentile, position_group


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_PATH.read_text())
    connection.execute(
        "INSERT INTO competition (competition_id, country, tier, display_name) VALUES ('ENG1', 'England', 1, 'Premier League')"
    )
    connection.execute("INSERT INTO season (season_id, start_year, end_year) VALUES ('2024-2025', 2024, 2025)")
    yield connection
    connection.close()


def _add_player(conn, name, position, xg, minutes=2000):
    cur = conn.execute("INSERT INTO player (canonical_name, primary_position) VALUES (?, ?)", (name, position))
    player_id = cur.lastrowid
    conn.execute(
        """INSERT INTO player_season_stat_flat (player_id, season_id, competition_id, minutes, xg)
           VALUES (?, '2024-2025', 'ENG1', ?, ?)""",
        (player_id, minutes, xg),
    )
    conn.commit()
    return player_id


def test_position_group_maps_known_codes():
    assert position_group("FW") == "Forward"
    assert position_group("GK") == "Goalkeeper"
    assert position_group(None) == "Unknown"
    assert position_group("XX") == "Unknown"


def test_percentile_boundaries_min_median_max(conn):
    # 5 forwards with xg 1,2,3,4,5 -- exact median/min/max are unambiguous to check.
    ids = [_add_player(conn, f"Player {i}", "FW", float(i)) for i in range(1, 6)]

    assert percentile(conn, ids[0], "2024-2025", "ENG1", "xg") == 1 / 5  # lowest
    assert percentile(conn, ids[-1], "2024-2025", "ENG1", "xg") == 5 / 5  # highest, top of cohort
    assert percentile(conn, ids[2], "2024-2025", "ENG1", "xg") == 3 / 5  # median


def test_percentile_none_when_stat_missing(conn):
    pid = _add_player(conn, "No Data Player", "FW", xg=None)
    assert percentile(conn, pid, "2024-2025", "ENG1", "xg") is None


def test_percentile_none_when_cohort_too_small(conn):
    # Only 2 players in this position group -- below the 5-player minimum cohort size.
    ids = [_add_player(conn, f"GK {i}", "GK", float(i)) for i in range(1, 3)]
    assert percentile(conn, ids[0], "2024-2025", "ENG1", "xg") is None


def test_tier3_player_without_xg_excluded_from_tier1_cohort(conn):
    # 5 forwards form a valid cohort; a 6th player with no xg (as tier-3-only players would
    # have) must never be silently counted into that cohort's percentile computation.
    ids = [_add_player(conn, f"Player {i}", "FW", float(i)) for i in range(1, 6)]
    no_xg_id = _add_player(conn, "Tier3 Only Player", "FW", xg=None)

    assert percentile(conn, no_xg_id, "2024-2025", "ENG1", "xg") is None
    # the existing cohort's percentiles are unaffected by the no-xg player's presence
    assert percentile(conn, ids[-1], "2024-2025", "ENG1", "xg") == 5 / 5


def test_invalid_stat_column_rejected(conn):
    pid = _add_player(conn, "Player", "FW", xg=1.0)
    with pytest.raises(ValueError):
        percentile(conn, pid, "2024-2025", "ENG1", "'; DROP TABLE player; --")
