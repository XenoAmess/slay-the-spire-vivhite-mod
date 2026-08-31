# `energy_big.png` consumer evidence

## Asset classification

`energy_big.png` is one standalone transparent `Texture2D`, not an atlas page,
atlas region, spritesheet, or animation frame. This task derives it from five
already-approved runtime layers; it performs no AI generation and no creative
image edit.

## Pool mapping

All three Vivhite content pools map their large energy icon to the same file:

- `Vivhite/VivhiteCode/Characters/VivhiteCardPool.cs:19`
- `Vivhite/VivhiteCode/Characters/VivhiteRelicPool.cs:13`
- `Vivhite/VivhiteCode/Characters/VivhitePotionPool.cs:13`

Each returns:

```text
res://Vivhite/images/characters/energy_big.png
```

RitsuLib `0.5.14` patches the string overload of
`MegaCrit.Sts2.Core.Helpers.EnergyIconHelper.GetPath`. Its prefix looks up the
pool's `IModBigEnergyIconPool.BigEnergyIconPath`; on a match it assigns that
path as the result and skips the original helper. It does not reinterpret the
five combat-counter layers as the large icon.

The unpatched game helper resolves
`images/atlases/ui_atlas.sprites/card/energy_<lowercase>.tres`. PCK evidence for
the comparable vanilla assets is:

- Ironclad: atlas region `Rect2(1440, 1948, 74, 74)`.
- Silent: atlas region `Rect2(1182, 630, 74, 74)`.
- Defect: region `Rect2(237, 879, 71, 72)` with
  `margin = Rect2(1, 1, 3, 2)`, giving a `74×74` logical texture.

Those values establish the vanilla display texture's logical card-UI size.
Vivhite's standalone source-canvas contract remains the project's explicit
`256×256 RGBA8` contract: `tools/art/audit_vivhite_runtime_art.gd` checks that
exact size, native format, transparent corners, and non-edge-touching Alpha.
The prior runtime placeholder at the same path was also `256×256`; this task
changes only its pixels, not its consumer or dimensions.

## Five-layer runtime scene

`Vivhite/Vivhite/scenes/characters/Vivhite_energy_counter.tscn` uses a
`128×128` counter control and five `256×256` source textures with `expand_mode`
enabled. Scene-tree draw order is exactly:

```text
Layer1 -> Layer2 -> Layer3 -> Layer4 -> Layer5
```

`Layer2` and `Layer3` are children of `RotationLayers`; setup pose is rotation
zero for both. Therefore a same-size `256×256` SourceOver composition in that
order is a valid deterministic static representative for the mapped large
energy texture. No VFX node or numeric `3/3` label is included in
`energy_big.png` because the requested derivation is explicitly from the five
orb image layers only.

## Derivation decision

The consumer evidence permits the derivation. The script retains every source
at `256×256 RGBA8`, applies setup-pose rotation `0`, and performs only Godot's
standard `Image.blend_rect` SourceOver. It performs no crop, resize, threshold,
mask, color key, Alpha cleanup, edge contraction, recolor, or redraw.

