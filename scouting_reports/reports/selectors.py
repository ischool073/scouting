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


def finishing_selection(goals: Optional[int], npxg: Optional[float], npxg_percentile: Optional[float], minutes: Optional[int]) -> Selection:
    if minutes is None or minutes < 450:
        return Selection("insufficient_minutes", {})
    if npxg is None or npxg_percentile is None:
        return Selection("finishing_no_advanced_stats", {"goals": goals or 0})
    pct = round(npxg_percentile * 100)
    if npxg_percentile >= 0.90:
        return Selection("finishing_elite", {"pct": pct, "goals": goals, "npxg": round(npxg, 1)})
    if npxg_percentile >= 0.70:
        return Selection("finishing_above_average", {"pct": pct, "goals": goals, "npxg": round(npxg, 1)})
    if npxg_percentile >= 0.30:
        return Selection("finishing_average", {"pct": pct, "goals": goals, "npxg": round(npxg, 1)})
    return Selection("finishing_below_average", {"pct": pct, "goals": goals, "npxg": round(npxg, 1)})


def creativity_selection(assists: Optional[int], xa: Optional[float], xa_percentile: Optional[float], minutes: Optional[int]) -> Selection:
    if minutes is None or minutes < 450:
        return Selection("insufficient_minutes", {})
    if xa is None or xa_percentile is None:
        return Selection("creativity_no_advanced_stats", {"assists": assists or 0})
    pct = round(xa_percentile * 100)
    if xa_percentile >= 0.90:
        return Selection("creativity_elite", {"pct": pct, "assists": assists, "xa": round(xa, 1)})
    if xa_percentile >= 0.70:
        return Selection("creativity_above_average", {"pct": pct, "assists": assists, "xa": round(xa, 1)})
    if xa_percentile >= 0.30:
        return Selection("creativity_average", {"pct": pct, "assists": assists, "xa": round(xa, 1)})
    return Selection("creativity_below_average", {"pct": pct, "assists": assists, "xa": round(xa, 1)})


def market_value_selection(market_value_eur: Optional[int]) -> Selection:
    if market_value_eur is None:
        return Selection("market_value_unknown", {})
    return Selection("market_value_known", {"value_millions": round(market_value_eur / 1_000_000, 1)})
