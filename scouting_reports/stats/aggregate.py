"""Flattens per-source stats_snapshot payloads into the query-friendly
player_season_stat_flat table that report generation actually reads.

Field provenance (given the sources currently wired up):
  minutes/goals/assists          <- FBref 'standard' stat_type (most authoritative for match counts)
  xg/xa/npxg/xg_chain/xg_buildup <- Understat
  key_passes                     <- Understat
  shots/shots_on_target          <- FBref 'shooting' stat_type
  tackles_won/interceptions/
    fouls_committed/fouls_drawn/
    crosses                      <- FBref 'misc' stat_type
  save_pct/clean_sheet_pct/
    goals_against_90             <- FBref 'keeper' stat_type (goalkeepers only)
  sofascore_rating/distance_km/sprints/top_speed_kmh/
    duels_won_pct/dribbles_won_pct/
    big_chances_created          <- SofaScore (physical/rating data no other source provides)
  market_value_eur               <- Transfermarkt bulk dataset

progressive_carries/progressive_passes stay NULL -- FBref's soccerdata reader doesn't expose
the passing/possession tables that would carry those.
"""
import json
import sqlite3


def flatten_player_season_stats(conn: sqlite3.Connection, competition_id: str, season_id: str) -> int:
    player_ids = [
        row["player_id"]
        for row in conn.execute(
            "SELECT DISTINCT player_id FROM stats_snapshot WHERE competition_id = ? AND season_id = ?",
            (competition_id, season_id),
        ).fetchall()
    ]

    rows_written = 0
    for player_id in player_ids:
        fbref = _latest_payload(conn, player_id, "fbref", "standard", competition_id, season_id)
        shooting = _latest_payload(conn, player_id, "fbref", "shooting", competition_id, season_id)
        misc = _latest_payload(conn, player_id, "fbref", "misc", competition_id, season_id)
        keeper = _latest_payload(conn, player_id, "fbref", "keeper", competition_id, season_id)
        understat = _latest_payload(conn, player_id, "understat", "understat_xg", competition_id, season_id)
        transfermarkt = _latest_payload(conn, player_id, "transfermarkt", "market_value", competition_id, season_id)
        sofascore = _latest_payload(conn, player_id, "sofascore", "sofascore_overall", competition_id, season_id)

        position = (fbref or {}).get("pos")
        if position:
            # FBref sometimes gives combo positions like "DF,MF" -- take the primary one.
            conn.execute(
                "UPDATE player SET primary_position = ? WHERE player_id = ? AND primary_position IS NULL",
                (position.split(",")[0].strip(), player_id),
            )

        if transfermarkt:
            conn.execute(
                """UPDATE player SET
                     nationality = COALESCE(nationality, ?),
                     height_cm = COALESCE(height_cm, ?),
                     preferred_foot = COALESCE(preferred_foot, ?),
                     photo_url = COALESCE(photo_url, ?),
                     contract_expires = COALESCE(contract_expires, ?),
                     international_caps = COALESCE(international_caps, ?),
                     international_goals = COALESCE(international_goals, ?)
                   WHERE player_id = ?""",
                (
                    transfermarkt.get("country_of_citizenship"),
                    transfermarkt.get("height_in_cm"),
                    transfermarkt.get("foot"),
                    transfermarkt.get("image_url"),
                    transfermarkt.get("contract_expiration_date"),
                    transfermarkt.get("international_caps"),
                    transfermarkt.get("international_goals"),
                    player_id,
                ),
            )

        minutes = (fbref or {}).get("Playing Time_Min")
        appearances = (fbref or {}).get("Playing Time_MP")
        starts = (fbref or {}).get("Playing Time_Starts")
        goals = (fbref or {}).get("Performance_Gls")
        assists = (fbref or {}).get("Performance_Ast")
        if minutes is None and understat:
            minutes = understat.get("minutes")
        if appearances is None and understat:
            appearances = understat.get("matches")
        if goals is None and understat:
            goals = understat.get("goals")
        if assists is None and understat:
            assists = understat.get("assists")

        conn.execute(
            """INSERT INTO player_season_stat_flat
               (player_id, season_id, competition_id, minutes, appearances, starts, goals, assists, xg, xa, npxg,
                progressive_carries, progressive_passes, tackles_won, interceptions,
                shots, shots_on_target, fouls_committed, fouls_drawn, crosses,
                xg_chain, xg_buildup, key_passes,
                save_pct, clean_sheet_pct, goals_against_90,
                sofascore_rating, distance_km, sprints, top_speed_kmh,
                duels_won_pct, dribbles_won_pct, big_chances_created,
                market_value_eur, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(player_id, season_id, competition_id) DO UPDATE SET
                 minutes=excluded.minutes, appearances=excluded.appearances, starts=excluded.starts,
                 goals=excluded.goals, assists=excluded.assists,
                 xg=excluded.xg, xa=excluded.xa, npxg=excluded.npxg,
                 tackles_won=excluded.tackles_won, interceptions=excluded.interceptions,
                 shots=excluded.shots, shots_on_target=excluded.shots_on_target,
                 fouls_committed=excluded.fouls_committed, fouls_drawn=excluded.fouls_drawn,
                 crosses=excluded.crosses, xg_chain=excluded.xg_chain, xg_buildup=excluded.xg_buildup,
                 key_passes=excluded.key_passes, save_pct=excluded.save_pct,
                 clean_sheet_pct=excluded.clean_sheet_pct, goals_against_90=excluded.goals_against_90,
                 sofascore_rating=excluded.sofascore_rating, distance_km=excluded.distance_km,
                 sprints=excluded.sprints, top_speed_kmh=excluded.top_speed_kmh,
                 duels_won_pct=excluded.duels_won_pct, dribbles_won_pct=excluded.dribbles_won_pct,
                 big_chances_created=excluded.big_chances_created,
                 market_value_eur=excluded.market_value_eur, updated_at=datetime('now')
            """,
            (
                player_id, season_id, competition_id,
                minutes, appearances, starts, goals, assists,
                (understat or {}).get("xg"), (understat or {}).get("xa"), (understat or {}).get("np_xg"),
                (misc or {}).get("Performance_TklW"), (misc or {}).get("Performance_Int"),
                (shooting or {}).get("Standard_Sh"), (shooting or {}).get("Standard_SoT"),
                (misc or {}).get("Performance_Fls"), (misc or {}).get("Performance_Fld"), (misc or {}).get("Performance_Crs"),
                (understat or {}).get("xg_chain"), (understat or {}).get("xg_buildup"), (understat or {}).get("key_passes"),
                (keeper or {}).get("Performance_Save%"), (keeper or {}).get("Performance_CS%"), (keeper or {}).get("Performance_GA90"),
                (sofascore or {}).get("rating"), (sofascore or {}).get("kilometersCovered"),
                (sofascore or {}).get("numberOfSprints"), (sofascore or {}).get("topSpeed"),
                (sofascore or {}).get("totalDuelsWonPercentage"), (sofascore or {}).get("successfulDribblesPercentage"),
                (sofascore or {}).get("bigChancesCreated"),
                (transfermarkt or {}).get("market_value_in_eur"),
            ),
        )
        rows_written += 1
    conn.commit()
    return rows_written


def _latest_payload(conn, player_id, source, stat_type, competition_id, season_id):
    row = conn.execute(
        """SELECT payload_json FROM stats_snapshot
           WHERE player_id = ? AND source = ? AND stat_type = ? AND competition_id = ? AND season_id = ?
           ORDER BY fetched_at DESC LIMIT 1""",
        (player_id, source, stat_type, competition_id, season_id),
    ).fetchone()
    return json.loads(row["payload_json"]) if row else None
