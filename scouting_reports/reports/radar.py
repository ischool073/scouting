"""Renders a percentile radar chart as inline SVG -- the "iconic StatsBomb radar"
(their own description) reimagined with our data: one axis per key metric, each
scaled to the player's percentile (0-1) within their competition/position cohort.

Missing percentiles (no data for that axis) are plotted at the center rather than
skipped, so a gap in the shape is visually honest about missing data instead of
silently stretching the polygon across fewer axes.
"""
import math

SIZE = 280
CENTER = SIZE / 2
RADIUS = SIZE / 2 - 56
GRID_RINGS = (0.25, 0.5, 0.75, 1.0)


def _point(angle: float, r: float) -> tuple[float, float]:
    return CENTER + r * math.cos(angle), CENTER + r * math.sin(angle)


def build_radar_svg(axes: list[dict]) -> str:
    """axes: list of {"label": str, "percentile": float|None}"""
    n = len(axes)
    if n < 3:
        return ""  # a radar needs at least 3 axes to mean anything

    angle_step = 2 * math.pi / n
    angles = [-math.pi / 2 + i * angle_step for i in range(n)]

    grid_polygons = []
    for ring in GRID_RINGS:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (_point(a, RADIUS * ring) for a in angles))
        grid_polygons.append(f'<polygon points="{pts}" fill="none" stroke="#2a2a2a" stroke-width="1"/>')

    spokes = []
    labels = []
    for angle, axis in zip(angles, axes):
        x, y = _point(angle, RADIUS)
        spokes.append(f'<line x1="{CENTER}" y1="{CENTER}" x2="{x:.1f}" y2="{y:.1f}" stroke="#2a2a2a" stroke-width="1"/>')
        lx, ly = _point(angle, RADIUS + 32)
        anchor = "middle"
        if lx < CENTER - 5:
            anchor = "end"
        elif lx > CENTER + 5:
            anchor = "start"
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" fill="#9a9a9a" font-size="11" text-anchor="{anchor}" '
            f'font-family="-apple-system, Arial, sans-serif" font-weight="600">{axis["label"].upper()}</text>'
        )

    data_points = []
    dots = []
    for angle, axis in zip(angles, axes):
        pct = axis["percentile"] or 0
        x, y = _point(angle, RADIUS * pct)
        data_points.append((x, y))
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#ccff00"/>')

    poly_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in data_points)
    data_polygon = f'<polygon points="{poly_pts}" fill="#ccff00" fill-opacity="0.25" stroke="#ccff00" stroke-width="2"/>'

    return (
        f'<svg viewBox="0 0 {SIZE} {SIZE}" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">'
        + "".join(grid_polygons)
        + "".join(spokes)
        + data_polygon
        + "".join(dots)
        + "".join(labels)
        + "</svg>"
    )
