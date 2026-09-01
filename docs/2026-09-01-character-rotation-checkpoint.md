# Character rotation checkpoint and active-run journal boundary

Date: 2026-09-01

## Problem

The terminal flow persists a run and profile statistics, advances
`knowledge/character_rotation.json`, and then invokes the default automatic
checkpoint. The old default path set omitted the global rotation file. A
checkpoint could therefore publish profile results without the matching
scheduler state.

Review work can overlap the terminal write. Its concurrent-state list also
needs the same global rotation file.

The root and per-profile `.active_run_learning.json` files are active-run
transaction journals. They hold the pre-run baseline and fail-closed manual
takeover exclusion. They are runtime evidence, not durable learning output.

## Resolution

- Add only the root `character_rotation.json` to the default checkpoint.
- Protect that same global file in fallback and profile-aware review paths.
- Classify rotation and active-run journals as online runtime.
- Ignore the exact root and one-level profile journal paths.
- Keep profile-local `character_rotation.json` outside the checkpoint; the
  root file remains the sole authority.
- Add tests for checkpoint inclusion, profile isolation, and review rejection.

The ignore rules are intentionally narrow. They do not hide runs, stats,
progression, policy, lessons, queues, or the global rotation state.

## Verification

From `sts2-ascend`:

```powershell
py -3 -m unittest tests.test_nested_profile_paths tests.test_llm_profile_isolation tests.test_review_path_classifier
```

All 27 tests passed. An earlier extended `test_autogit_safety` run passed
66/67 initially because one Windows temporary-directory `os.replace` call
returned `WinError 5`; the exact failing test passed on immediate rerun.

## Operational note

Do not manually edit or delete active-run journals. Normal terminal
persistence and the existing fail-closed lifecycle own their cleanup.
