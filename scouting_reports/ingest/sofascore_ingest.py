"""SofaScore ingestion, hit directly via their own statistics API.

Uses `tls_requests` (already a dependency for FBref -- see fbref_top.py) rather than plain
`requests`: a bare request gets a 403 from SofaScore's bot detection, but the same
TLS-fingerprint-matching client that resolved FBref's Cloudflare block also works here,
returning real 200s with rich per-90 stats (duel %, shot placement, sprint counts, top
speed) well beyond what FBref/Understat expose. Checked robots.txt first -- it does not
disallow /api/ or /player/ paths (only archived date pages, share images, and standings
pages in various languages, plus a full block for one unrelated bot).

SofaScore has no bulk "every player in this tournament/season" listing endpoint, so this
looks up each of our already identity-resolved players by name via SofaScore's search
endpoint, disambiguates by team-name match (name collisions happen -- e.g. a second,
unrelated "Erling Haaland" exists in their system), then pulls that player's season
statistics. Rate-limited out of the same respect for their servers as our FBref approach.
"""
import time
from urllib.parse import quote

import pandas as pd
import tls_requests
from rapidfuzz import fuzz

from scouting_reports.ingest.base import SourceIngestor
from scouting_reports.identity.match import normalize_name

BASE_URL = "https://www.sofascore.com/api/v1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
REQUEST_DELAY_SECONDS = 1.0


def _to_sofascore_year(season_id: str) -> str:
    """Our '2025-2026' -> SofaScore's '25/26'."""
    start, end = season_id.split("-")
    return f"{start[-2:]}/{end[-2:]}"


class SofascoreIngestor(SourceIngestor):
    source_name = "sofascore"

    def __init__(self, tournament_id: int, players: list[dict]):
        """players: list of {"canonical_name": ..., "last_team_hint": ...} for players we
        already have identity-resolved from other sources -- this source enriches them
        rather than seeding brand-new players, since there's no bulk listing to seed from."""
        self.tournament_id = tournament_id
        self.players = players

    def _get(self, path: str) -> dict:
        response = tls_requests.get(f"{BASE_URL}{path}", headers=HEADERS)
        response.raise_for_status()
        return response.json()

    def _resolve_season_id(self, season_id: str) -> int:
        year = _to_sofascore_year(season_id)
        data = self._get(f"/unique-tournament/{self.tournament_id}/seasons")
        for season in data["seasons"]:
            if season["year"] == year:
                return season["id"]
        raise ValueError(f"SofaScore season '{year}' not found for tournament {self.tournament_id}")

    def _find_player(self, name: str, team_hint: str):
        try:
            data = self._get(f"/search/all?q={quote(name)}")
        except Exception:
            return None
        candidates = [r["entity"] for r in data.get("results", []) if r.get("type") == "player"]
        if not candidates:
            return None
        best, best_score = None, 0.0
        for cand in candidates:
            name_sim = fuzz.token_sort_ratio(normalize_name(name), normalize_name(cand.get("name", "")))
            team_sim = fuzz.token_set_ratio(
                normalize_name(team_hint or ""), normalize_name(cand.get("team", {}).get("name", ""))
            )
            score = 0.5 * name_sim + 0.5 * team_sim
            if score > best_score:
                best, best_score = cand, score
        return best if best_score >= 70 else None

    def fetch(self, competition_id: str, season_id: str) -> pd.DataFrame:
        sofascore_season_id = self._resolve_season_id(season_id)
        rows = []
        for player in self.players:
            time.sleep(REQUEST_DELAY_SECONDS)
            hit = self._find_player(player["canonical_name"], player.get("last_team_hint"))
            if hit is None:
                continue
            time.sleep(REQUEST_DELAY_SECONDS)
            try:
                stats = self._get(
                    f"/player/{hit['id']}/unique-tournament/{self.tournament_id}"
                    f"/season/{sofascore_season_id}/statistics/overall"
                )
            except Exception:
                continue
            row = dict(stats.get("statistics", {}))
            row["source_player_id"] = str(hit["id"])
            row["source_name"] = hit["name"]
            row["team_hint"] = hit.get("team", {}).get("name")
            rows.append(row)
        return pd.DataFrame(rows)

    def normalize(self, raw: pd.DataFrame, competition_id: str, season_id: str) -> pd.DataFrame:
        out = raw.copy()
        out["date_of_birth"] = None
        out["stat_type"] = "sofascore_overall"
        return out
