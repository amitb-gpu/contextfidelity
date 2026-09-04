# Analysis plan

Sealed with the protocol. Implemented in `src/contextfidelity/analysis/model.py`.

## Unit and outcome

One row per **atom** (individual required action) per **opportunity** (one
new-or-modified function) per **session** (one agent run). Binary outcome.

Primary scale is **atomic**. Secondary is **complete** (all atoms on an
opportunity), collapsed to one row per opportunity. The primary scale is fixed
here because rungs differ in atom count; choosing after seeing results is the
failure this document prevents.

## Predictor

Chronological generation position: the order the agent emitted each function,
recovered from the session's file-touching tool calls. Functions in files never
touched have no position and are excluded by construction — counted and
reported, not dropped silently. A run whose position coverage falls below 80%
is not scored; that indicates the timeline parser is failing, most likely
because the harness changed its event schema.

Sensitivity: AST-traversal index (files alphabetical, declaration order).

## Specification

Primary: restricted cubic spline on generation position, knots fixed in advance
at 1, 4, 8, 15. Knot placement is dense at the low end because the original
found a substantial share of non-compliance mass in the first few generated
functions (median first omission at position 4).

Reported additionally: the linear coefficient as an odds ratio per generation
step, for comparability with the original's 0.944. This is a comparability
statistic, not the primary specification.

Model-free companion: compliance rate in preregistered position bins 1-3, 4-15,
16+. Reported alongside the spline so the shape can be inspected without
trusting the basis.

Nonlinearity: likelihood-ratio test of spline against linear, df = knots - 2.

## Inference

Primary intervals: nonparametric bootstrap resampling **sessions** with
replacement, 2000 draws, percentile method. The cluster is the session.
Resampling atoms would treat within-session correlation as extra information and
produce intervals that are too narrow.

Cross-check: logistic GLM with cluster-robust covariance on session.

Contrasts (RQ2, RQ3): difference in linear slope between conditions, with a
paired session-level bootstrap on the difference. Reported as distinguishable
only if the 95% interval excludes zero.

## Handling

- **Non-production trials** (clarifying question instead of code): separate
  Code-Production Rate. Not counted as non-compliance.
- **Constant outcome**: a slope is not estimable and is reported as such. For
  the no-configuration baseline this is the expected zero-floor result.
- **Convergence failure**: reported, never silently dropped.
- **L1 strata** (predicate true / false) reported separately. Pooling would hide
  the difference between an agent that stops applying a rule and one that
  applies it indiscriminately.
- **L3 strata** (strict / standard tier) reported separately.

## Multiplicity

RQ1 is a single planned contrast, uncorrected. RQ2 comprises three planned
rung-vs-L0 contrasts and RQ3 three planned arm-vs-A1 contrasts; both families
are Benjamini-Hochberg corrected at FDR 0.05 within family. Exploratory analyses
are labelled exploratory in any write-up and are not corrected into the planned
families.
