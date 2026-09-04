import pytest
from contextfidelity.design import build, expand, validate
from contextfidelity.rules import ARMS, placebo_balanced, rung


def test_design_validates():
    assert validate(build()) == []


def test_every_rung_has_a_floor_control():
    plan = build()
    cells = [c for ph in plan.values() for c in ph.cells]
    for rid in ("L0", "L1", "L2", "L3"):
        assert any(c.rung == rid and "FLOOR" in c.cell_id for c in cells), rid


def test_phase3_includes_placebo_arm():
    """Without it a positive re-surfacing result cannot separate rule content
    from attention interruption."""
    assert any(c.arm == "A4" for c in build()["phase3"].cells)


def test_phase1_has_no_config_baseline():
    assert any(not c.config for c in build()["phase1"].cells)


def test_phase3_target_placeholder_requires_resolution():
    with pytest.raises(ValueError):
        list(expand(build()["phase3"]))
    assert list(expand(build()["phase3"], resolved_rung="L2"))


def test_run_ids_unique():
    runs = [r.run_id for r in expand(build(replicates=3, floor_replicates=2)["phase1"])]
    assert len(runs) == len(set(runs))


def test_placebo_length_matched_at_every_rung():
    for rid in ("L0", "L1", "L2", "L3"):
        assert placebo_balanced(rung(rid)), rid


def test_only_a1_omits_resurfacing():
    assert not ARMS["A1"].resurfaces
    assert all(ARMS[a].resurfaces for a in ("A2", "A3", "A4"))
