import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import pandas as pd

from scouting_reports.identity.match import resolve_player_id


class SourceIngestor(ABC):
    source_name: str

    @abstractmethod
    def fetch(self, competition_id: str, season_id: str) -> pd.DataFrame:
        """Pull raw data for one competition/season from this source."""

    @abstractmethod
    def normalize(self, raw: pd.DataFrame, competition_id: str, season_id: str) -> pd.DataFrame:
        """Return a DataFrame with at least: source_player_id, source_name,
        date_of_birth (nullable), team_hint (nullable), stat_type, plus stat columns."""

    def load(self, conn: sqlite3.Connection, normalized: pd.DataFrame, competition_id: str, season_id: str) -> int:
        rows_written = 0
        for _, row in normalized.iterrows():
            player_id = resolve_player_id(
                conn,
                source=self.source_name,
                source_player_id=str(row["source_player_id"]),
                source_name=row["source_name"],
                date_of_birth=row.get("date_of_birth"),
                team_hint=row.get("team_hint"),
            )
            if player_id is None:
                continue  # routed to review queue instead, no stats row written yet

            payload = row.drop(
                labels=[c for c in ("source_player_id", "source_name", "date_of_birth", "team_hint")
                        if c in row.index]
            ).to_dict()

            conn.execute(
                """INSERT INTO stats_snapshot
                   (player_id, source, competition_id, season_id, stat_type, fetched_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    self.source_name,
                    competition_id,
                    season_id,
                    row.get("stat_type", "standard"),
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(payload, default=str),
                ),
            )
            rows_written += 1
        conn.commit()
        return rows_written

    def run(self, conn: sqlite3.Connection, competition_id: str, season_id: str) -> int:
        started_at = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO ingest_run (source, competition_id, started_at, status) VALUES (?, ?, ?, 'running')",
            (self.source_name, competition_id, started_at),
        )
        run_id = cur.lastrowid
        conn.commit()
        try:
            raw = self.fetch(competition_id, season_id)
            normalized = self.normalize(raw, competition_id, season_id)
            rows_written = self.load(conn, normalized, competition_id, season_id)
            conn.execute(
                "UPDATE ingest_run SET finished_at = ?, status = 'success', rows_written = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), rows_written, run_id),
            )
            conn.commit()
            return rows_written
        except Exception as exc:
            conn.execute(
                "UPDATE ingest_run SET finished_at = ?, status = 'failed', error_message = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), str(exc), run_id),
            )
            conn.commit()
            raise
