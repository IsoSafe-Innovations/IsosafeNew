from app.rules.zones import crossed_line, point_in_polygon, zones_containing

SQUARE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]


def test_point_inside():
    assert point_in_polygon((0.5, 0.5), SQUARE)


def test_point_outside():
    assert not point_in_polygon((0.1, 0.5), SQUARE)
    assert not point_in_polygon((0.9, 0.9), SQUARE)


def test_degenerate_polygon():
    assert not point_in_polygon((0.5, 0.5), [[0, 0], [1, 1]])


def test_zones_containing():
    zones = [
        {"id": "a", "polygon": SQUARE},
        {"id": "b", "polygon": [[0.0, 0.0], [0.3, 0.0], [0.3, 0.3], [0.0, 0.3]]},
        {"id": "line-only", "line": [[0, 0.5], [1, 0.5]]},
    ]
    assert zones_containing((0.25, 0.25), zones) == ["a", "b"]
    assert zones_containing((0.5, 0.5), zones) == ["a"]
    assert zones_containing((0.95, 0.95), zones) == []


def test_line_crossing():
    line = [[0.0, 0.5], [1.0, 0.5]]
    assert crossed_line((0.5, 0.4), (0.5, 0.6), line)  # crosses downward
    assert crossed_line((0.5, 0.6), (0.5, 0.4), line)  # crosses upward
    assert not crossed_line((0.5, 0.3), (0.5, 0.45), line)  # same side
    # crossing far outside the segment bounds
    assert not crossed_line((2.0, 0.4), (2.0, 0.6), line)
