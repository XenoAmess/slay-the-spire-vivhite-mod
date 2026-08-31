# Static visual assessment

Status: **main-agent visual pass; archived**

The main agent visually confirmed that the five-layer setup-pose composition
is clear, the open center is suitable for the energy-cost number overlay, and
the transparent edge has no visible rectangular pollution. This review closes
the static asset archive; no pixel change or PNG re-encoding followed it.

- Runtime and archived output are byte-identical `256×256 RGBA8` PNGs.
- SHA-256: `ca117da971f5999b3075238283979cbca423c07b7137a1692e00288e3ebe3df0`.
- Corner Alpha: `[0, 0, 0, 0]`.
- Nonzero-Alpha bbox: `[28, 26, 191, 219]`; it does not touch any edge.
- The setup-pose orb remains centered and legible at `256`, `64`, and `32`
  pixels on black, white, and game-indigo `#182139` backgrounds.
- No rectangular halo, canvas-shaped haze, edge pollution, or visible
  overexposure appears on any checked background or size.
- The open center, blue-violet rings, gold-white crown geometry, and side
  butterflies remain distinguishable at small sizes.
- No source layer was altered. The output is a direct
  `Layer1 -> Layer2 -> Layer3 -> Layer4 -> Layer5` setup-pose SourceOver.

The 60 files under `five-layer-runtime-timeline/` are byte-identical copies of
the existing `.tmp/energy-composite` evidence for six real rotation timepoints
(`0`, `0.25`, `0.5`, `1`, `2`, `3` seconds), including actual `128` renders and
black/white/game-indigo renders at `128`, `64`, and `32`. Independent SHA-256
comparison found `60/60` exact matches and zero mismatches. They are recorded
as prior five-layer runtime consumer acceptance evidence, not newly rendered
or re-encoded files.
