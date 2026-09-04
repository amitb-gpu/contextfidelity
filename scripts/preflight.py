#!/usr/bin/env python3
"""Fail-closed pre-flight. Run immediately before any real phase.

Every check must pass. The last one is the reason this script exists: a
text-only smoke test proves the CLI answers, not that it can change the
repository. The first Phase-1 attempt passed a text smoke test and then produced
340 sessions' worth of nothing, because in default permission mode every write
was denied and the harness recorded the denial as "the agent wrote no code".

So the write check actually creates a file and then modifies it, in the
configured target repository, through the same harness the study uses.
"""
import argparse
import subprocess
import sys

import _boot  # noqa: F401
from contextfidelity import seal as sealmod
from contextfidelity.config import Settings
from contextfidelity.environment import check
from contextfidelity.harness import ClaudeCodeHarness, changed_files, reset_repo

PROBE = ".contextfidelity-preflight.txt"


def _fail(msg: str) -> bool:
    print(f"  FAIL  {msg}")
    return False


def _ok(msg: str) -> bool:
    print(f"  ok    {msg}")
    return True


def check_write_capability(s: Settings) -> bool:
    """Create, then modify, a disposable file via the pinned CLI."""
    repo = s.target_repo
    harness = ClaudeCodeHarness(s.cli_path, s.model)
    try:
        reset_repo(repo, s.target_commit or "HEAD")

        res = harness.run(repo, f"Create a file named {PROBE} containing exactly the text ALPHA", 300)
        if res.permission_denials:
            return _fail(f"create denied ({res.permission_denials} permission denial(s))")
        created = changed_files(repo)
        if PROBE not in created:
            return _fail(f"create produced no {PROBE} (status={res.status})")
        if "ALPHA" not in created[PROBE]:
            return _fail(f"{PROBE} does not contain ALPHA after create")
        _ok(f"create: {PROBE} written")

        res = harness.run(
            repo, f"Modify the existing file {PROBE} so that it contains exactly the text BETA", 300
        )
        if res.permission_denials:
            return _fail(f"modify denied ({res.permission_denials} permission denial(s))")
        after = changed_files(repo)
        if PROBE not in after or "BETA" not in after[PROBE]:
            return _fail(f"{PROBE} not modified to BETA (status={res.status})")
        return _ok(f"modify: {PROBE} changed in place")
    finally:
        reset_repo(repo, s.target_commit or "HEAD")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v1.1-protocol", help="protocol tag that must govern this run")
    ap.add_argument("--skip-write-check", action="store_true",
                    help="diagnostics only; a real phase must never be started this way")
    args = ap.parse_args()
    s = Settings.load()
    results = []

    print("environment")
    env = check(s.cli_path, s.model)
    results.append(_ok(f"execution stack {env.mode}") if env.mode == "EXACT"
                   else _fail(f"execution stack {env.mode}: {env.deviations}"))

    print("protocol")
    tag = subprocess.run(["git", "-C", str(s.root), "rev-parse", f"{args.tag}^{{commit}}"],
                         capture_output=True, text=True)
    results.append(_ok(f"tag {args.tag} -> {tag.stdout.strip()[:12]}") if tag.returncode == 0
                   else _fail(f"tag {args.tag} does not exist"))

    if not s.seal_path.exists():
        results.append(_fail("no seal"))
    else:
        v = sealmod.verify(s.root, s.seal_path)
        results.append(_ok(v.summary()) if v.ok else _fail(v.summary()))
        w = sealmod.witness_state(v.seal, s.seal_path)
        results.append(_ok(f"witness {w.status} ({w.detail})") if w.ok
                       else _fail(f"witness {w.status}: {w.detail}"))

    print("target repository")
    if s.target_repo is None:
        results.append(_fail("target_repo not configured"))
    else:
        head = subprocess.run(["git", "-C", str(s.target_repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        results.append(_ok(f"HEAD {head[:12]} == pinned") if head == s.target_commit
                       else _fail(f"HEAD {head[:12]} != pinned {(s.target_commit or '')[:12]}"))
        dirty = subprocess.run(["git", "-C", str(s.target_repo), "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        results.append(_ok("target clean") if not dirty else _fail("target has local changes"))

    print("write capability")
    if args.skip_write_check:
        print("  SKIPPED — this run is diagnostics only, not clearance to collect")
        results.append(False)
    elif s.target_repo is None:
        results.append(_fail("cannot test writes without a target repository"))
    else:
        results.append(check_write_capability(s))

    ok = all(results)
    print()
    print("PREFLIGHT: " + ("PASS — clear to collect" if ok else "FAIL — do not collect"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
