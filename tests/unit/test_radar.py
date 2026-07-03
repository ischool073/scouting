from scouting_reports.reports.radar import build_radar_svg


def test_radar_requires_at_least_three_axes():
    assert build_radar_svg([{"label": "A", "percentile": 0.5}, {"label": "B", "percentile": 0.5}]) == ""


def test_radar_renders_svg_with_expected_element_counts():
    axes = [
        {"label": "Finishing", "percentile": 0.9},
        {"label": "Creativity", "percentile": 0.5},
        {"label": "Shooting", "percentile": 0.3},
        {"label": "Defending", "percentile": 0.1},
        {"label": "Build-up", "percentile": 0.7},
    ]
    svg = build_radar_svg(axes)
    assert svg.startswith("<svg")
    assert svg.count("<circle") == 5  # one data-point dot per axis
    assert svg.count("<text") == 5  # one label per axis
    for axis in axes:
        assert axis["label"].upper() in svg


def test_radar_treats_missing_percentile_as_zero_not_a_crash():
    axes = [
        {"label": "A", "percentile": None},
        {"label": "B", "percentile": 0.8},
        {"label": "C", "percentile": 0.5},
    ]
    svg = build_radar_svg(axes)
    assert svg.startswith("<svg")
