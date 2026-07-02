from scouting_reports.reports.selectors import (
    creativity_selection,
    finishing_selection,
    market_value_selection,
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
