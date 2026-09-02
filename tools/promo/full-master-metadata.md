# Full-master run metadata

`finalize_full_master_metadata.py` creates immutable, hash-bound sidecars for
one already-rendered run. It is deliberately downstream of recording and
rendering: it never starts OBS or the game, invokes OCR/TTS, or marks a claim
true. It also never performs `signoff` or `export`.

1. Copy the closed OBS recording and its `ffprobe` JSON into the run's
   `raw/`/`renders/` directories. Keep failed and partial files in the same
   attempt.
2. Write a new JSON spec inside the run (the plan at
   `runs/<run-id>/notes/full-master-metadata-plan.json` describes the required
   fields). Each artifact needs an ID, normalized run-relative path, media
   type, and category. Do not provide bytes or hashes: the finalizer computes
   them from the files it reads.
3. Run from the repository root:

   ```powershell
   py -3 -B tools/promo/finalize_full_master_metadata.py `
     --spec tools/promo/runs/<run-id>/notes/full-master-metadata-spec.json
   ```

The command writes, only if none already exists:

* `run-manifest.json`;
* `review/full-master-artifact-index.json`;
* `review/full-master-evidence-coverage.json`.

If any output exists, the command fails rather than overwriting an audit
record. Use a new `run-id`/attempt for a changed recording or edit. A visual
screen capture is classified as an observation, not as an STS2 state/action
receipt. A semantic `passed` shot is accepted only when a bound semantic audit
JSON explicitly reports pass; absent runtime evidence remains `pending` or
`blocked`. The delegated review mode records the user's workflow instruction
without claiming that an independent 1.0x watch occurred.
