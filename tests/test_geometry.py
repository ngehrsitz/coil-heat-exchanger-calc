"""Tests for RegisterGeometry.validate() cross-field consistency checks."""

from physics.geometry import RegisterGeometry, derive_geometry


def test_default_geometry_is_valid():
    assert RegisterGeometry().validate() == []


def test_tube_wall_at_least_half_od_flagged():
    # tube_id = tube_od − 2·tube_wall would be ≤ 0.
    errors = RegisterGeometry(tube_od=0.010, tube_wall=0.006).validate()
    fields = [field for field, _ in errors]
    assert "tube_wall" in fields
    assert all(isinstance(msg, str) and msg for _, msg in errors)


def test_tube_wall_exactly_half_od_flagged():
    errors = RegisterGeometry(tube_od=0.010, tube_wall=0.005).validate()
    assert any(field == "tube_wall" for field, _ in errors)


def test_fin_thickness_at_least_pitch_flagged():
    # fin_pitch_clear = fin_pitch − fin_thickness would be ≤ 0.
    errors = RegisterGeometry(fin_pitch=0.002, fin_thickness=0.002).validate()
    assert any(field == "fin_thickness" for field, _ in errors)


def test_multiple_violations_reported_together():
    errors = RegisterGeometry(
        tube_od=0.010,
        tube_wall=0.006,
        fin_pitch=0.002,
        fin_thickness=0.003,
    ).validate()
    fields = {field for field, _ in errors}
    assert fields == {"tube_wall", "fin_thickness"}


def test_tube_od_must_be_smaller_than_hole_pitch():
    errors = RegisterGeometry(tube_od=0.010, hole_pitch=0.008).validate()
    assert any(field == "hole_pitch" for field, _ in errors)


def test_tube_holes_must_fit_pitch_cell():
    errors = RegisterGeometry(tube_od=0.020, hole_pitch=0.021, row_pitch=0.010).validate()
    assert any(field == "row_pitch" for field, _ in errors)


def test_blockage_must_leave_positive_free_flow_area():
    errors = RegisterGeometry(
        tube_od=0.010,
        hole_pitch=0.010,
        fin_pitch=0.001,
        fin_thickness=0.0009,
    ).validate()
    assert any(field == "tube_od" for field, _ in errors)


def test_derive_geometry_rejects_invalid_layout():
    g = RegisterGeometry(tube_od=0.010, hole_pitch=0.008)
    try:
        derive_geometry(g)
    except ValueError as exc:
        assert "Invalid register geometry" in str(exc)
    else:  # pragma: no cover - assertion failure path
        raise AssertionError("derive_geometry accepted an invalid layout")


def test_valid_geometry_derives_positive_quantities():
    # A geometry that passes validate() must not produce a degenerate coil.
    g = RegisterGeometry()
    assert g.validate() == []
    d = derive_geometry(g)
    assert d.tube_id > 0.0
    assert d.fin_area > 0.0
    assert d.bare_area > 0.0
    assert d.total_ext_area > 0.0
    assert d.frontal_area > 0.0
    assert d.min_free_flow_area > 0.0
