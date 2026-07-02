import click

from scouting_reports.config import ensure_season, load_leagues, sync_competitions
from scouting_reports.db.connection import get_connection, init_db
from scouting_reports.ingest.fbref_top import FBrefTopIngestor
from scouting_reports.ingest.transfermarkt_bulk import TransfermarktBulkIngestor
from scouting_reports.ingest.understat_ingest import UnderstatIngestor
from scouting_reports.reports.generator import generate_report
from scouting_reports.stats.aggregate import flatten_player_season_stats


@click.group()
def cli():
    pass


@cli.command()
def init():
    """Create/upgrade the SQLite schema and sync config/leagues.yaml into it."""
    init_db()
    conn = get_connection()
    sync_competitions(conn)
    conn.close()
    click.echo("DB initialized and competitions synced.")


@cli.command()
@click.option("--competition", required=True, help="Competition id from config/leagues.yaml, e.g. ENG1")
@click.option("--season", required=True, help="Season id, e.g. 2024-2025")
@click.option("--source", type=click.Choice(["fbref", "understat", "transfermarkt", "all"]), default="all")
def ingest(competition, season, source):
    """Run ingestion for one competition/season."""
    conn = get_connection()
    ensure_season(conn, season)
    leagues = {league["id"]: league for league in load_leagues()}
    league = leagues[competition]

    if source in ("fbref", "all") and league["fbref_source"] == "soccerdata":
        ingestor = FBrefTopIngestor(fbref_key=league["fbref_key"])
        rows = ingestor.run(conn, competition, season)
        click.echo(f"fbref: wrote {rows} stat rows")

    if source in ("understat", "all") and league["understat_key"]:
        ingestor = UnderstatIngestor(understat_key=league["understat_key"])
        rows = ingestor.run(conn, competition, season)
        click.echo(f"understat: wrote {rows} stat rows")

    if source in ("transfermarkt", "all") and league["transfermarkt_competition_id"]:
        ingestor = TransfermarktBulkIngestor(transfermarkt_competition_id=league["transfermarkt_competition_id"])
        rows = ingestor.run(conn, competition, season)
        click.echo(f"transfermarkt: wrote {rows} stat rows")

    flat_rows = flatten_player_season_stats(conn, competition, season)
    click.echo(f"flattened {flat_rows} player-season rows")

    conn.close()


@cli.command()
@click.option("--player", required=True, help="Player name (substring match, case-insensitive)")
@click.option("--competition", required=True, help="Competition id, e.g. ENG1")
@click.option("--season", required=True, help="Season id, e.g. 2024-2025")
def report(player, competition, season):
    """Generate and print a scouting report for a player by name."""
    conn = get_connection()
    matches = conn.execute(
        "SELECT player_id, canonical_name, last_team_hint FROM player WHERE canonical_name LIKE ?",
        (f"%{player}%",),
    ).fetchall()

    if not matches:
        click.echo(f"No player found matching '{player}'.")
        return
    if len(matches) > 1:
        click.echo(f"Multiple players match '{player}', pick one and re-run with an exact/narrower name:")
        for m in matches:
            click.echo(f"  - {m['canonical_name']} ({m['last_team_hint']})")
        return

    try:
        click.echo(generate_report(conn, matches[0]["player_id"], competition, season))
    except ValueError as exc:
        click.echo(str(exc))
    finally:
        conn.close()


if __name__ == "__main__":
    cli()
