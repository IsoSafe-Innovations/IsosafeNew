"""Zone geometry. Zones are polygons of normalized (0..1) coordinates stored in
cameras.zones JSONB:

  {"id": "stockroom-entrance", "name": "Stockroom", "polygon": [[x, y], ...]}

Line zones (for line_crossing rules) use a 2-point "line" instead of "polygon".
"""


def point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    x, y = point
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def zones_containing(point: tuple[float, float], zones: list[dict]) -> list[str]:
    hits = []
    for zone in zones:
        poly = zone.get("polygon")
        if poly and point_in_polygon(point, poly):
            hits.append(zone["id"])
    return hits


def _side_of_line(point: tuple[float, float], line: list[list[float]]) -> float:
    (x1, y1), (x2, y2) = line[0], line[1]
    return (x2 - x1) * (point[1] - y1) - (y2 - y1) * (point[0] - x1)


def crossed_line(prev: tuple[float, float], curr: tuple[float, float],
                 line: list[list[float]]) -> bool:
    """True when the segment prev->curr crosses the zone line."""
    a = _side_of_line(prev, line)
    b = _side_of_line(curr, line)
    if a == 0 or b == 0:
        return False
    if (a > 0) == (b > 0):
        return False
    # Also require the crossing point to be within the line segment bounds (with margin)
    (x1, y1), (x2, y2) = line[0], line[1]
    min_x, max_x = min(x1, x2) - 0.05, max(x1, x2) + 0.05
    min_y, max_y = min(y1, y2) - 0.05, max(y1, y2) + 0.05
    mx, my = (prev[0] + curr[0]) / 2, (prev[1] + curr[1]) / 2
    return min_x <= mx <= max_x and min_y <= my <= max_y
