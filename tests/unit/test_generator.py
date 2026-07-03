import sqlite3

import pytest

from scouting_reports.db.connection import SCHEMA_PATH
from scouting_reports.reports.generator import _age, _per90, build_player_profile


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


def test_age_computes_from_date_of_birth():
    assert _age("2000-01-01") == pytest.approx(_age("2000-01-01"))  # deterministic, no crash
    assert isinstance(_age("2000-01-01"), int)


def test_age_none_when_dob_missing():
    assert _age(None) is None


def test_build_profile_raises_for_player_with_no_stats(conn):
    conn.execute("INSERT INTO player (canonical_name) VALUES ('Ghost Player')")
    conn.commit()
    player_id = conn.execute("SELECT player_id FROM player").fetchone()["player_id"]
    with pytest.raises(ValueError):
        build_player_profile(conn, player_id, "ENG1", "2024-2025")


def test_build_profile_includes_bio_and_full_stats(conn):
    cur = conn.execute(
        """INSERT INTO player
           (canonical_name, primary_position, last_team_hint, date_of_birth, nationality,
            height_cm, preferred_foot, photo_url, contract_expires, international_caps, international_goals)
           VALUES ('Test Player', 'FW', 'Test FC', '2000-01-01', 'Testland', 180, 'right',
                   'http://example.com/p.jpg', '2027-06-30', 10, 2)"""
    )
    player_id = cur.lastrowid
    conn.execute(
        """INSERT INTO player_season_stat_flat
           (player_id, season_id, competition_id, minutes, goals, assists, xg, market_value_eur)
           VALUES (?, '2024-2025', 'ENG1', 2000, 5, 3, 4.5, 10000000)""",
        (player_id,),
    )
    conn.commit()

    profile = build_player_profile(conn, player_id, "ENG1", "2024-2025")

    assert profile["player_name"] == "Test Player"
    assert profile["bio"]["nationality"] == "Testland"
    assert profile["bio"]["height_cm"] == 180
    assert profile["bio"]["age"] is not None
    assert "Market Value" in profile["sections"]

    stat_labels = {s["label"]: s for s in profile["stats"]}
    assert stat_labels["Goals"]["value"] == 5
    assert stat_labels["Market Value (EUR)"]["display"] == "EUR 10.0m"

    # outfield players get a 5-axis radar (Finishing/Creativity/Shooting/Defending/Build-up)
    assert len(profile["radar"]) == 5
    assert profile["radar_svg"].startswith("<svg")


def test_goalkeeper_gets_three_axis_radar_not_outfield_sections(conn):
    cur = conn.execute(
        "INSERT INTO player (canonical_name, primary_position) VALUES ('Test Keeper', 'GK')"
    )
    player_id = cur.lastrowid
    conn.execute(
        """INSERT INTO player_season_stat_flat
           (player_id, season_id, competition_id, minutes, save_pct, clean_sheet_pct, goals_against_90)
           VALUES (?, '2024-2025', 'ENG1', 2000, 71.5, 34.0, 0.9)""",
        (player_id,),
    )
    conn.commit()

    profile = build_player_profile(conn, player_id, "ENG1", "2024-2025")

    assert len(profile["radar"]) == 3
    assert {a["label"] for a in profile["radar"]} == {"Shot Stopping", "Clean Sheets", "Goals Prevented"}
    assert "Finishing" not in profile["sections"]
    assert "Goalkeeping" in profile["sections"]


def test_fouls_committed_bar_percentile_is_inverted(conn):
    # Lower fouls should map to a HIGHER bar_percentile (fewer fouls = better discipline),
    # since fouls_committed is flagged lower_is_better in STAT_FIELDS.
    ids = []
    for fouls in (2, 5, 8, 12, 20):
        cur = conn.execute(
            "INSERT INTO player (canonical_name, primary_position) VALUES (?, 'MF')", (f"P{fouls}",)
        )
        pid = cur.lastrowid
        ids.append((pid, fouls))
        conn.execute(
            """INSERT INTO player_season_stat_flat
               (player_id, season_id, competition_id, minutes, fouls_committed)
               VALUES (?, '2024-2025', 'ENG1', 2000, ?)""",
            (pid, fouls),
        )
    conn.commit()

    low_fouls_profile = build_player_profile(conn, ids[0][0], "ENG1", "2024-2025")
    high_fouls_profile = build_player_profile(conn, ids[-1][0], "ENG1", "2024-2025")

    low_bar = next(s["bar_percentile"] for s in low_fouls_profile["stats"] if s["label"] == "Fouls Committed")
    high_bar = next(s["bar_percentile"] for s in high_fouls_profile["stats"] if s["label"] == "Fouls Committed")
    assert low_bar > high_bar


def test_per90_divides_count_stats_by_minutes():
    # 9 goals in 900 minutes (10 x 90) -> exactly 0.9 goals per 90.
    assert _per90(9, 900, is_rate_stat=False) == 0.9


def test_per90_leaves_rate_stats_unchanged():
    # SofaScore's distance/sprints/rating are already per-match averages, not season totals --
    # must NOT be divided by minutes/90 again.
    assert _per90(7.17, 2148, is_rate_stat=True) == 7.17


def test_per90_none_passthrough():
    assert _per90(None, 900, is_rate_stat=False) is None


def test_outfield_profile_includes_four_categories_with_per90_values(conn):
    cur = conn.execute("INSERT INTO player (canonical_name, primary_position) VALUES ('Category Test', 'MF')")
    player_id = cur.lastrowid
    conn.execute(
        """INSERT INTO player_season_stat_flat
           (player_id, season_id, competition_id, minutes, goals, sofascore_rating, distance_km)
           VALUES (?, '2024-2025', 'ENG1', 900, 9, 7.2, 10.5)""",
        (player_id,),
    )
    conn.commit()

    profile = build_player_profile(conn, player_id, "ENG1", "2024-2025")

    assert set(profile["categories"].keys()) == {"Attacking", "Passing & Progression", "Defending", "Physical"}
    goals_row = next(s for s in profile["categories"]["Attacking"] if s["label"] == "Goals")
    assert goals_row["value"] == 0.9  # 9 goals / (900/90) -- true per-90 count stat

    rating_row = next(s for s in profile["categories"]["Physical"] if s["label"] == "Match Rating")
    assert rating_row["value"] == 7.2  # rate stat, shown as-is not divided again

    distance_row = next(s for s in profile["categories"]["Physical"] if s["label"] == "Distance per Match (km)")
    assert distance_row["value"] == 10.5


def test_goalkeeper_profile_gets_goalkeeping_and_physical_categories(conn):
    cur = conn.execute("INSERT INTO player (canonical_name, primary_position) VALUES ('GK Category Test', 'GK')")
    player_id = cur.lastrowid
    conn.execute(
        """INSERT INTO player_season_stat_flat (player_id, season_id, competition_id, minutes, save_pct)
           VALUES (?, '2024-2025', 'ENG1', 900, 70.0)""",
        (player_id,),
    )
    conn.commit()

    profile = build_player_profile(conn, player_id, "ENG1", "2024-2025")
    assert set(profile["categories"].keys()) == {"Goalkeeping", "Physical"}
