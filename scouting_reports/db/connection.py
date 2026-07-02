import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "scouting.db"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='player_season_stat_flat'"
    ).fetchone():
        migrate_schema(conn)
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
        migrate_schema(conn)
    finally:
        conn.close()


# Columns added to existing tables after their initial release. New databases get these from
# schema.sql directly; this lets existing local databases pick them up without a rebuild.
_NEW_COLUMNS = {
    "player_season_stat_flat": {
        "interceptions": "INTEGER",
        "shots": "INTEGER",
        "shots_on_target": "INTEGER",
        "fouls_committed": "INTEGER",
        "fouls_drawn": "INTEGER",
        "crosses": "INTEGER",
        "xg_chain": "REAL",
        "xg_buildup": "REAL",
        "key_passes": "INTEGER",
        "save_pct": "REAL",
        "clean_sheet_pct": "REAL",
        "goals_against_90": "REAL",
    },
    "player": {
        "height_cm": "INTEGER",
        "preferred_foot": "TEXT",
        "photo_url": "TEXT",
        "contract_expires": "DATE",
        "international_caps": "INTEGER",
        "international_goals": "INTEGER",
    },
}


def migrate_schema(conn: sqlite3.Connection) -> None:
    for table, columns in _NEW_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, sql_type in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    conn.commit()
