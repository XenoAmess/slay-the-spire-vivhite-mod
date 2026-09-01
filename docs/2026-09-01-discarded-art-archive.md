# Discarded Vivhite art archive verification

Date: 2026-09-01

## Outcome

The append-only archive under
`assets/vivhite-ironclad/generated/discarded/` is safe to version as a
complete audit record. It contains 16 generation batches, 217 files, 106 PNG
files, and 88,541,450 bytes.

Each batch retains `original.png`, the verbatim prompt, generation metadata,
and either an assessment or evidence audit. The archived batch files were
compared with their tracked source generation records: all 216 duplicated
batch files are byte-identical. All declared prompt, image, and reference-image
SHA-256 values resolve and match.

## Status boundary

Eleven batches are explicitly rejected or not for runtime. Three are
superseded or not selected. The interrupted Scale Transformation attempt is
retained as an uninspected, non-adopted generation record. The first Divide and
Conquer Circle attempt preserves its historical acceptance note, but later
tracked evidence explicitly supersedes that image because the floating book
violated the character contract; the current runtime image has a different
hash.

The archive does not rewrite those historical judgments. Its README makes the
operational rule explicit: archived material cannot enter runtime assets and
cannot be used as a later generation reference.

## Validation

- No API keys, authorization headers, private keys, signed URLs, or ordinary
  URLs were found in the non-image records.
- All 16 generation JSON files parse.
- The largest individual file is 3,461,026 bytes.
- Nine historical logs retain old D-workspace evidence paths. They are
  immutable provenance, not active configuration, so they remain unchanged.
- No source generation record was moved, overwritten, or deleted.

This preserves failed paid work and design evidence without confusing it with
the accepted runtime asset chain.
