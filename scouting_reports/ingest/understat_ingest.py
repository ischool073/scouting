"""Understat ingestion for Big-5 top-flight competitions, via `soccerdata`.

Requires soccerdata>=1.9 -- earlier versions fail to parse Understat's current
homepage after their front-end redesign (see requirements.txt comment).
Understat has no lower-division coverage; competitions with understat_key=null
are skipped entirely (see cli.py orchestration).
"""
import pandas as pd
import soccerdata as sd

from scouting_reports.ingest.base import SourceIngestor


class UnderstatIngestor(SourceIngestor):
    source_name = "understat"

    def __init__(self, understat_key: str, cache_dir=None):
        self.understat_key = understat_key
        self._reader_kwargs = {"data_dir": cache_dir} if cache_dir else {}

    def fetch(self, competition_id: str, season_id: str) -> pd.DataFrame:
        soccerdata_season = _to_soccerdata_season(season_id)
        reader = sd.Understat(leagues=self.understat_key, seasons=soccerdata_season, **self._reader_kwargs)
        df = reader.read_player_season_stats().reset_index()
        df["stat_type"] = "understat_xg"
        return df

    def normalize(self, raw: pd.DataFrame, competition_id: str, season_id: str) -> pd.DataFrame:
        # raw's index levels are ('league', 'season', 'team', 'player'); read_player_season_stats()
        # is reset_index()'d in fetch(), so those are already plain columns here.
        out = raw.copy()
        out["source_name"] = raw["player"]
        out["source_player_id"] = raw["player_id"].astype(str)
        out["team_hint"] = raw["team"]
        out["date_of_birth"] = None
        return out


def _to_soccerdata_season(season_id: str) -> str:
    start, _ = season_id.split("-")
    return start
