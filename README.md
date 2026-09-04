# contextfidelity

A preregistered replication of within-session instruction attenuation in coding
agents, extended along instruction complexity.

## The target

McMillan (2026, [arXiv:2605.10039](https://arxiv.org/abs/2605.10039)) reports that
each additional function a coding agent generates within a session is associated
with roughly 5.6% lower odds of complying with a repository configuration
instruction — OR 0.944, across 1,650 sessions and 16,050 function-level
observations.

Two things make it worth replicating rather than citing. The author states the
finding was identified during analysis rather than pre-specified, treats it as a
follow-on investigation, and asks for independent replication. And the same paper
reports firm nulls on all four *structural* variables it did pre-specify — file
size, instruction position, file architecture, inter-file conflict — so the
attenuation result is the one live effect in an otherwise null study. That is
precisely the situation where a post-hoc finding deserves scrutiny.

**This repository does not assume the effect is real.** The reproduction
criterion is fixed in advance and a null is a result.

## Quick start

```bash
conda env create -f environment.yml && conda activate contextfidelity
pip install -e .

python scripts/check_environment.py     # go/no-go: EXACT or CONCEPTUAL?
python scripts/plan_runs.py             # the design and its budget
python scripts/power_check.py           # simulated power, clustered on sessions
python scripts/seal_protocol.py --version v1.0 --timestamp <your DOI>
python scripts/run_phase.py phase1 --harness replay   # pipeline dry run
python scripts/analyze.py phase1
python -m pytest                        # 49 tests
```

## Order of operations, and why it is that order

**1. Environment check before anything else.** The original pinned Claude Code
CLI 2.1.92 with Sonnet 4.6. Those pins *are* the replication. If they can't be
reproduced you are running a different system, and the study is a *conceptual*
replication that must say so in its title. The original demonstrates the hazard
on itself: its Opus 4.7 block was forced onto a newer CLI that enables adaptive
thinking by default, and the authors correctly decline to draw a model-level
conclusion because model, CLI, and thinking mode all moved together. Discovering
this mid-collection means the runs already spent belong to neither mode.

**2. Power before sealing.** See the finding below.

**3. Seal before data.** `runner.py` refuses to execute a phase without an intact
seal. The seal covers the protocol *and* the scorer *and* the analysis model — a
frozen protocol with a mutable scoring function is not a preregistration.

**4. Dry run on the replay harness.** Confirms the pipeline recovers a slope that
was deliberately injected, before spending the real budget.

## What the dry run found

Running the pipeline against synthetic sessions with a known slope surfaced three
things worth fixing before sealing, which is the entire point of doing it:

**The contrast tests are underpowered, badly.** At 50 sessions per cell — the
original's depth — power to detect a *slope* is 0.95, but power to detect a 1.5x
*difference* in slopes is 0.33. Reaching 0.80 would need over 300 sessions per
cell, roughly six times the budget. RQ2 and RQ3 are therefore powered only for
differences of about 2x or larger, and the preregistration says so up front: a
null on either is evidence against a large difference, not evidence of no
difference. A design powered to replicate is not automatically powered to compare.

**Random slopes are what make clustering bite.** Generation position is a
*within*-session predictor, so a session random intercept barely inflates its
standard error — clustering looks like it doesn't matter, and a power calculation
carrying only an intercept comes out optimistic. Between-session variation in the
slope itself is the term that matters. RQ1 power runs 1.00 / 0.95 / 0.74 at slope
sd of 0 / 0.03 / 0.06.

**A threshold was miscalibrated.** The floor-control minimum started at 60%
compliance, which sits *inside* the range of ordinary healthy behaviour — the
original's own per-task rates ran from 45% to 84%. It would have failed a sound
study. Recalibrated to 50%, with the reasoning recorded in `gate.py`.

## The design

Complexity ladder, matched on opportunities:

| Rung | Rule | Atoms | Strata |
|---|---|---|---|
| L0 | static marker on every function | 1 | — |
| L1 | conditional marker, locally visible predicate | 1 | predicate true / false |
| L2 | three-step procedural rule | 3 | — |
| L3 | marker tier from a repository registry file | 1 | strict / standard |

**An opportunity is one new-or-modified function, at every rung.** L1 and L3 vary
what the correct behaviour is, not whether there is one, so opportunity counts
match by construction. This kills the artifact that would otherwise manufacture
the complexity effect: a rung demanding more actions scores lower on an
all-or-nothing measure even at unchanged per-action probability. A test asserts
the counts stay equal across rungs.

For the same reason **atomic compliance is the primary scale** and complete
compliance is secondary — L2's complete rate is arithmetically depressed relative
to L0, and that is not a finding. Which scale is primary is fixed in `model.py`
before any data exists.

Arms: A1 configuration only, A2 periodic reminder, A3 event-triggered
re-surfacing of the applicable rule, **A4 event-triggered re-surfacing of a
matched-length irrelevant rule**.

A4 is not a robustness check. Re-surfacing changes three things at once — the
rule becomes salient, it becomes recent, and the context grows — so without a
placebo a positive A3 result attributes recovery to rule content when it could be
attention reset. If the placebo also restores compliance, the mechanism is
interruption, and that is the more interesting finding. The placebo is
length-matched per rung from a sealed clause pool, because one fixed text cannot
match both L0 and L2 and an unmatched placebo reintroduces the token-count
confound it exists to remove.

Floor controls at every rung establish that the agent *can* comply at generation
position 1. Without them a flat slope is ambiguous between "no attenuation" and
"never complied" — and at L3 specifically, that is what separates an adherence
failure from a retrieval failure.

## Phase gates

```
phase 1 (RQ1: does it replicate?)      -> REPRODUCED | NOT_REPRODUCED | INCONCLUSIVE
   |  only if REPRODUCED
phase 2 (RQ2: does complexity matter?) -> resolves the phase-3 target rung
   |  only if some rung attenuates
phase 3 (RQ3: does re-surfacing help, and is it content or interruption?)
```

Gates exist because RQ1 conditions RQ2 conditions RQ3: if attenuation doesn't
reproduce, the ladder measures the slope of nothing. They also control cost —
all three phases at full depth is 1,280 sessions.

The phase-1 criterion (`analysis/gate.py`) requires all four of: zero floor holds
in the no-configuration baseline; floor control clears 50%; slope negative with
its 95% session-bootstrap CI excluding zero; and the OR interval overlapping a
preregistered compatibility band of [0.85, 1.00]. That last one matters — a real
effect five times too steep is not the same finding, and the gate reports
"direction replicated but magnitude did not" rather than letting a directional
hit be written up as a replication.

`INCONCLUSIVE` is a real outcome. An underpowered or non-converged phase 1 stops
the study rather than being rounded toward whichever answer is nearer.

Verified end to end on the replay harness:

| Injected slope | Gate outcome |
|---|---|
| −0.0578 (the original's) | REPRODUCED |
| 0.0 (no effect) | NOT_REPRODUCED — CI includes zero |
| −0.30 (5x too steep) | NOT_REPRODUCED — direction yes, magnitude no |

## Analysis

Committed in `protocol/analysis_plan.md`, implemented in `analysis/model.py`, both
sealed.

Shape is not assumed linear — the original describes the relationship as
non-monotonic, so forcing one coefficient would misspecify the thing being
replicated. Primary specification is a restricted cubic spline with knots fixed
in advance at positions 1, 4, 8, 15, dense at the low end because the original
found most non-compliance mass in the first few functions. The linear OR is
reported additionally, for comparability only, alongside model-free bin rates.

Inference clusters on sessions via nonparametric bootstrap, with a cluster-robust
GLM as cross-check. Non-production trials (the agent asks a clarifying question
instead of writing code) are reported as a separate Code-Production Rate and are
**not** counted as non-compliance — an agent that asks rather than guesses hasn't
violated the rule, and folding those into the denominator would penalise exactly
the behaviour you'd want.

## The replay harness

`--harness replay` generates synthetic sessions from a specified compliance
process. It is **not** a model simulator and must never be reported as one. Its
only job is to answer "if the effect were there, would this pipeline find it?"
before the run budget is spent. On the numbers above it recovers an injected
0.944 as 0.9467 with CI [0.9359, 0.9565].

## What is not claimed

No claim that the agent "forgot" anything — the observable is behavioural, and
lost salience, planning competition, prompt construction, context compaction and
harness behaviour are all live explanations this design does not separate. No
claim beyond the models, harnesses, languages and tasks actually run; the original
found a 12.8-point gap between two models in one family at matched configuration
and an 11-point shift between codebases, so absolute rates are not portable. No
cost or caching claim — cache-adjusted economics is a deliberate later axis, and
folding it in here would recreate the confounded multi-intervention design this
study exists to avoid.

## Before you run this for real

- Fill every `TBD` in `protocol/PREREGISTRATION.md`, including the replication
  mode from the environment check.
- Get an **external** timestamp. A self-issued one proves nothing about when the
  protocol existed; the tool marks any seal without one as `UNWITNESSED` and says
  so on every run. Zenodo DOI or an OpenTimestamps proof, deposited before the
  first real run.
- Consider sending the frozen protocol to McMillan. He explicitly invited
  replication; it costs nothing, may get you the scoring fixtures, and avoids
  colliding with work already under way.
