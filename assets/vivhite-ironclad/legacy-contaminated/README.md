# Legacy contaminated art — never consume

This directory preserves rejected historical material so no user-provided or
generated image is lost. Its contents include painted checkerboards,
green-screen outputs, programmatically reconstructed Alpha, descendants that
used those images as references, legacy Ironclad-shape region transfers, and
their packed/runtime copies.

Nothing below this directory may be used as:

- an EvoLink reference image;
- an identity or pose anchor;
- a Spine texture or mesh source;
- an atlas or UI input;
- a runtime Mod resource.

The dated archive is [`2026-08-27/`](2026-08-27/README.md). It is retained for
lineage/audit only; do not restore files from it by filename or by visual
similarity.

The only closed exception is the four multiplayer gestures explicitly approved
by the user on 2026-08-28. They may be restored byte-for-byte from
`2026-08-27/custom/ui/multiplayer/` into
`../custom/ui/multiplayer/`; they must not be used as AI references, have their
Alpha rewritten, or authorize any other contaminated file.

Replacement art must start from `../references/character-design.png` and
`../references/face-reference.jpg`, then use the repository's EvoLink
`gpt-image-2` native-transparent workflow. The source, prompt, request record,
and Alpha/consumer evidence must be archived before any runtime promotion.
