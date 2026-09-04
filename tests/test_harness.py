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
