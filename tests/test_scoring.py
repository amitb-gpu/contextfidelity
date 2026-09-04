from contextfidelity.rules import LADDER
from contextfidelity.scoring import extract_functions, score_run, summarize

DOC = """
/**
 * @audit-scope helpers
 */
export async function alpha() {
  // @tracked
  return 1;
  // @end-tracked
}

function beta() {
  return 2;
}
"""
PATH = "src/lib/helpers.ts"


def test_extracts_both_functions():
    fns = extract_functions(PATH, DOC)
    assert {f.name for f in fns} == {"alpha", "beta"}


def test_export_and_async_detected():
    fns = {f.name: f for f in extract_functions(PATH, DOC)}
    assert fns["alpha"].is_exported and fns["alpha"].is_async
    assert not fns["beta"].is_exported and not fns["beta"].is_async


def test_opportunity_counts_match_across_rungs():
    """The core anti-artifact property: a harder rung must not have fewer or
    more opportunities, or slope comparisons across rungs are confounded."""
    counts = {
        rid: summarize(score_run({PATH: DOC}, LADDER[rid], {"src/lib": "strict"}))["opportunities"]
        for rid in ("L0", "L1", "L2", "L3")
    }
    assert len(set(counts.values())) == 1, counts


def test_l2_has_three_atoms_per_opportunity():
    s = summarize(score_run({PATH: DOC}, LADDER["L2"]))
    assert s["atoms"] == 3 * s["opportunities"]


def test_l1_splits_strata_by_predicate():
    strata = summarize(score_run({PATH: DOC}, LADDER["L1"]))["by_stratum"]
    assert set(strata) == {"predicate_true", "predicate_false"}


def test_l1_penalises_over_application():
    over = "export function gamma() {\n  // @audited\n  return 1;\n}"
    s = score_run({PATH: over}, LADDER["L1"])
    assert s[0].atoms[0].passed is False


def test_l3_uses_registry_tier():
    src = "export function d() {\n  // @tracked:strict\n  return 1;\n}"
    strict = score_run({PATH: src}, LADDER["L3"], {"src/lib": "strict"})
    standard = score_run({PATH: src}, LADDER["L3"], {"src/lib": "standard"})
    assert strict[0].complete and not standard[0].complete


def test_registry_falls_back_to_nearest_parent():
    from contextfidelity.scoring import registry_tier
    reg = {"src/lib": "strict"}
    assert registry_tier("src/lib/deep/x.ts", reg) == "strict"
    assert registry_tier("src/other/x.ts", reg) == "standard"


def test_marker_must_be_first_line_not_merely_present():
    late = "export function e() {\n  const x = 1;\n  // @tracked\n  return x;\n}"
    assert not score_run({PATH: late}, LADDER["L0"])[0].complete
