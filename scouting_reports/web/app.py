"""A small local web app: search a player by name, view their generated
scouting report in the browser instead of the terminal.

Run with:
    .venv\\Scripts\\python.exe -m scouting_reports.web.app
Then open http://127.0.0.1:5000 in a browser.
"""
import markdown as markdown_lib
from flask import Flask, render_template, request

from scouting_reports.db.connection import get_connection
from scouting_reports.reports.generator import generate_report

app = Flask(__name__)


def _available_competition_seasons(conn):
    return conn.execute(
        """SELECT DISTINCT f.competition_id, c.display_name, f.season_id
           FROM player_season_stat_flat f JOIN competition c ON c.competition_id = f.competition_id
           ORDER BY c.display_name, f.season_id"""
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


@app.route("/")
def index():
    conn = get_connection()
    comp_seasons = _available_competition_seasons(conn)
    default = comp_seasons[0] if comp_seasons else None
    players = _players_for_datalist(conn, default["competition_id"], default["season_id"]) if default else []
    conn.close()
    return render_template("index.html", comp_seasons=comp_seasons, players=players, default=default)


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
        report_markdown = generate_report(conn, player_id, competition_id, season_id)
        error = None
    except ValueError as exc:
        report_markdown = None
        error = str(exc)
    conn.close()

    report_html = markdown_lib.markdown(report_markdown) if report_markdown else None
    return render_template("report.html", report_html=report_html, error=error)


def main():
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    main()
