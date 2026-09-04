# Operational deviation log

Append-only. Deliberately **outside** `SEALED_GLOBS` (see
`contextfidelity.seal.SEAL_EXCLUDE` and §9 of the preregistration): operational
facts are not knowable when the protocol is frozen, so sealing this file would
mean that recording a deviation breaks the seal — honesty would present as
tampering, and silence would be the only way to stay intact.

This file records **operational** deviations only: harness configuration,
infrastructure faults, invalidated runs, environment drift. Anything touching
hypotheses, tasks, the ladder, scorers, the analysis model, the gate or the
stopping rules is an experimental change and requires re-sealing under a new
version and a new external witness. This log is not a side door for editing the
protocol.

Entries are appended in order and never edited. Each names the protocol tag and
manifest hash in force when it occurred.

---

## D-001 — Headless permission mode; harness could not write

- **Governing protocol:** v1.0-protocol, manifest `cfe3058868cf8656eeda9227475238abbb69c547e5e218fb3eaf87354b76b1fa`
- **Discovered:** 2026-09-04, during the Phase-1 validation session
- **Kind:** operational (harness configuration)

The pinned CLI was invoked without permission flags and therefore ran in
`permissionMode: "default"`, in which every write is denied in headless mode. The
validation session ran 87 turns over 334s, touched one file in its timeline, and
changed nothing on disk. A direct probe confirmed the cause:

```
"Claude requested permissions to write to .../hello.txt, but you haven't granted it yet."
permission_denials: [{"tool_name": "Write", ...}]
```

The harness recorded this as `no_code`. That status feeds the Code-Production
Rate, which the protocol treats as legitimate behaviour — an agent that asks
rather than guesses has not violated the rule. Had the full phase run, all 340
sessions would have returned a clean, fully powered and entirely artifactual
null: a harness fault reported as a finding about instruction attenuation.

**Resolution, fixed for all real sessions under v1.1:**

1. `--dangerously-skip-permissions` is a fixed non-interactive harness parameter
   (`ClaudeCodeHarness.PERMISSION_ARGS`), not a per-run choice. Sessions are
   confined to a target repository hard-reset and `git clean -fdx`'d beforehand.
2. Permission denials are counted from the terminal `result` event and force
   status `blocked`, which is not a completed cell and produces no scored rows,
   so such a run is retried rather than analysed.
3. `assert_target_cwd` refuses to invoke the real CLI anywhere but the configured
   target repository, and refuses entirely when none is configured — previously
   an unset `target_repo` would have turned the agent loose on the study's own
   working tree.
4. `scripts/preflight.py` proves write capability by creating and then modifying
   a disposable file in the configured target through the same harness the study
   uses. A text-only smoke test is explicitly insufficient: the original smoke
   test passed while writes were impossible.

## D-002 — One invalid session quarantined

- **Governing protocol:** v1.0-protocol, manifest `cfe3058868cf8656eeda9227475238abbb69c547e5e218fb3eaf87354b76b1fa`
- **Date:** 2026-09-04
- **Kind:** operational (invalidated run)

Session `P1-BASE-T3-r001` (cell `P1-BASE`, rung L0, arm A1, task T3, no-config
baseline) was executed under the conditions in D-001 and returned `no_code` with
zero functions emitted. It is invalid: the outcome reflects a denied write, not
model behaviour.

It is retained at `runs-INVALID-permission-denied/` for inspection, is excluded
from every scientific denominator, and is not present on any resume path — the
phase-1 ledger was removed wholesale rather than edited, since the ledger is
hash-chained and deleting a record would break the chain it exists to protect.

No other session was executed under v1.0. Phase 1 begins from zero under v1.1.

## D-003 — Ancillary token and cost accounting corrected

- **Governing protocol:** v1.1-protocol, manifest `eb747a9e90caca4b9cbc4cb9ec38e331edf38789e6bdc93386fa8983fc0594ec`
- **Date:** 2026-09-04
- **Kind:** operational (instrumentation)

Session usage was summed across per-turn `assistant` events, which double-counts
cache reads against a shared prefix and undercounts the rest; the quarantined
session recorded 327 input / 562 output tokens for an 87-turn session. Totals are
now taken from the terminal `result` event, and `total_cost_usd` is recorded.

No preregistered endpoint, denominator or gate criterion reads these fields. They
are ancillary accounting and cannot affect the phase-1 decision.

## D-004 — Phase 1 attempt 1 invalidated: account quota exhausted mid-collection

- **Governing protocol:** v1.1-protocol, manifest `eb747a9e90caca4b9cbc4cb9ec38e331edf38789e6bdc93386fa8983fc0594ec`
- **Date:** 2026-09-05
- **Kind:** operational (environment fault, invalidated phase)

The first Phase-1 collection iterated all 340 planned sessions but produced a
usable result for none of the design's comparisons. The account's five-hour
usage window was exhausted after approximately 59 sessions (~4.3 hours of
collection), and `overageStatus` was `rejected` with reason `out_of_credits`, so
there was no headroom. Every subsequent session returned in ~1.8s with one turn,
zero tokens and `$0.0000` cost, and the stream carried a `rate_limit_event`.

Observed distribution:

| Cell | Result |
|---|---|
| `P1-BASE` | 59 ok, 91 invalid |
| `P1-L0-A1` | 150 invalid, **zero** usable |
| `P1-L0-FLOOR` | 40 invalid, **zero** usable |

The treatment cell and the floor controls contain no data at all, so the phase
cannot support the reproduction criterion under any handling of the remainder.

**Two classification faults, both the D-001 failure in a new costume.** 91
quota-exhausted sessions were recorded as `no_code` — a behavioural outcome that
feeds the Code-Production Rate *and* counts as a completed cell, so a resume
would have skipped those 150 baseline runs permanently and left the phase
silently short of data. The other 190 were recorded as bare `error`. In both
cases an infrastructure fault was presented as something the model did.

Collection also continued for 281 sessions after the environment was dead,
because nothing checked whether consecutive runs were producing anything.

**Disposition.** The phase was frozen before being touched, so the failure is
recorded immutably: chain intact, single governing seal `eb747a9e90ca`, ledger
sha256 `f7b12f1b505fa67bc530f793af024a394276bba0231525ededcb7af683ace9ce`. It is
quarantined at `runs-INVALID-rate-limit-phase1/`, excluded from every scientific
denominator, and is not on any resume path.

**No analysis was run and no gate outcome was computed.** Reporting
`NOT_REPRODUCED` or `INCONCLUSIVE` from a phase whose treatment cell is empty
would be reporting an infrastructure failure as a scientific result.

**Resolution, effective for all subsequent collection:**

1. A session carrying a non-`allowed` `rate_limit_event`, or one that engaged no
   API work at all (no tool events, zero cost, zero output tokens), is now
   classified `blocked`. `blocked` satisfies no cell and produces no scored rows,
   so such runs are retried on resume rather than silently accepted. A
   `rate_limit_event` with status `allowed` appears on healthy sessions and is
   explicitly not treated as a fault.
2. `run_phase` aborts after 5 consecutive invalid sessions and reports the abort,
   rather than grinding through a dead environment.
3. Collection must be planned around the five-hour window. At the observed ~264s
   per session, roughly 55-60 sessions fit in one window, so Phase 1 requires
   about six windows and must be run as resumable chunks.

No experimental, design or analysis change accompanies this entry, so the
manifest is unchanged and no re-seal is required. This is the case the
append-only log exists for.
