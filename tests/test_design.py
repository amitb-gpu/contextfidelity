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


def test_multi_task_pool_is_labelled_reconstructed():
    """The publication gives task descriptions, not verbatim prompts.

    If these are ever silently promoted to 'the original prompts', the study
    would be claiming an exactness it does not have.
    """
    from contextfidelity.rules import MULTI_TASKS

    for t in MULTI_TASKS:
        assert "RECONSTRUCTED" in t.description, t.id


def test_floor_control_is_not_attributed_to_the_original():
    """F1 is ours. It must never be reported inside the replicated task pool."""
    from contextfidelity.rules import FLOOR_TASKS, MULTI_TASKS

    for t in FLOOR_TASKS:
        assert "NOT part of McMillan" in t.description, t.id
    assert not any(t.id.startswith("F") for t in MULTI_TASKS)


def test_rq1_task_pool_matches_the_published_multi_function_tasks():
    from contextfidelity.rules import MULTI_TASKS

    assert [t.id for t in MULTI_TASKS] == ["T3", "T4", "T5"]


def test_task_paths_follow_the_baseline_app_router_layout():
    """The baseline is locale-segmented; a bare src/app/dashboard path does not
    exist there, and a task targeting one would fail for reasons unrelated to
    instruction adherence."""
    from contextfidelity.rules import ALL_TASKS

    for t in ALL_TASKS:
        if "src/app/" in t.prompt:
            assert "src/app/[locale]/" in t.prompt, t.id
        assert "src/lib/" not in t.prompt, t.id
