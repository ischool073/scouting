import sqlite3
from pathlib import Path

import yaml

LEAGUES_YAML_PATH = Path(__file__).parent.parent / "config" / "leagues.yaml"


def load_leagues(path: Path = LEAGUES_YAML_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["leagues"]


def ensure_season(conn: sqlite3.Connection, season_id: str) -> None:
    start, end = season_id.split("-")
    conn.execute(
        "INSERT OR IGNORE INTO season (season_id, start_year, end_year) VALUES (?, ?, ?)",
        (season_id, int(start), int(end)),
    )
    conn.commit()


def sync_competitions(conn: sqlite3.Connection, path: Path = LEAGUES_YAML_PATH) -> None:
    """Upsert config/leagues.yaml rows into the `competition` table."""
    for league in load_leagues(path):
        conn.execute(
            """INSERT INTO competition
               (competition_id, country, tier, display_name, fbref_source, fbref_key, understat_key, transfermarkt_comp_id)
               VALUES (:id, :country, :tier, :display_name, :fbref_source, :fbref_key, :understat_key, :transfermarkt_competition_id)
               ON CONFLICT(competition_id) DO UPDATE SET
                 country=excluded.country, tier=excluded.tier, display_name=excluded.display_name,
                 fbref_source=excluded.fbref_source, fbref_key=excluded.fbref_key,
                 understat_key=excluded.understat_key, transfermarkt_comp_id=excluded.transfermarkt_comp_id
            """,
            league,
        )
    conn.commit()
