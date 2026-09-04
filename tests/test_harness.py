import json
from contextfidelity.harness import ReplayHarness, ReplaySpec, parse_stream


def test_replay_respects_no_config_zero_floor():
    """Without a configuration file the rule was never stated; the marker must
    never appear, or the outcome measures something other than instruction
    following."""
    h = ReplayHarness(ReplaySpec(config_present=False, seed=1), "L0")
    from contextfidelity.rules import LADDER
    from contextfidelity.scoring import score_run, summarize
    res = h.run(".", "task")
    assert summarize(score_run(res.changed_files, LADDER["L0"]))["atomic_rate"] == 0.0


def test_replay_single_function_for_floor_control():
    h = ReplayHarness(ReplaySpec(single_function=True, seed=1), "L0")
    assert len(h.run(".", "task").timeline) == 1


def test_replay_is_deterministic_given_seed():
    a = ReplayHarness(ReplaySpec(seed=42), "L0").run(".", "t").changed_files
    b = ReplayHarness(ReplaySpec(seed=42), "L0").run(".", "t").changed_files
    assert a == b


def test_stream_parser_extracts_tools_and_usage():
    events = [
        {"type": "assistant", "message": {"model": "m1", "content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": "a.ts"}}],
            "usage": {"input_tokens": 10, "output_tokens": 5,
                      "cache_read_input_tokens": 3}}},
    ]
    res = parse_stream("\n".join(json.dumps(e) for e in events))
    assert len(res.timeline) == 1 and res.timeline[0].path == "a.ts"
    assert res.input_tokens == 10 and res.cache_read_tokens == 3
    assert res.model_id == "m1"


def test_stream_parser_warns_when_schema_yields_nothing():
    """A silent CLI format change must surface as a warning, not as an
    unexplained drop in reconstructable positions."""
    res = parse_stream(json.dumps({"type": "something_new", "data": {}}))
    assert res.parse_warnings and "tool_use" in res.parse_warnings[0]


def _result_event(**over):
    base = {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.25,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 200,
            "cache_read_input_tokens": 26435,
            "cache_creation_input_tokens": 5261,
        },
        "permission_denials": [],
    }
    base.update(over)
    return json.dumps(base)


def _assistant_event(usage):
    return json.dumps({
        "type": "assistant",
        "message": {"model": "claude-sonnet-4-6", "content": [], "usage": usage},
    })


def test_session_totals_come_from_the_terminal_result_event():
    """Per-turn usage double-counts cache reads against a shared prefix.

    Ancillary accounting only — no preregistered endpoint reads these numbers.
    """
    from contextfidelity.harness import parse_stream

    stream = "\n".join([
        _assistant_event({"input_tokens": 3, "output_tokens": 5, "cache_read_input_tokens": 10688}),
        _assistant_event({"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 15747}),
        _result_event(),
    ])
    res = parse_stream(stream)
    assert res.input_tokens == 10
    assert res.output_tokens == 200
    assert res.cache_read_tokens == 26435  # not 10688 + 15747
    assert res.total_cost_usd == 0.25


def test_permission_denials_are_counted():
    from contextfidelity.harness import parse_stream

    res = parse_stream(_result_event(permission_denials=[{"tool_name": "Write"}]))
    assert res.permission_denials == 1


def test_permission_args_are_fixed_on_the_real_harness():
    from contextfidelity.harness import ClaudeCodeHarness

    argv = ClaudeCodeHarness("claude", "claude-sonnet-4-6")._argv("do a thing")
    assert "--dangerously-skip-permissions" in argv


def test_blocked_runs_do_not_satisfy_a_cell():
    """A denied write is a harness fault, not a behavioural outcome. If it
    counted as completed, resume would skip the cell and the phase would be
    quietly short of data."""
    import tempfile
    from pathlib import Path

    from contextfidelity.ledger import Ledger

    with tempfile.TemporaryDirectory() as td:
        led = Ledger(Path(td) / "l.jsonl")
        common = dict(phase="phase1", cell_id="C", rung="L0", arm="A1", task_id="T3",
                      replicate=1, seal_hash="s", target_commit="c", harness="claude-code",
                      harness_version="2.1.92", model_id="m", config_sha256="")
        led.append(run_id="a", status="blocked", **common)
        assert led.completed_cells() == {}
        led.append(run_id="b", status="no_code", **common)
        assert led.completed_cells() == {"C|T3": 1}


def test_rate_limited_session_is_blocked_not_no_code():
    """The failure that wrecked the first Phase 1.

    91 quota-exhausted sessions were recorded as no_code, which counts as a
    completed cell, so resume would have skipped them permanently and the phase
    would have been silently short of data forever.
    """
    from contextfidelity.harness import parse_stream

    stream = "\n".join([
        json.dumps({"type": "rate_limit_event",
                    "rate_limit_info": {"status": "rejected", "rateLimitType": "five_hour"}}),
        _result_event(total_cost_usd=0.0,
                      usage={"input_tokens": 0, "output_tokens": 0,
                             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}),
    ])
    res = parse_stream(stream)
    assert res.rate_limit_status == "rejected"


def test_allowed_rate_limit_event_is_not_a_failure():
    """Healthy sessions also emit rate_limit_event with status 'allowed';
    treating its mere presence as failure would invalidate every good run."""
    from contextfidelity.harness import parse_stream

    stream = "\n".join([
        json.dumps({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}}),
        _result_event(),
    ])
    assert parse_stream(stream).rate_limit_status == ""


def test_no_work_detection_distinguishes_infrastructure_from_behaviour():
    """A genuine no_code session still costs money and emits tokens; a dead
    environment returns in under two seconds having spent nothing."""
    from contextfidelity.harness import parse_stream

    dead = parse_stream(_result_event(
        total_cost_usd=0.0,
        usage={"input_tokens": 0, "output_tokens": 0,
               "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}))
    assert dead.total_cost_usd == 0.0 and dead.output_tokens == 0 and not dead.timeline

    real = parse_stream(_result_event())
    assert real.total_cost_usd > 0 and real.output_tokens > 0
