"""A small local web app: search a player by name, view their generated
scouting report in the browser instead of the terminal.

Run with:
    .venv\\Scripts\\python.exe -m scouting_reports.web.app
Then open http://127.0.0.1:5000 in a browser.
"""
from flask import Flask, render_template, request

from scouting_reports.db.connection import get_connection
from scouting_reports.reports.generator import build_player_profile

app = Flask(__name__)


def _available_competition_seasons(conn):
    # DESC on season_id so the most recent season sorts first -- callers that pick
    # comp_seasons[0] as a default get the current season, not the oldest one loaded.
    return conn.execute(
        """SELECT DISTINCT f.competition_id, c.display_name, f.season_id
           FROM player_season_stat_flat f JOIN competition c ON c.competition_id = f.competition_id
           ORDER BY c.display_name, f.season_id DESC"""
    ).fetchall()


def _players_for_datalist(conn, competition_id, season_id):
    # Only players with real minutes -- Transfermarkt-only squad/loan entries (market value but
    # no on-pitch data) exist in player_season_stat_flat but generate_report() correctly refuses
    # to render a report for them, so they shouldn't be offered as if they were selectable.
    return conn.execute(
        """SELECT DISTINCT p.canonical_name, p.last_team_hint
           FROM player p JOIN player_season_stat_flat f ON f.player_id = p.player_id
           WHERE f.competition_id = ? AND f.season_id = ? AND f.minutes IS NOT NULL
           ORDER BY p.canonical_name""",
        (competition_id, season_id),
    ).fetchall()


def _source_links(conn, player_id: int, canonical_name: str) -> list[dict]:
    """Deep links back to the original data source for this player, so the underlying
    numbers can always be checked against the live, up-to-date source page."""
    refs = {r["source"]: r["source_player_id"] for r in conn.execute(
        "SELECT source, source_player_id FROM player_source_ref WHERE player_id = ?", (player_id,)
    ).fetchall()}

    links = []
    if "understat" in refs:
        links.append({"label": "Understat", "url": f"https://understat.com/player/{refs['understat']}"})
    if "transfermarkt" in refs:
        links.append({"label": "Transfermarkt", "url": f"https://www.transfermarkt.com/-/profil/spieler/{refs['transfermarkt']}"})
    if "fbref" in refs:
        # FBref's own player-page ID isn't captured by our current ingestion (only a
        # name+team composite key is), so this links to FBref's search rather than a
        # direct profile page until that's fixed.
        from urllib.parse import quote
        links.append({"label": "FBref (search)", "url": f"https://fbref.com/en/search/search.fcgi?search={quote(canonical_name)}"})
    return links


def _resolve_player_id_by_name(conn, competition_id: str, season_id: str, name: str):
    row = conn.execute(
        """SELECT p.player_id FROM player p JOIN player_season_stat_flat f ON f.player_id = p.player_id
           WHERE f.competition_id = ? AND f.season_id = ? AND f.minutes IS NOT NULL AND p.canonical_name = ?""",
        (competition_id, season_id, name),
    ).fetchone()
    if row:
        return row["player_id"]
    row = conn.execute(
        """SELECT p.player_id FROM player p JOIN player_season_stat_flat f ON f.player_id = p.player_id
           WHERE f.competition_id = ? AND f.season_id = ? AND f.minutes IS NOT NULL AND p.canonical_name LIKE ?
           LIMIT 1""",
        (competition_id, season_id, f"%{name}%"),
    ).fetchone()
    return row["player_id"] if row else None


def _summary_stats(conn, competition_id, season_id):
    if not competition_id:
        return {}
    row = conn.execute(
        """SELECT COUNT(*) as player_count, SUM(goals) as total_goals, MAX(market_value_eur) as top_value
           FROM player_season_stat_flat WHERE competition_id = ? AND season_id = ? AND minutes IS NOT NULL""",
        (competition_id, season_id),
    ).fetchone()
    source_count = conn.execute("SELECT COUNT(DISTINCT source) as c FROM stats_snapshot").fetchone()["c"]
    return {
        "player_count": row["player_count"],
        "total_goals": row["total_goals"],
        "top_value_m": round(row["top_value"] / 1_000_000, 1) if row["top_value"] else None,
        "source_count": source_count,
    }


@app.route("/")
def index():
    conn = get_connection()
    comp_seasons = _available_competition_seasons(conn)
    default = comp_seasons[0] if comp_seasons else None
    players = _players_for_datalist(conn, default["competition_id"], default["season_id"]) if default else []
    summary = _summary_stats(conn, default["competition_id"] if default else None, default["season_id"] if default else None)
    conn.close()
    return render_template(
        "index.html", comp_seasons=comp_seasons, players=players, default=default, summary=summary, active_page="home"
    )


@app.route("/players")
def players_list():
    conn = get_connection()
    comp_seasons = _available_competition_seasons(conn)
    default = comp_seasons[0] if comp_seasons else None
    rows = []
    if default:
        rows = conn.execute(
            """SELECT p.player_id, p.canonical_name, p.last_team_hint, p.primary_position,
                      f.minutes, f.goals, f.assists, f.market_value_eur
               FROM player p JOIN player_season_stat_flat f ON f.player_id = p.player_id
               WHERE f.competition_id = ? AND f.season_id = ? AND f.minutes IS NOT NULL
               ORDER BY f.minutes DESC""",
            (default["competition_id"], default["season_id"]),
        ).fetchall()
    conn.close()
    return render_template(
        "players.html",
        players=rows,
        competition_id=default["competition_id"] if default else "",
        season_id=default["season_id"] if default else "",
        competition_name=default["display_name"] if default else "",
        active_page="players",
    )


@app.route("/search")
def search():
    player_query = request.args.get("player", "").strip()
    competition_id = request.args.get("competition", "")
    season_id = request.args.get("season", "")

    conn = get_connection()
    matches = conn.execute(
        """SELECT DISTINCT p.player_id, p.canonical_name, p.last_team_hint
           FROM player p JOIN player_season_stat_flat f ON f.player_id = p.player_id
           WHERE f.competition_id = ? AND f.season_id = ? AND f.minutes IS NOT NULL
             AND p.canonical_name LIKE ?
           ORDER BY p.canonical_name""",
        (competition_id, season_id, f"%{player_query}%"),
    ).fetchall()
    conn.close()

    if len(matches) == 1:
        return report(matches[0]["player_id"], competition_id, season_id)

    return render_template(
        "results.html",
        query=player_query,
        matches=matches,
        competition_id=competition_id,
        season_id=season_id,
    )


@app.route("/report/<int:player_id>")
def report(player_id, competition_id=None, season_id=None):
    competition_id = competition_id or request.args.get("competition")
    season_id = season_id or request.args.get("season")

    conn = get_connection()
    try:
        profile = build_player_profile(conn, player_id, competition_id, season_id)
        source_links = _source_links(conn, player_id, profile["player_name"])
        error = None
    except ValueError as exc:
        profile = None
        source_links = []
        error = str(exc)
    conn.close()

    return render_template("profile.html", profile=profile, source_links=source_links, error=error)


@app.route("/compare")
def compare():
    conn = get_connection()
    comp_seasons = _available_competition_seasons(conn)
    default = comp_seasons[0] if comp_seasons else None
    competition_id = request.args.get("competition") or (default["competition_id"] if default else "")
    season_id = request.args.get("season") or (default["season_id"] if default else "")
    name_a = request.args.get("player_a", "").strip()
    name_b = request.args.get("player_b", "").strip()
    players = _players_for_datalist(conn, competition_id, season_id) if competition_id else []

    profile_a = profile_b = None
    stat_pairs = []
    error = None
    if name_a and name_b:
        pid_a = _resolve_player_id_by_name(conn, competition_id, season_id, name_a)
        pid_b = _resolve_player_id_by_name(conn, competition_id, season_id, name_b)
        if pid_a is None or pid_b is None:
            error = "Couldn't find one or both players for this competition/season -- pick from the suggestions."
        else:
            try:
                profile_a = build_player_profile(conn, pid_a, competition_id, season_id)
                profile_b = build_player_profile(conn, pid_b, competition_id, season_id)
                stat_pairs = list(zip(profile_a["stats"], profile_b["stats"]))
            except ValueError as exc:
                error = str(exc)
    conn.close()

    return render_template(
        "compare.html",
        players=players,
        competition_id=competition_id,
        season_id=season_id,
        name_a=name_a,
        name_b=name_b,
        profile_a=profile_a,
        profile_b=profile_b,
        stat_pairs=stat_pairs,
        error=error,
        active_page="compare",
    )


def main():
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    main()
