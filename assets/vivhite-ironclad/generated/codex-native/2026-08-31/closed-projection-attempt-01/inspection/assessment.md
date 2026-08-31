# Closed Projection attempt 01 — evidence audit

Audit date: 2026-08-31

Result: accepted as a complete Codex-native evidence package, with the native
tool provenance limit stated below. This audit did not generate or alter any
image.

## Provenance and hash chain

- Git commit `11a1dc5174dbf4e0d049f4d928a15fb5613af357` added
  `prompt.txt`, `generation.json`, `original.png`, and the adopted runtime
  `ClosedProjection.png` together.
- Those four tracked files are unchanged from that commit.
- Every prompt, original, runtime, and reference SHA-256 declared in
  `generation.json` matches the current referenced file.
- `original.png` is `1536x1024`, 8-bit RGB, fully opaque.
- Re-running `tools/art/prepare_vivhite_card_portrait.gd` on that original
  reproduced the adopted `1000x760` RGB runtime PNG byte-for-byte:
  `207f1a5e673be31a2199c736b1f836fd7295c205be7b92ea9c516212798f809d`.

The Codex built-in image tool did not expose an internal model ID, request ID,
seed, quality field, requested output size, or raw request envelope. None is
invented here or in `generation.json`; the explicit `null` model ID and its
explanatory note are the truthful available record. The original PNG retains
its native `caBX` provenance chunk, but this audit does not claim to have
cryptographically validated that chunk.

## Deterministic inspection reproduction

The historical package did not retain its inspection GDScript. For this audit,
the contemporaneous standard card inspector at
`axiom-ring-attempt-01/inspection/inspect_candidate.gd` (SHA-256
`8ba90fb00a3b40b95523264cab4be518fc81ffdb4f394a95675b375ecefe3d50`)
was run in a disposable system-temporary Godot project against this package's
`original.png`. All six generated inspection PNGs matched the files in this
directory byte-for-byte. This identifies the derivation without pretending
that the external script was historically stored in this package.

The captured logs agree with the reproduced operation: source `1536x1024`,
centered crop `(105, 8, 1325, 1007)`, Lanczos resize, and `1000x760 RGB8`
output. Both stderr logs are genuinely empty successful-run artifacts.

## Visual review

- The accepted crop is a complete opaque scene with foreground, middle ground,
  and background depth.
- The source, directional projection body, and impact endpoint remain visible
  after the centered crop.
- The attack read remains clear in color and grayscale at `100x76`.
- Vivhite is unarmed and uses two empty-hand gestures.
- No enemy, second person, readable text, weapon, mouth-emitted magic, blood,
  liquid, or red/crimson strand near the face is present.

This is a static-art acceptance only. It does not upgrade the existing
`static_accepted_pending_game_validation` status to a claim of in-game card-frame
validation.

## Secret scan

The package's text files and PNG metadata were checked for authorization
headers, bearer tokens, API-key assignments, OpenAI-style keys, EvoLink key
names, signed URL parameters, and credential-bearing query strings. No match
was found. The PNGs contain no `tEXt`, `zTXt`, or `iTXt` chunks. The original's
`caBX` payload also produced no match for those credential patterns.
