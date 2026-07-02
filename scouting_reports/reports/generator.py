"""Orchestrates report generation: pull a player's merged profile, compute
percentiles, run the deterministic selectors, and render the Jinja2 template.
Refuses to generate a report for a player with zero resolved stats -- never
renders a template against empty/placeholder data.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from scouting_reports.reports.selectors import (
    creativity_selection,
    finishing_selection,
    market_value_selection,
)
from scouting_reports.stats.percentiles import percentile

TEMPLATE_DIR = Path(__file__).parent / "templates"

TEMPLATE_TEXT = {
    "insufficient_minutes": "Not enough minutes played this season to draw a reliable conclusion for this category.",
    "finishing_no_advanced_stats": "{{goals}} goal(s) recorded, but no expected-goals data is available for this competition tier to assess shot quality.",
    "finishing_elite": "Elite finishing output: {{npxg}} non-penalty xG against {{goals}} actual goals, {{pct}}th percentile among peers in this competition.",
    "finishing_above_average": "Above-average finishing: {{npxg}} non-penalty xG, {{pct}}th percentile among peers in this competition.",
    "finishing_average": "Average finishing output for the position: {{npxg}} non-penalty xG, {{pct}}th percentile.",
    "finishing_below_average": "Below-average finishing output: {{npxg}} non-penalty xG, {{pct}}th percentile among peers in this competition.",
    "creativity_no_advanced_stats": "{{assists}} assist(s) recorded, but no expected-assists data is available for this competition tier.",
    "creativity_elite": "Elite chance creation: {{xa}} xA, {{pct}}th percentile among peers in this competition.",
    "creativity_above_average": "Above-average chance creation: {{xa}} xA, {{pct}}th percentile.",
    "creativity_average": "Average chance creation for the position: {{xa}} xA, {{pct}}th percentile.",
    "creativity_below_average": "Below-average chance creation: {{xa}} xA, {{pct}}th percentile among peers in this competition.",
    "market_value_unknown": "No market valuation available.",
    "market_value_known": "Estimated market value: EUR {{value_millions}}m (Transfermarkt).",
}


def _render_selection(selection) -> str:
    text = TEMPLATE_TEXT[selection.template_key]
    for key, value in selection.params.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def generate_report(conn: sqlite3.Connection, player_id: int, competition_id: str, season_id: str) -> str:
    row = conn.execute(
        """SELECT p.canonical_name, p.primary_position, p.last_team_hint,
                  f.minutes, f.goals, f.assists, f.xg, f.xa, f.npxg, f.market_value_eur
           FROM player p LEFT JOIN player_season_stat_flat f
             ON f.player_id = p.player_id AND f.season_id = ? AND f.competition_id = ?
           WHERE p.player_id = ?""",
        (season_id, competition_id, player_id),
    ).fetchone()
    if row is None or row["minutes"] is None:
        raise ValueError(f"No resolved stats for player_id={player_id} in {competition_id}/{season_id}; refusing to generate an empty report")

    competition = conn.execute(
        "SELECT display_name FROM competition WHERE competition_id = ?", (competition_id,)
    ).fetchone()

    npxg_pct = percentile(conn, player_id, season_id, competition_id, "npxg")
    xa_pct = percentile(conn, player_id, season_id, competition_id, "xa")

    finishing = finishing_selection(row["goals"], row["npxg"], npxg_pct, row["minutes"])
    creativity = creativity_selection(row["assists"], row["xa"], xa_pct, row["minutes"])
    market_value = market_value_selection(row["market_value_eur"])

    sources = conn.execute(
        "SELECT DISTINCT source, MAX(fetched_at) as latest FROM stats_snapshot WHERE player_id = ? GROUP BY source",
        (player_id,),
    ).fetchall()
    sources_line = "; ".join(f"{r['source']} (as of {r['latest'][:10]})" for r in sources)

    tier = conn.execute("SELECT tier FROM competition WHERE competition_id = ?", (competition_id,)).fetchone()["tier"]
    tier_caveat = (
        "Advanced metrics (xG/xA) are unavailable for this competition tier; only basic stats and market value are shown."
        if tier > 1 and row["xg"] is None
        else ""
    )

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.md.j2")
    return template.render(
        player_name=row["canonical_name"],
        team=row["last_team_hint"] or "Unknown",
        position=row["primary_position"],
        competition_name=competition["display_name"] if competition else competition_id,
        season=season_id,
        minutes=row["minutes"],
        goals=row["goals"],
        assists=row["assists"],
        finishing_text=_render_selection(finishing),
        creativity_text=_render_selection(creativity),
        market_value_text=_render_selection(market_value),
        sources_line=sources_line,
        as_of_date=datetime.now(timezone.utc).date().isoformat(),
        tier_caveat=tier_caveat,
    )
