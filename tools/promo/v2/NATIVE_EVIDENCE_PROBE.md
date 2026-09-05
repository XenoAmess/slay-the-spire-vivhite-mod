# Native evidence probe

`native_evidence_probe.py` is a read-only inventory and validator for a
director-v2 promo run. It does not start or control the game, OBS, Brain, the
console, or an HTTP action endpoint. It also does not write a sidecar, alter a
take row, or infer a state transition from a video frame, screenshot, or
`godot.log`.

## What counts as native evidence

The probe treats a production take as native only when a strict v2 sidecar can
be loaded by
`vivhite_promo.action_evidence_v2.load_action_evidence`. That validator checks
the immutable, SHA-bound triad:

* `state.before` (`vivhite_promo_state_snapshot`);
* `action.receipt` (`vivhite_promo_action_receipt`) whose input origin is a
  real game-window pointer and whose outcome is applied/settled; and
* `state.after` (`vivhite_promo_state_snapshot`),

including one capture identity, observation ordering, pointer/settled frames,
monotonic times, and artifact hashes. The probe never turns the following into
native evidence: operator marks, screenshots, recorder timestamps, event/log
order, Brain/API actions, console setup, or a `strict-action-sidecar.rejected`
absence record.

## Usage

From the repository root:

```powershell
py -3 tools/promo/v2/native_evidence_probe.py `
  tools/promo/runs/run-20260903T0012-director-v2-a1 `
  --takes T07 T10 T16 T18 T19 T20 --format text
```

Use JSON when another operator needs to continue from a machine-readable
report. `--strict` keeps the same read-only behavior but returns exit code 2
if any requested attempt is not `native_valid`:

```powershell
py -3 tools/promo/v2/native_evidence_probe.py <run-root> `
  --format json --strict > native-evidence-report.json
```

The report scans matching attempt directories under `contracts/takes`,
`capture/takes`, and `evidence/takes`. Statuses are:

* `native_valid`: at least one strict sidecar loaded and all references/hash
  bindings passed;
* `native_candidate_invalid`: a non-rejected strict-looking sidecar was found
  but the v2 validator rejected it;
* `native_documents_without_sidecar`: one or more native-role documents exist,
  but no sidecar binds the complete triad;
* `operator_only`: capture bundles/marks exist but no native role documents;
* `rejected_absence_record_only`: the attempt contains only an explicit
  rejection/absence record; and
* `missing`: no evidence bundle or native artifact was found.

## Current run hand-off

On `run-20260903T0012-director-v2-a1`, the focused attempts currently resolve
to `missing`, `operator_only`, or `rejected_absence_record_only`; there is no
`native_valid` attempt for T07, T10, T16, T18, T19, or T20. T16/a22 (the latest
recorded candidate) is `operator_only`: its `operator-marks.source.json`,
`recording-marks.json`, and review files are preserved, but they are not a
native state/receipt chain. This result is diagnostic only and does not change
the run or its progress document.

## How a future take becomes loadable

The capture operator must create a new attempt directory, preserve the raw
recording, and obtain native state snapshots and a pointer receipt during that
same game run. The existing
`promo_capture_evidence_helper.ps1` may be dot-sourced to checkpoint process
identity, screenshots, and operator marks, but its own documentation explicitly
states that it never emits strict evidence. After the raw file is closed, a
reviewer must bind verified source frames and create the normal v2 sidecar with
the exact SHA/identity/timing values. Re-run this probe before asking the
production binder to consume the take.

If the action was sent through Brain/API or a console, keep it as setup or a
failed-reference record and record a fresh native pointer take; do not relabel
it. If the one-take action is visually too dense, split it into independent
subshots/takes while retaining a native triad for each formal action.
