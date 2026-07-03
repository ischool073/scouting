"""Orchestrates report generation: pull a player's merged profile, compute
percentiles, run the deterministic selectors, and build a structured profile
that both the CLI (markdown) and web app (rich HTML) render from -- so both
surfaces read from a single source of truth, not duplicated query logic.

Refuses to build a profile for a player with zero resolved stats -- never
renders a template against empty/placeholder data.
"""
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from scouting_reports.reports.radar import build_radar_svg
from scouting_reports.reports.selectors import (
    buildup_selection,
    creativity_selection,
    defensive_selection,
    discipline_selection,
    finishing_selection,
    goalkeeping_selection,
    market_value_selection,
    shot_volume_selection,
)
from scouting_reports.stats.percentiles import MIN_MINUTES_FOR_PERCENTILE, percentile, position_group

TEMPLATE_DIR = Path(__file__).parent / "templates"

TEMPLATE_TEXT = {
    "insufficient_minutes": "Not enough minutes played this season to draw a reliable conclusion for this category.",
    "finishing_no_advanced_stats": "{{goals}} goal(s) recorded, but no expected-goals data is available for this competition tier to assess shot quality.",
    "finishing_elite": "Elite finishing output: {{npxg}} non-penalty xG against {{goals}} actual goals, {{pct}} percentile among peers in this competition.",
    "finishing_above_average": "Above-average finishing: {{npxg}} non-penalty xG, {{pct}} percentile among peers in this competition.",
    "finishing_average": "Average finishing output for the position: {{npxg}} non-penalty xG, {{pct}} percentile.",
    "finishing_below_average": "Below-average finishing output: {{npxg}} non-penalty xG, {{pct}} percentile among peers in this competition.",
    "creativity_no_advanced_stats": "{{assists}} assist(s) recorded, but no expected-assists data is available for this competition tier.",
    "creativity_elite": "Elite chance creation: {{xa}} xA, {{pct}} percentile among peers in this competition.",
    "creativity_above_average": "Above-average chance creation: {{xa}} xA, {{pct}} percentile.",
    "creativity_average": "Average chance creation for the position: {{xa}} xA, {{pct}} percentile.",
    "creativity_below_average": "Below-average chance creation: {{xa}} xA, {{pct}} percentile among peers in this competition.",
    "defensive_no_advanced_stats": "No tackle/interception data available for this competition tier.",
    "defensive_elite": "Elite defensive workrate: {{tackles_won}} tackles won, {{interceptions}} interceptions, {{pct}} percentile among peers.",
    "defensive_above_average": "Above-average defensive activity: {{tackles_won}} tackles won, {{interceptions}} interceptions, {{pct}} percentile.",
    "defensive_average": "Average defensive activity for the position: {{tackles_won}} tackles won, {{interceptions}} interceptions, {{pct}} percentile.",
    "defensive_below_average": "Below-average defensive activity: {{tackles_won}} tackles won, {{interceptions}} interceptions, {{pct}} percentile.",
    "shot_volume_no_advanced_stats": "No shooting data available for this competition tier.",
    "shot_volume_known": "{{shots}} shots, {{shots_on_target}} on target ({{accuracy}}% accuracy).",
    "shot_volume_elite": "High shot-accuracy profile: {{shots}} shots, {{shots_on_target}} on target ({{accuracy}}%), {{pct}} percentile on shots-on-target rate.",
    "shot_volume_above_average": "Above-average shot accuracy: {{shots}} shots, {{shots_on_target}} on target ({{accuracy}}%), {{pct}} percentile.",
    "shot_volume_average": "Average shot accuracy for the position: {{shots}} shots, {{shots_on_target}} on target ({{accuracy}}%), {{pct}} percentile.",
    "shot_volume_below_average": "Below-average shot accuracy: {{shots}} shots, {{shots_on_target}} on target ({{accuracy}}%), {{pct}} percentile.",
    "discipline_no_advanced_stats": "No foul data available for this competition tier.",
    "discipline_known": "Committed {{fouls_committed}} fouls and drew {{fouls_drawn}} fouls this season.",
    "buildup_no_advanced_stats": "{{key_passes}} key pass(es) recorded, but no build-up involvement data (xG chain/buildup) is available for this competition tier.",
    "buildup_elite": "Heavily involved in build-up play: {{xg_chain}} xG chain, {{xg_buildup}} xG buildup, {{key_passes}} key passes, {{pct}} percentile.",
    "buildup_above_average": "Above-average build-up involvement: {{xg_chain}} xG chain, {{xg_buildup}} xG buildup, {{key_passes}} key passes, {{pct}} percentile.",
    "buildup_average": "Average build-up involvement for the position: {{xg_chain}} xG chain, {{xg_buildup}} xG buildup, {{pct}} percentile.",
    "buildup_below_average": "Below-average build-up involvement: {{xg_chain}} xG chain, {{xg_buildup}} xG buildup, {{pct}} percentile.",
    "goalkeeping_no_advanced_stats": "No goalkeeping data available for this competition tier.",
    "goalkeeping_known": "{{save_pct}}% save rate, {{clean_sheet_pct}}% clean sheet rate, {{goals_against_90}} goals conceded per 90.",
    "market_value_unknown": "No market valuation available.",
    "market_value_known": "Estimated market value: EUR {{value_millions}}m (Transfermarkt).",
}

# Every numeric field we currently store per player-season, for the "show everything" stats
# table. (label, column, percentile_column_or_None, lower_is_better)
# percentile_column is None where a percentile cohort wouldn't be meaningful (counts that are
# inherently cumulative/contextual rather than a "quality" signal, e.g. raw minutes).
STAT_FIELDS = [
    ("Minutes Played", "minutes", None, False),
    ("Goals", "goals", None, False),
    ("Assists", "assists", None, False),
    ("Expected Goals (xG)", "xg", "xg", False),
    ("Non-Penalty xG", "npxg", "npxg", False),
    ("Expected Assists (xA)", "xa", "xa", False),
    ("Shots", "shots", "shots", False),
    ("Shots on Target", "shots_on_target", "shots_on_target", False),
    ("Key Passes", "key_passes", "key_passes", False),
    ("xG Chain", "xg_chain", "xg_chain", False),
    ("xG Buildup", "xg_buildup", "xg_buildup", False),
    ("Tackles Won", "tackles_won", "tackles_won", False),
    ("Interceptions", "interceptions", "interceptions", False),
    ("Crosses", "crosses", "crosses", False),
    ("Fouls Committed", "fouls_committed", "fouls_committed", True),
    ("Fouls Drawn", "fouls_drawn", "fouls_drawn", False),
    ("Save %", "save_pct", "save_pct", False),
    ("Clean Sheet %", "clean_sheet_pct", "clean_sheet_pct", False),
    ("Goals Conceded per 90", "goals_against_90", "goals_against_90", True),
    ("Match Rating", "sofascore_rating", "sofascore_rating", False),
    ("Distance per Match (km)", "distance_km", "distance_km", False),
    ("Sprints per Match", "sprints", "sprints", False),
    ("Top Speed (km/h)", "top_speed_kmh", "top_speed_kmh", False),
    ("Duels Won %", "duels_won_pct", "duels_won_pct", False),
    ("Dribbles Won %", "dribbles_won_pct", "dribbles_won_pct", False),
    ("Big Chances Created", "big_chances_created", "big_chances_created", False),
    ("Market Value (EUR)", "market_value_eur", "market_value_eur", False),
]

# Dashboard category grid: (label, column, percentile_column, lower_is_better, is_rate_stat).
# is_rate_stat=True means the stored value is already a per-match average or a peak (e.g.
# SofaScore's distance/sprints/top-speed/rating/percentages), not a season total -- shown as-is
# rather than divided by minutes/90 the way count stats (goals, tackles, shots...) are.
PHYSICAL_CATEGORY = [
    ("Match Rating", "sofascore_rating", "sofascore_rating", False, True),
    ("Distance per Match (km)", "distance_km", "distance_km", False, True),
    ("Sprints per Match", "sprints", "sprints", False, True),
    ("Top Speed (km/h)", "top_speed_kmh", "top_speed_kmh", False, True),
]

OUTFIELD_CATEGORIES = {
    "Attacking": [
        ("Goals", "goals", None, False, False),
        ("Expected Goals (xG)", "xg", "xg", False, False),
        ("Shots", "shots", "shots", False, False),
        ("Shots on Target", "shots_on_target", "shots_on_target", False, False),
        ("Big Chances Created", "big_chances_created", "big_chances_created", False, False),
        ("Fouls Won", "fouls_drawn", "fouls_drawn", False, False),
    ],
    "Passing & Progression": [
        ("Assists", "assists", None, False, False),
        ("Expected Assists (xA)", "xa", "xa", False, False),
        ("Key Passes", "key_passes", "key_passes", False, False),
        ("xG Chain", "xg_chain", "xg_chain", False, False),
        ("xG Buildup", "xg_buildup", "xg_buildup", False, False),
        ("Crosses", "crosses", "crosses", False, False),
    ],
    "Defending": [
        ("Tackles Won", "tackles_won", "tackles_won", False, False),
        ("Interceptions", "interceptions", "interceptions", False, False),
        ("Duels Won %", "duels_won_pct", "duels_won_pct", False, True),
        ("Dribbles Won %", "dribbles_won_pct", "dribbles_won_pct", False, True),
        ("Fouls Committed", "fouls_committed", "fouls_committed", True, False),
    ],
    "Physical": PHYSICAL_CATEGORY,
}

GOALKEEPER_CATEGORIES = {
    "Goalkeeping": [
        ("Save %", "save_pct", "save_pct", False, True),
        ("Clean Sheet %", "clean_sheet_pct", "clean_sheet_pct", False, True),
        ("Goals Conceded per 90", "goals_against_90", "goals_against_90", True, True),
    ],
    "Physical": PHYSICAL_CATEGORY,
}


def _render_selection(selection) -> str:
    text = TEMPLATE_TEXT[selection.template_key]
    for key, value in selection.params.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def _combined_percentile(conn, player_id, season_id, competition_id, columns) -> Optional[float]:
    values = [percentile(conn, player_id, season_id, competition_id, c) for c in columns]
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _format_stat_value(column: str, value) -> Optional[str]:
    """Always returns a ready-to-display string (or None) -- the single place that decides
    how a stat value looks, so templates never need their own type-sniffing/rounding logic."""
    if value is None:
        return None
    if column == "market_value_eur":
        return f"EUR {value / 1_000_000:.1f}m"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _per90(value, minutes: Optional[int], is_rate_stat: bool):
    if value is None:
        return None
    if is_rate_stat or not minutes:
        return round(value, 2) if isinstance(value, float) else value
    return round(value / (minutes / 90), 2)


def _build_category(conn, player_id, season_id, competition_id, row, fields) -> list[dict]:
    result = []
    for label, column, pct_column, lower_is_better, is_rate in fields:
        raw_value = row[column]
        pct = percentile(conn, player_id, season_id, competition_id, pct_column) if pct_column and raw_value is not None else None
        bar_pct = (1 - pct) if (pct is not None and lower_is_better) else pct
        result.append({
            "label": label,
            "value": _per90(raw_value, row["minutes"], is_rate),
            "percentile": pct,
            "bar_percentile": bar_pct,
        })
    return result


def _age(date_of_birth: Optional[str]) -> Optional[int]:
    if not date_of_birth:
        return None
    dob = date.fromisoformat(date_of_birth)
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def build_player_profile(conn: sqlite3.Connection, player_id: int, competition_id: str, season_id: str) -> dict:
    """Returns a structured dict with bio info, every stored stat (+ percentile where
    meaningful), and the deterministic narrative sections -- the single source of truth
    both the CLI markdown report and the web profile page render from."""
    row = conn.execute(
        """SELECT p.canonical_name, p.primary_position, p.last_team_hint, p.date_of_birth,
                  p.nationality, p.height_cm, p.preferred_foot, p.photo_url,
                  p.contract_expires, p.international_caps, p.international_goals,
                  f.minutes, f.appearances, f.starts, f.goals, f.assists, f.xg, f.xa, f.npxg, f.market_value_eur,
                  f.tackles_won, f.interceptions, f.shots, f.shots_on_target, f.crosses,
                  f.fouls_committed, f.fouls_drawn, f.xg_chain, f.xg_buildup, f.key_passes,
                  f.save_pct, f.clean_sheet_pct, f.goals_against_90,
                  f.sofascore_rating, f.distance_km, f.sprints, f.top_speed_kmh,
                  f.duels_won_pct, f.dribbles_won_pct, f.big_chances_created
           FROM player p LEFT JOIN player_season_stat_flat f
             ON f.player_id = p.player_id AND f.season_id = ? AND f.competition_id = ?
           WHERE p.player_id = ?""",
        (season_id, competition_id, player_id),
    ).fetchone()
    if row is None or row["minutes"] is None:
        raise ValueError(f"No resolved stats for player_id={player_id} in {competition_id}/{season_id}; refusing to generate an empty report")

    competition = conn.execute(
        "SELECT display_name, tier FROM competition WHERE competition_id = ?", (competition_id,)
    ).fetchone()

    is_goalkeeper = position_group(row["primary_position"]) == "Goalkeeper"

    sections = {}
    radar = []
    if is_goalkeeper:
        sections["Goalkeeping"] = _render_selection(
            goalkeeping_selection(row["save_pct"], row["clean_sheet_pct"], row["goals_against_90"], row["minutes"])
        )
        save_pct_pct = percentile(conn, player_id, season_id, competition_id, "save_pct")
        cs_pct_pct = percentile(conn, player_id, season_id, competition_id, "clean_sheet_pct")
        ga90_pct = percentile(conn, player_id, season_id, competition_id, "goals_against_90")
        radar = [
            {"label": "Shot Stopping", "percentile": save_pct_pct},
            {"label": "Clean Sheets", "percentile": cs_pct_pct},
            {"label": "Goals Prevented", "percentile": (1 - ga90_pct) if ga90_pct is not None else None},
        ]
    else:
        npxg_pct = percentile(conn, player_id, season_id, competition_id, "npxg")
        xa_pct = percentile(conn, player_id, season_id, competition_id, "xa")
        defensive_pct = _combined_percentile(conn, player_id, season_id, competition_id, ["tackles_won", "interceptions"])
        sot_pct = percentile(conn, player_id, season_id, competition_id, "shots_on_target")
        xg_chain_pct = percentile(conn, player_id, season_id, competition_id, "xg_chain")

        sections["Finishing"] = _render_selection(finishing_selection(row["goals"], row["npxg"], npxg_pct, row["minutes"]))
        sections["Creativity"] = _render_selection(creativity_selection(row["assists"], row["xa"], xa_pct, row["minutes"]))
        sections["Shooting"] = _render_selection(shot_volume_selection(row["shots"], row["shots_on_target"], sot_pct, row["minutes"]))
        sections["Defensive Actions"] = _render_selection(
            defensive_selection(row["tackles_won"], row["interceptions"], defensive_pct, row["minutes"])
        )
        sections["Build-up Play"] = _render_selection(
            buildup_selection(row["xg_chain"], row["xg_buildup"], row["key_passes"], xg_chain_pct, row["minutes"])
        )
        sections["Discipline"] = _render_selection(discipline_selection(row["fouls_committed"], row["fouls_drawn"], row["minutes"]))

        radar = [
            {"label": "Finishing", "percentile": npxg_pct},
            {"label": "Creativity", "percentile": xa_pct},
            {"label": "Shooting", "percentile": sot_pct},
            {"label": "Defending", "percentile": defensive_pct},
            {"label": "Build-up", "percentile": xg_chain_pct},
        ]

    sections["Market Value"] = _render_selection(market_value_selection(row["market_value_eur"]))

    stats = []
    for label, column, pct_column, lower_is_better in STAT_FIELDS:
        value = row[column]
        pct = percentile(conn, player_id, season_id, competition_id, pct_column) if pct_column and value is not None else None
        bar_pct = (1 - pct) if (pct is not None and lower_is_better) else pct
        display = _format_stat_value(column, value)
        stats.append({"label": label, "value": value, "display": display, "percentile": pct, "bar_percentile": bar_pct})

    category_source = GOALKEEPER_CATEGORIES if is_goalkeeper else OUTFIELD_CATEGORIES
    categories = {
        title: _build_category(conn, player_id, season_id, competition_id, row, fields)
        for title, fields in category_source.items()
    }

    # Bottom comparison bar: a handful of headline percentiles, computed the same way as
    # everywhere else (real cohort-based percentile(), not a fabricated "rank out of N").
    highlight_columns = (
        [("Save %", "save_pct"), ("Clean Sheet %", "clean_sheet_pct"), ("Match Rating", "sofascore_rating")]
        if is_goalkeeper
        else [
            ("Goals", "goals"), ("xG", "xg"), ("Assists", "assists"), ("Key Passes", "key_passes"),
            ("Interceptions", "interceptions"), ("Duels Won %", "duels_won_pct"), ("Match Rating", "sofascore_rating"),
        ]
    )
    highlight_chips = []
    for label, column in highlight_columns:
        pct = percentile(conn, player_id, season_id, competition_id, column) if row[column] is not None else None
        if pct is not None:
            highlight_chips.append({"label": label, "percentile": pct})

    comparison_context = {
        "position_group": position_group(row["primary_position"]),
        "competition_name": competition["display_name"] if competition else competition_id,
        "min_minutes": MIN_MINUTES_FOR_PERCENTILE,
    }

    sources = conn.execute(
        "SELECT DISTINCT source, MAX(fetched_at) as latest FROM stats_snapshot WHERE player_id = ? GROUP BY source",
        (player_id,),
    ).fetchall()
    sources_line = "; ".join(f"{r['source']} (as of {r['latest'][:10]})" for r in sources)

    tier_caveat = (
        "Advanced metrics (xG/xA and beyond) are unavailable for this competition tier; only basic stats and market value are shown."
        if competition and competition["tier"] > 1 and row["xg"] is None
        else ""
    )

    return {
        "player_name": row["canonical_name"],
        "team": row["last_team_hint"] or "Unknown",
        "position": row["primary_position"],
        "position_group": position_group(row["primary_position"]),
        "competition_name": competition["display_name"] if competition else competition_id,
        "season": season_id,
        "minutes": row["minutes"],
        "appearances": row["appearances"],
        "starts": row["starts"],
        "goals": row["goals"],
        "assists": row["assists"],
        "match_rating": row["sofascore_rating"],
        "match_rating_percentile": percentile(conn, player_id, season_id, competition_id, "sofascore_rating") if row["sofascore_rating"] is not None else None,
        "bio": {
            "date_of_birth": row["date_of_birth"],
            "age": _age(row["date_of_birth"]),
            "nationality": row["nationality"],
            "height_cm": row["height_cm"],
            "preferred_foot": row["preferred_foot"],
            "photo_url": row["photo_url"],
            "contract_expires": row["contract_expires"],
            "international_caps": row["international_caps"],
            "international_goals": row["international_goals"],
        },
        "sections": sections,
        "stats": stats,
        "categories": categories,
        "highlight_chips": highlight_chips,
        "comparison_context": comparison_context,
        "radar": radar,
        "radar_svg": build_radar_svg(radar),
        "sources_line": sources_line,
        "as_of_date": datetime.now(timezone.utc).date().isoformat(),
        "tier_caveat": tier_caveat,
    }


def generate_report(conn: sqlite3.Connection, player_id: int, competition_id: str, season_id: str) -> str:
    """CLI-facing: renders the plain-text/markdown report."""
    profile = build_player_profile(conn, player_id, competition_id, season_id)
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.md.j2")
    return template.render(**profile)
