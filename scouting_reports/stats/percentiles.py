"""Computes a player's percentile for a given stat, within a cohort of players who
share the same competition, season, and position group. Tier-3-only players (no xG
etc.) are simply excluded from the cohorts they don't have data for -- they never
pollute a tier-1 cohort's distribution, and they never receive a percentile for a
stat they don't have.
"""
import sqlite3
from typing import Optional

MIN_MINUTES_FOR_PERCENTILE = 450  # roughly 5 full matches; below this, sample size is too noisy

# Coarse position groups so cohorts have enough players to be statistically meaningful.
POSITION_GROUPS = {
    "GK": "Goalkeeper",
    "DF": "Defender",
    "MF": "Midfielder",
    "FW": "Forward",
}


def position_group(primary_position: Optional[str]) -> str:
    if not primary_position:
        return "Unknown"
    return POSITION_GROUPS.get(primary_position.strip().upper(), "Unknown")


def percentile(
    conn: sqlite3.Connection,
    player_id: int,
    season_id: str,
    competition_id: str,
    stat_column: str,
) -> Optional[float]:
    """Return player's percentile (0.0-1.0) for stat_column within their position-group
    cohort in this competition/season, or None if the player or the cohort lacks the stat."""
    if stat_column not in _ALLOWED_STAT_COLUMNS:
        raise ValueError(f"Unsupported stat_column: {stat_column}")

    player_row = conn.execute(
        f"""SELECT f.{stat_column} as value, p.primary_position
            FROM player_season_stat_flat f JOIN player p ON p.player_id = f.player_id
            WHERE f.player_id = ? AND f.season_id = ? AND f.competition_id = ?""",
        (player_id, season_id, competition_id),
    ).fetchone()
    if player_row is None or player_row["value"] is None:
        return None

    group = position_group(player_row["primary_position"])
    # Position-group filtering happens in Python (not SQL) since position_group() does name
    # normalization not directly expressible in SQL.
    cohort_values = [
        row["value"]
        for row in conn.execute(
            f"""SELECT f.{stat_column} as value, p.primary_position
                FROM player_season_stat_flat f JOIN player p ON p.player_id = f.player_id
                WHERE f.season_id = ? AND f.competition_id = ?
                  AND f.{stat_column} IS NOT NULL AND f.minutes >= ?""",
            (season_id, competition_id, MIN_MINUTES_FOR_PERCENTILE),
        ).fetchall()
        if position_group(row["primary_position"]) == group
    ]
    if len(cohort_values) < 5:  # cohort too small to be a meaningful percentile
        return None

    value = player_row["value"]
    rank = sum(1 for v in cohort_values if v <= value)
    return rank / len(cohort_values)


_ALLOWED_STAT_COLUMNS = {
    "xg", "xa", "npxg", "goals", "assists", "minutes",
    "progressive_carries", "progressive_passes", "tackles_won", "interceptions",
    "shots", "shots_on_target", "fouls_committed", "fouls_drawn", "crosses",
    "xg_chain", "xg_buildup", "key_passes",
    "save_pct", "clean_sheet_pct", "goals_against_90",
    "sofascore_rating", "distance_km", "sprints", "top_speed_kmh",
    "duels_won_pct", "dribbles_won_pct", "big_chances_created",
    "market_value_eur",
}
