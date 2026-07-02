from scouting_reports.reports.selectors import (
    buildup_selection,
    creativity_selection,
    defensive_selection,
    discipline_selection,
    finishing_selection,
    goalkeeping_selection,
    market_value_selection,
    ordinal,
    shot_volume_selection,
)


def test_finishing_insufficient_minutes():
    sel = finishing_selection(goals=1, npxg=1.0, npxg_percentile=0.5, minutes=100)
    assert sel.template_key == "insufficient_minutes"


def test_finishing_no_advanced_stats_still_cites_real_goals():
    sel = finishing_selection(goals=3, npxg=None, npxg_percentile=None, minutes=1000)
    assert sel.template_key == "finishing_no_advanced_stats"
    assert sel.params["goals"] == 3


def test_finishing_elite_boundary():
    sel = finishing_selection(goals=20, npxg=18.0, npxg_percentile=0.90, minutes=2000)
    assert sel.template_key == "finishing_elite"
    assert sel.params["npxg"] == 18.0


def test_finishing_below_average():
    sel = finishing_selection(goals=1, npxg=1.0, npxg_percentile=0.10, minutes=2000)
    assert sel.template_key == "finishing_below_average"


def test_every_finishing_branch_backed_by_real_numbers():
    # Guards against fabrication: any non-"no data" branch must carry real npxg/goals params.
    for pct in (0.95, 0.75, 0.5, 0.1):
        sel = finishing_selection(goals=5, npxg=4.2, npxg_percentile=pct, minutes=1500)
        assert sel.params["npxg"] == 4.2
        assert sel.params["goals"] == 5


def test_creativity_elite():
    sel = creativity_selection(assists=10, xa=9.0, xa_percentile=0.95, minutes=2000)
    assert sel.template_key == "creativity_elite"


def test_creativity_no_advanced_stats_defaults_missing_assists_to_zero():
    sel = creativity_selection(assists=None, xa=None, xa_percentile=None, minutes=1000)
    assert sel.params["assists"] == 0


def test_market_value_known():
    sel = market_value_selection(25_000_000)
    assert sel.template_key == "market_value_known"
    assert sel.params["value_millions"] == 25.0


def test_market_value_unknown():
    sel = market_value_selection(None)
    assert sel.template_key == "market_value_unknown"
    assert sel.params == {}


def test_ordinal_suffixes():
    assert ordinal(1) == "1st"
    assert ordinal(2) == "2nd"
    assert ordinal(3) == "3rd"
    assert ordinal(4) == "4th"
    assert ordinal(11) == "11th"
    assert ordinal(12) == "12th"
    assert ordinal(13) == "13th"
    assert ordinal(21) == "21st"
    assert ordinal(33) == "33rd"
    assert ordinal(100) == "100th"


def test_defensive_selection_insufficient_minutes():
    sel = defensive_selection(tackles_won=5, interceptions=3, combined_percentile=0.5, minutes=100)
    assert sel.template_key == "insufficient_minutes"


def test_defensive_selection_elite():
    sel = defensive_selection(tackles_won=20, interceptions=15, combined_percentile=0.95, minutes=2000)
    assert sel.template_key == "defensive_elite"
    assert sel.params["tackles_won"] == 20
    assert sel.params["interceptions"] == 15


def test_defensive_selection_no_advanced_stats():
    sel = defensive_selection(tackles_won=None, interceptions=None, combined_percentile=None, minutes=2000)
    assert sel.template_key == "defensive_no_advanced_stats"


def test_shot_volume_computes_real_accuracy_percentage():
    sel = shot_volume_selection(shots=10, shots_on_target=4, sot_percentile=0.6, minutes=2000)
    assert sel.params["accuracy"] == 40


def test_shot_volume_zero_shots_does_not_divide_by_zero():
    sel = shot_volume_selection(shots=0, shots_on_target=0, sot_percentile=None, minutes=2000)
    assert sel.params["accuracy"] == 0


def test_discipline_known_cites_real_numbers():
    sel = discipline_selection(fouls_committed=8, fouls_drawn=12, minutes=2000)
    assert sel.template_key == "discipline_known"
    assert sel.params == {"fouls_committed": 8, "fouls_drawn": 12}


def test_buildup_no_advanced_stats_still_cites_key_passes():
    sel = buildup_selection(xg_chain=None, xg_buildup=None, key_passes=7, xg_chain_percentile=None, minutes=2000)
    assert sel.template_key == "buildup_no_advanced_stats"
    assert sel.params["key_passes"] == 7


def test_buildup_elite():
    sel = buildup_selection(xg_chain=30.0, xg_buildup=20.0, key_passes=50, xg_chain_percentile=0.95, minutes=2000)
    assert sel.template_key == "buildup_elite"


def test_goalkeeping_known_cites_real_numbers():
    sel = goalkeeping_selection(save_pct=71.7, clean_sheet_pct=34.2, goals_against_90=0.89, minutes=3000)
    assert sel.template_key == "goalkeeping_known"
    assert sel.params["save_pct"] == 71.7


def test_goalkeeping_insufficient_minutes():
    sel = goalkeeping_selection(save_pct=71.7, clean_sheet_pct=34.2, goals_against_90=0.89, minutes=50)
    assert sel.template_key == "insufficient_minutes"
