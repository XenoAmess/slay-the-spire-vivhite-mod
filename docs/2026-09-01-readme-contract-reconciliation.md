# README contract reconciliation

Date: 2026-09-01

## Problem

Several README edits mixed current facts with earlier implementation states.
The main drifts were the historical `89/89` art count, per-file deployment
wording, old Drain conversion prose, incomplete catch-up rotation semantics,
and treating `summary_ready` as if it proved native save persistence. The
ASCEND-VISION section also described two simultaneous profile dashboards and a
five-run moving average that the current UI does not implement.

The simplified manual-takeover prose omitted the persistent exclusion journal,
same-run F10 no-learning rule, and fail-closed restart behavior. The daily
Bilibili watcher implementation exists, but the local scheduled task is not
currently installed, so the README must describe installation rather than
claim current machine state.

## Resolution

- Document the exact `92/92` runtime bitmap inventory and same-batch atomic
  DLL/manifest/PCK deployment contract.
- Describe Drain as one aggregate recovery request with one final ceiling.
- Lock catch-up to pre-balance VVVVI; the first equalizing Vivhite terminal is
  followed by Ironclad and permanent strict 1:1 alternation.
- Separate `summary_ready` from the read-only `progress.save` JSON equivalence
  check and the exact `verified/true/null` terminal barrier.
- Restore the durable manual-takeover exclusion and rollback contract.
- Match the viewer: one active-profile dashboard, a 40-run trend with a 20-run
  moving average, and a cross-profile ratio only after both have 20 samples.
- Describe the watcher as a task registered by the installer.
- Restore the Chinese Solitary Crown text's explicit ceiling-rounding phrase.

## Verification

The Brain rotation, dashboard, floor-statistics, card-statistics, and manual
control suites passed 77/77 tests. The compiled Vivhite acceptance runner then
passed all 64 checks, including the exact 61-card catalog, Solitary Crown
rounding, the 92-file art inventory, V3 skin ownership, and the card-trail VFX.

The ignored `third_party/STS2-Agent` checkout remains on the user's
`fix/event-option-localization` branch. It was not switched or rewritten; the
documented GAME_OVER implementation is on that fork's local and remote main.

## Lesson

README reconciliation must follow executable consumers and regression tests,
not the newest-looking prose. Machine installation state also must not be
generalized from an installer script.
