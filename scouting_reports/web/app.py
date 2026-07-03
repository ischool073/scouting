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


def _available_competitions(conn):
    return conn.execute(
        """SELECT DISTINCT f.competition_id, c.display_name
           FROM player_season_stat_flat f JOIN competition c ON c.competition_id = f.competition_id
           ORDER BY c.display_name"""
    ).fetchall()


def _available_seasons(conn, competition_id):
    return conn.execute(
        """SELECT DISTINCT season_id FROM player_season_stat_flat WHERE competition_id = ?
           ORDER BY season_id DESC""",
        (competition_id,),
    ).fetchall()


def _default_competition_season(conn):
    comp_seasons = _available_competition_seasons(conn)
    return comp_seasons[0] if comp_seasons else None


def _competition_badge(conn, competition_id: str, season_id: str):
    """A short-code badge (e.g. "PL") for the top-right corner -- text-based rather than
    hotlinking an official league crest, so it doesn't depend on an external image source
    or reproduce a trademarked logo."""
    if not competition_id or not season_id:
        return None
    row = conn.execute("SELECT display_name FROM competition WHERE competition_id = ?", (competition_id,)).fetchone()
    if not row:
        return None
    words = row["display_name"].split()
    code = "".join(w[0] for w in words[:3]).upper()
    return {"code": code, "name": row["display_name"], "season": season_id}


def _player_available_seasons(conn, player_id: int):
    """Every (competition, season) this specific player has real stats for, so the profile
    page can offer a season switcher scoped to just that player's own data."""
    return conn.execute(
        """SELECT DISTINCT f.competition_id, c.display_name, f.season_id
           FROM player_season_stat_flat f JOIN competition c ON c.competition_id = f.competition_id
           WHERE f.player_id = ? AND f.minutes IS NOT NULL
           ORDER BY f.season_id DESC""",
        (player_id,),
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
    default = _default_competition_season(conn)
    players = _players_for_datalist(conn, default["competition_id"], default["season_id"]) if default else []
    summary = _summary_stats(conn, default["competition_id"] if default else None, default["season_id"] if default else None)
    conn.close()
    # No season/competition picker here by design -- the home screen is just "find a player."
    # The season is chosen per-player on their profile page instead (see report()).
    return render_template("index.html", players=players, default=default, summary=summary, active_page="home")


@app.route("/players")
def players_list():
    conn = get_connection()
    default = _default_competition_season(conn)
    competitions = _available_competitions(conn)
    competition_id = request.args.get("competition") or (default["competition_id"] if default else "")
    seasons = _available_seasons(conn, competition_id) if competition_id else []
    season_id = request.args.get("season") or (default["season_id"] if default else "")

    rows = []
    if competition_id and season_id:
        rows = conn.execute(
            """SELECT p.player_id, p.canonical_name, p.last_team_hint, p.primary_position,
                      f.minutes, f.goals, f.assists, f.market_value_eur
               FROM player p JOIN player_season_stat_flat f ON f.player_id = p.player_id
               WHERE f.competition_id = ? AND f.season_id = ? AND f.minutes IS NOT NULL
               ORDER BY f.minutes DESC""",
            (competition_id, season_id),
        ).fetchall()
    badge = _competition_badge(conn, competition_id, season_id)
    conn.close()
    return render_template(
        "players.html",
        players=rows,
        competitions=competitions,
        seasons=seasons,
        competition_id=competition_id,
        season_id=season_id,
        competition_badge=badge,
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
    available_seasons = _player_available_seasons(conn, player_id)
    if not season_id and available_seasons:
        # No season specified (e.g. reached via a stale link) -- fall back to this
        # player's own most recent season rather than a global default.
        competition_id, season_id = available_seasons[0]["competition_id"], available_seasons[0]["season_id"]

    try:
        profile = build_player_profile(conn, player_id, competition_id, season_id)
        source_links = _source_links(conn, player_id, profile["player_name"])
        error = None
    except ValueError as exc:
        profile = None
        source_links = []
        error = str(exc)
    badge = _competition_badge(conn, competition_id, season_id)
    conn.close()

    return render_template(
        "profile.html",
        profile=profile,
        source_links=source_links,
        error=error,
        player_id=player_id,
        available_seasons=available_seasons,
        current_season_id=season_id,
        competition_badge=badge,
    )


@app.route("/compare")
def compare():
    conn = get_connection()
    default = _default_competition_season(conn)
    competitions = _available_competitions(conn)
    competition_id = request.args.get("competition") or (default["competition_id"] if default else "")
    seasons = _available_seasons(conn, competition_id) if competition_id else []
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
    badge = _competition_badge(conn, competition_id, season_id)
    conn.close()

    return render_template(
        "compare.html",
        players=players,
        competitions=competitions,
        seasons=seasons,
        competition_id=competition_id,
        season_id=season_id,
        name_a=name_a,
        name_b=name_b,
        profile_a=profile_a,
        profile_b=profile_b,
        stat_pairs=stat_pairs,
        error=error,
        competition_badge=badge,
        active_page="compare",
    )


def main():
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    main()
