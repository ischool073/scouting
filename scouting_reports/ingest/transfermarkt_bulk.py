"""Transfermarkt ingestion via the pre-scraped, weekly-refreshed dcaribou/transfermarkt-datasets
DuckDB file -- not a live scraper. Download once (or re-download if it's gone stale):

    curl -L -o data/transfermarkt_bulk/transfermarkt-datasets.duckdb \
        https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.duckdb

NOTE: as of this writing, the dataset only contains ONE domestic league competition per
country (e.g. 'GB1' for England) -- no 2nd/3rd tier competitions exist in it despite earlier
assumptions to the contrary. This module currently only supplies data for tier-1 competitions;
tier-2/3 support depends on a decision covered separately (see conversation/plan notes), not
addressed by this module.
"""
from pathlib import Path

import duckdb
import pandas as pd

from scouting_reports.ingest.base import SourceIngestor

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "transfermarkt_bulk" / "transfermarkt-datasets.duckdb"


class TransfermarktBulkIngestor(SourceIngestor):
    source_name = "transfermarkt"

    def __init__(self, transfermarkt_competition_id: str, db_path: Path = DEFAULT_DB_PATH):
        self.transfermarkt_competition_id = transfermarkt_competition_id
        self.db_path = db_path

    def fetch(self, competition_id: str, season_id: str) -> pd.DataFrame:
        con = duckdb.connect(str(self.db_path), read_only=True)
        try:
            return con.execute(
                """SELECT player_id, name, date_of_birth, position, current_club_name,
                          market_value_in_eur, highest_market_value_in_eur
                   FROM players
                   WHERE current_club_domestic_competition_id = ?""",
                [self.transfermarkt_competition_id],
            ).fetchdf()
        finally:
            con.close()

    def normalize(self, raw: pd.DataFrame, competition_id: str, season_id: str) -> pd.DataFrame:
        out = raw.rename(columns={
            "name": "source_name",
            "current_club_name": "team_hint",
        }).copy()
        out["source_player_id"] = out["player_id"].astype(str)
        dob = pd.to_datetime(out["date_of_birth"]).dt.strftime("%Y-%m-%d")
        out["date_of_birth"] = dob.where(pd.notna(dob), None)
        out["stat_type"] = "market_value"
        return out
