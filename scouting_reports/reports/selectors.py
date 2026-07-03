"""Deterministic sentence selection for scouting reports.

Every function here branches purely on computed thresholds and returns a template
key plus the real numbers to interpolate into it -- never free text. This guarantees
every sentence in a generated report traces back to an actual computed stat; there is
no code path that emits a claim not backed by a number in player_season_stat_flat.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Selection:
    template_key: str
    params: dict


def ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def finishing_selection(goals: Optional[int], npxg: Optional[float], npxg_percentile: Optional[float], minutes: Optional[int]) -> Selection:
    if minutes is None or minutes < 450:
        return Selection("insufficient_minutes", {})
    if npxg is None or npxg_percentile is None:
        return Selection("finishing_no_advanced_stats", {"goals": goals or 0})
    pct = round(npxg_percentile * 100)
    if npxg_percentile >= 0.90:
        return Selection("finishing_elite", {"pct": ordinal(pct), "goals": goals, "npxg": round(npxg, 1)})
    if npxg_percentile >= 0.70:
        return Selection("finishing_above_average", {"pct": ordinal(pct), "goals": goals, "npxg": round(npxg, 1)})
    if npxg_percentile >= 0.30:
        return Selection("finishing_average", {"pct": ordinal(pct), "goals": goals, "npxg": round(npxg, 1)})
    return Selection("finishing_below_average", {"pct": ordinal(pct), "goals": goals, "npxg": round(npxg, 1)})


def creativity_selection(assists: Optional[int], xa: Optional[float], xa_percentile: Optional[float], minutes: Optional[int]) -> Selection:
    if minutes is None or minutes < 450:
        return Selection("insufficient_minutes", {})
    if xa is None or xa_percentile is None:
        return Selection("creativity_no_advanced_stats", {"assists": assists or 0})
    pct = round(xa_percentile * 100)
    if xa_percentile >= 0.90:
        return Selection("creativity_elite", {"pct": ordinal(pct), "assists": assists, "xa": round(xa, 1)})
    if xa_percentile >= 0.70:
        return Selection("creativity_above_average", {"pct": ordinal(pct), "assists": assists, "xa": round(xa, 1)})
    if xa_percentile >= 0.30:
        return Selection("creativity_average", {"pct": ordinal(pct), "assists": assists, "xa": round(xa, 1)})
    return Selection("creativity_below_average", {"pct": ordinal(pct), "assists": assists, "xa": round(xa, 1)})


def market_value_selection(market_value_eur: Optional[int]) -> Selection:
    if market_value_eur is None:
        return Selection("market_value_unknown", {})
    return Selection("market_value_known", {"value_millions": round(market_value_eur / 1_000_000, 1)})


def _tier(pct: float) -> str:
    if pct >= 0.90:
        return "elite"
    if pct >= 0.70:
        return "above_average"
    if pct >= 0.30:
        return "average"
    return "below_average"


def defensive_selection(
    tackles_won: Optional[int], interceptions: Optional[int], combined_percentile: Optional[float], minutes: Optional[int]
) -> Selection:
    if minutes is None or minutes < 450:
        return Selection("insufficient_minutes", {})
    if tackles_won is None or interceptions is None or combined_percentile is None:
        return Selection("defensive_no_advanced_stats", {})
    pct = round(combined_percentile * 100)
    return Selection(f"defensive_{_tier(combined_percentile)}", {"pct": ordinal(pct), "tackles_won": tackles_won, "interceptions": interceptions})


def shot_volume_selection(
    shots: Optional[int], shots_on_target: Optional[int], sot_percentile: Optional[float], minutes: Optional[int]
) -> Selection:
    if minutes is None or minutes < 450:
        return Selection("insufficient_minutes", {})
    if shots is None or shots_on_target is None:
        return Selection("shot_volume_no_advanced_stats", {})
    sot_pct_of_shots = round((shots_on_target / shots) * 100) if shots else 0
    if sot_percentile is None:
        return Selection("shot_volume_known", {"shots": shots, "shots_on_target": shots_on_target, "accuracy": sot_pct_of_shots})
    return Selection(
        f"shot_volume_{_tier(sot_percentile)}",
        {"pct": ordinal(round(sot_percentile * 100)), "shots": shots, "shots_on_target": shots_on_target, "accuracy": sot_pct_of_shots},
    )


def discipline_selection(fouls_committed: Optional[int], fouls_drawn: Optional[int], minutes: Optional[int]) -> Selection:
    if minutes is None or minutes < 450:
        return Selection("insufficient_minutes", {})
    if fouls_committed is None or fouls_drawn is None:
        return Selection("discipline_no_advanced_stats", {})
    return Selection("discipline_known", {"fouls_committed": fouls_committed, "fouls_drawn": fouls_drawn})


def buildup_selection(
    xg_chain: Optional[float], xg_buildup: Optional[float], key_passes: Optional[int],
    xg_chain_percentile: Optional[float], minutes: Optional[int],
) -> Selection:
    if minutes is None or minutes < 450:
        return Selection("insufficient_minutes", {})
    if xg_chain is None or xg_buildup is None or xg_chain_percentile is None:
        return Selection("buildup_no_advanced_stats", {"key_passes": key_passes or 0})
    return Selection(
        f"buildup_{_tier(xg_chain_percentile)}",
        {"pct": ordinal(round(xg_chain_percentile * 100)), "xg_chain": round(xg_chain, 1), "xg_buildup": round(xg_buildup, 1), "key_passes": key_passes or 0},
    )


def goalkeeping_selection(
    save_pct: Optional[float], clean_sheet_pct: Optional[float], goals_against_90: Optional[float], minutes: Optional[int]
) -> Selection:
    if minutes is None or minutes < 450:
        return Selection("insufficient_minutes", {})
    if save_pct is None or clean_sheet_pct is None or goals_against_90 is None:
        return Selection("goalkeeping_no_advanced_stats", {})
    return Selection(
        "goalkeeping_known",
        {"save_pct": round(save_pct, 1), "clean_sheet_pct": round(clean_sheet_pct, 1), "goals_against_90": round(goals_against_90, 2)},
    )
