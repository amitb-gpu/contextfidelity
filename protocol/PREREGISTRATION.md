# Preregistration

**Study:** Within-session instruction attenuation in coding agents — preregistered
replication and complexity extension

**Status:** DRAFT — not sealed. Fields marked `TBD` must be filled before sealing.
Sealing before the environment check has run is a protocol violation.

**Seal version:** TBD
**External timestamp (DOI / OTS proof):** TBD
**Replication mode:** EXACT — Claude Code CLI 2.1.92 with Claude Sonnet 4.6 (`claude-sonnet-4-6`)

---

## 1. Target finding

McMillan, D. (2026), *Instruction Adherence in Coding Agent Configuration Files*,
arXiv:2605.10039, reports that each additional function an agent generates within
a session is associated with approximately 5.6% lower odds of complying with a
repository configuration instruction (OR = 0.944, 95% CI [0.937, 0.951]), across
1,650 sessions and 16,050 function-level observations.

Two properties make it a replication target rather than an established result.
The author states the finding was identified during analysis rather than
pre-specified, treats it as a follow-on investigation, and asks for independent
replication before it is relied upon. And the same paper reports firm nulls on
all four *structural* variables it did pre-specify — file size, instruction
position, file architecture, and inter-file conflict — so the attenuation result
is the one live effect in an otherwise null study, which is exactly the situation
where a post-hoc finding most deserves scrutiny.

We are not assuming the effect is real. Both outcomes are reportable and the
criterion for each is fixed below.

## 2. Research questions

- **RQ1** Does within-session compliance attenuation replicate under a
  preregistered analysis?
- **RQ2** Does the shape or magnitude of attenuation change as instruction
  complexity increases?
- **RQ3** Can targeted rule re-surfacing reduce attenuation, and is any recovery
  attributable to rule *content* rather than to attention interruption?

RQ2 is asked only if RQ1's gate passes. RQ3 only if RQ2 finds attenuation at some
rung. See `stopping_rules.yaml`.

## 3. Hypotheses

- **H1** Compliance changes systematically with within-session generation
  position, in the negative direction. *Not* specified as a constant per-step
  decrement: the original explicitly describes the relationship as non-monotonic,
  so the primary specification is a restricted cubic spline with knots fixed in
  advance at generation positions 1, 4, 8, 15. The linear coefficient is reported
  additionally as an odds ratio, for comparability only.
- **H2** The position effect interacts with instruction complexity.
  Direction is **not** predicted. A steeper slope at higher rungs and a flat
  profile are both substantive results.
- **H3** Event-triggered re-surfacing of the applicable rule attenuates the
  position effect relative to configuration-only.
- **H3-placebo** If re-surfacing an *irrelevant* rule of matched length produces
  comparable recovery, the mechanism is attention interruption rather than rule
  content. This is a coequal hypothesis, not a robustness check.

## 4. Design

Complexity ladder (`src/contextfidelity/rules.py`), matched on opportunities:

| Rung | Rule | Atoms | Strata |
|---|---|---|---|
| L0 | static local marker on every function | 1 | — |
| L1 | conditional marker, locally visible predicate | 1 | predicate true / false |
| L2 | three-step procedural rule | 3 | — |
| L3 | marker tier determined by a repository registry file | 1 | strict / standard |

**An opportunity is one new-or-modified function, at every rung.** L1 and L3 vary
what the correct behaviour is per function, not whether there is one, so
opportunity counts are matched by construction rather than by hoping tasks
balance. This is the artifact that would otherwise manufacture the H2 effect: a
rung requiring more actions produces a lower all-or-nothing score even at
unchanged per-action probability.

**Two scales, primary fixed in advance.** *Atomic* compliance (proportion of
individual required actions performed) is primary for cross-rung comparison,
because rungs differ in atom count. *Complete* compliance (all actions on an
opportunity) is secondary and reported for practitioner relevance. L2's complete
rate is arithmetically depressed relative to L0; that is not a finding.

Arms:

| Arm | Condition |
|---|---|
| A1 | configuration only |
| A2 | configuration + periodic reminder |
| A3 | configuration + event-triggered re-surfacing of the applicable rule |
| A4 | configuration + event-triggered re-surfacing of a matched-length irrelevant rule (placebo) |

**Floor controls at every rung.** A single-function task establishing that the
agent *can* comply at generation position 1. Without it a flat slope is ambiguous
between "no attenuation" and "never complied", and at L3 specifically it is what
separates an adherence failure from a retrieval failure.

**No-configuration baseline.** Establishes that the marker never appears
spontaneously. If it does, the outcome measures something other than
instruction-driven behaviour.

## 5. Analysis plan

Committed in `analysis_plan.md` and implemented in
`src/contextfidelity/analysis/model.py`, both sealed. Summary:

- Outcome is binary at the atom level.
- Predictor is chronological generation position, reconstructed from the tool
  timeline. AST-traversal index reported as sensitivity.
- Inference is clustered on **sessions**, via nonparametric session-level
  bootstrap (primary) and cluster-robust GLM (cross-check). Atom-level
  independence is not assumed: at ~16 functions per session the design effect is
  substantial and naive intervals would be far too narrow.
- Non-production trials (agent returns a clarifying question instead of code) are
  reported as a separate Code-Production Rate and are **not** counted as
  non-compliance. An agent that asks rather than guesses has not violated the
  rule, and folding those trials into the denominator would penalise exactly the
  behaviour we would want.

## 6. Reproduction criterion (RQ1 gate)

All four required, evaluated by `analysis/gate.py`:

1. No-configuration baseline marker rate ≤ 1%.
2. Floor-control position-1 compliance ≥ 50%.
3. Linear position slope negative with 95% session-bootstrap CI excluding zero.
4. CI on the odds ratio overlaps the preregistered compatibility band
   [0.85, 1.00].

Outcomes: `REPRODUCED`, `NOT_REPRODUCED`, `INCONCLUSIVE`. The third is a real
outcome — an underpowered or non-converged phase 1 stops the study rather than
being rounded toward whichever answer is nearer.

Direction-without-magnitude (3 passes, 4 fails) is reported explicitly as such
and not as either a clean replication or a clean null.

## 7. Sample size

Simulation-based, clustered on sessions (`src/contextfidelity/power.py`), anchored
on the original's reported parameters, including a between-session slope-variance
term. That term matters: generation position is a *within*-session predictor, so
a session random intercept barely inflates its standard error and a calculation
carrying only an intercept comes out optimistic. The original reported
substantial per-task slope heterogeneity (per-task ORs from 1.005 to 0.831), so
a nonzero slope sd is the conservative default.

Simulated at 50 sessions per cell (matching the original's depth), slope
sd = 0.03:

| Test | Power |
|---|---|
| RQ1: detect a negative slope | 0.95 |
| RQ2/RQ3: detect a **1.5x** steeper slope | 0.33 |
| RQ2/RQ3: detect a **2x** steeper slope | 0.77 |

**The contrast tests are underpowered for moderate differences and this is
declared in advance.** Reaching 0.80 power on a 1.5x difference needs well over
300 sessions per cell — roughly six times the budget, and not feasible. The
consequence is stated here rather than discovered at write-up:

> RQ2 and RQ3 are powered to detect slope differences of approximately 2x or
> larger. A null result on either is evidence against a *large* difference and
> is **not** evidence of no difference. Any RQ2/RQ3 null will be reported with
> this minimum detectable effect attached.

Sensitivity of RQ1 power to slope heterogeneity: 1.00 at sd = 0, 0.95 at
sd = 0.03, 0.74 at sd = 0.06. If observed between-session slope variance in
phase 1 exceeds 0.06, phase 1 is reported as underpowered regardless of its
point estimate.

- Sessions per cell: 50 (multi-function tasks), 40 (floor controls)
- Numbers above regenerate with `python scripts/power_check.py`

## 8. What is not claimed

- No claim that the agent "forgot" the instruction. The observable is behavioural.
  Lost salience, planning competition, prompt construction, context compaction,
  and harness behaviour are all live explanations that this design does not
  separate. If compliance rebounds immediately after re-injection that constrains
  the explanation; it does not expose an internal mechanism.
- No claim about models, harnesses, languages, or task types outside those run.
  The original found a 12.8-point compliance gap between two models in the same
  family at matched configuration, and an 11-point shift between codebases.
  Absolute rates are not portable.
- No claim that the marker instruction generalises to instructions requiring
  comprehension or multi-step reasoning beyond the ladder as specified.
- No cost or caching claim. Cache-adjusted economics is a deliberate later axis;
  including it here would recreate the confounded multi-intervention design this
  study exists to avoid.

## 9. Deviations

Any departure from this document after sealing is recorded here with its date and
reason, and the protocol is re-sealed with a new version. Both seals are reported.
Silent overwriting defeats the purpose of sealing.

| Date | Deviation | Reason | New seal |
|---|---|---|---|
| — | — | — | — |
