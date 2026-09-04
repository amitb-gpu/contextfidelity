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
