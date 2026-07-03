"""FBref ingestion for Big-5 top-flight competitions, via the `soccerdata` package.

Requires soccerdata>=1.9 -- earlier versions fail against FBref's current
Cloudflare-protected front end (see requirements.txt comment).
"""
import pandas as pd
import soccerdata as sd

from scouting_reports.ingest.base import SourceIngestor

# Valid stat_type values per soccerdata 1.9's FBref.read_player_season_stats() -- confirmed by
# calling it and reading the TypeError's allowed-values list. Advanced passing/defense/possession
# tables (available on FBref itself) are not exposed through this method in this library version.
STAT_TYPES = ("standard", "keeper", "shooting", "playing_time", "misc")


class FBrefTopIngestor(SourceIngestor):
    source_name = "fbref"

    def __init__(self, fbref_key: str, cache_dir=None):
        self.fbref_key = fbref_key
        self._reader_kwargs = {"data_dir": cache_dir} if cache_dir else {}

    def fetch(self, competition_id: str, season_id: str) -> pd.DataFrame:
        soccerdata_season = _to_soccerdata_season(season_id)
        reader = sd.FBref(leagues=self.fbref_key, seasons=soccerdata_season, **self._reader_kwargs)
        frames = []
        for stat_type in STAT_TYPES:
            df = reader.read_player_season_stats(stat_type=stat_type)
            df.columns = ["_".join(c for c in col if c).strip() if isinstance(col, tuple) else col
                           for col in df.columns]
            df = df.reset_index()
            df["stat_type"] = stat_type
            frames.append(df)
        return pd.concat(frames, ignore_index=True)

    def normalize(self, raw: pd.DataFrame, competition_id: str, season_id: str) -> pd.DataFrame:
        out = raw.rename(columns={
            "player": "source_name",
            "team": "team_hint",
            "born": "birth_year",
        }).copy()
        # FBref exposes birth year, not a full DOB -- kept as a weaker signal for identity matching.
        out["date_of_birth"] = None
        out["source_player_id"] = out["source_name"].astype(str) + "|" + out.get("team_hint", "").astype(str)
        return out


def _to_soccerdata_season(season_id: str) -> str:
    """Convert our '2024-2025' season_id into soccerdata's '2425' format."""
    start, end = season_id.split("-")
    return start[-2:] + end[-2:]
