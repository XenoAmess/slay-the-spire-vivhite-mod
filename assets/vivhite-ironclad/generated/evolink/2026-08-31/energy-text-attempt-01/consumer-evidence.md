# `energy_text.png` consumer evidence

## Asset classification

`energy_text.png` is one standalone transparent rich-text UI icon. It is not an
atlas page, atlas region, spritesheet, animation frame, or one of the five
combat-counter layers.

The three Vivhite content pools all resolve the same file:

- `Vivhite/VivhiteCode/Characters/VivhiteCardPool.cs`
- `Vivhite/VivhiteCode/Characters/VivhiteRelicPool.cs`
- `Vivhite/VivhiteCode/Characters/VivhitePotionPool.cs`

Each `TextEnergyIconPath` returns
`res://Vivhite/images/characters/energy_text.png`.

## Base-game and RitsuLib consumption

The installed game assembly's
`MegaCrit.Sts2.Core.Localization.Formatters.EnergyIconsFormatter.TryEvaluateFormat`
builds the vanilla tag as:

```text
[img]res://images/packed/sprite_fonts/<energy-prefix>_energy_icon.png[/img]
```

For energy values one through three it repeats that tag; otherwise it writes
the numeric value next to one tag. It supplies no explicit image dimensions.

RitsuLib `0.5.14` inserts
`ModTextEnergyIconHelper.OverrideTextIconTag(prefix, defaultTag)` immediately
after the default tag is assembled. The helper maps a registered pool's
`EnergyColorName` to `IModTextEnergyIconPool.TextEnergyIconPath` and returns
`[img]<custom path>[/img]`. It changes the path only and does not resize or
reinterpret the image.

Seven same-purpose vanilla resources were read directly from the installed
game PCK with `ProjectSettings.load_resource_pack`. All decode as `24x24`
RGBA8. Exact extracted copies are under `consumer-references/base-game/`:

| File | SHA-256 |
| --- | --- |
| `colorless_energy_icon.png` | `65356d673aa7324dae66e0629bc2ac2d6114493a81f7e877e71a8ad12b671b16` |
| `defect_energy_icon.png` | `c33da1578d19dad96fdc0216f285f6ca688df37081027b6c0a20fcbf031fcb33` |
| `ironclad_energy_icon.png` | `4cd2a3ae8fbc7b4369c495597a933ac2a5eaf28dceddb64bc30f2f5375491290` |
| `necrobinder_energy_icon.png` | `d38f4a1d2b53824c8f0efb7b5d93afe72fc49e6d4fcc4409c75124b44e63ffa0` |
| `regent_energy_icon.png` | `10b37f4c73a4271b9ac9f15d61f6c2f95cc59e0e200572be397d3f39ad9f07a6` |
| `silent_energy_icon.png` | `7f1729edfd038212fde019f3a89f86f0871eccd4794384ae3e75df718f135ebf` |
| `watcher_energy_icon.png` | `88282ac3b8bc304e5cbb0d1144571e14b8e372070b32659fdda2be1bcee8e1eb` |

This establishes the runtime source size as exactly `24x24`, with a compact,
single-symbol silhouette and no internal text.

## Vivhite visual reference

The adopted five-layer energy counter uses five separate `256x256` RGBA8
textures in `Vivhite_energy_counter.tscn`, displayed in a `128x128` control.
Its static setup-pose derivative is archived here as
`consumer-references/vivhite-energy-big.png`, SHA-256
`ca117da971f5999b3075238283979cbca423c07b7137a1692e00288e3ebe3df0`.

The text icon therefore keeps only the counter's small-size visual essentials:
platinum geometry, saturated indigo/violet enamel, a cool-white/cyan star core,
and restrained antique-gold notes. The character, crown, butterflies, rotating
rings, and fine calculus lattice are deliberately omitted at `24x24`.

No image reference was transmitted to EvoLink; `output.request.json` correctly
records an empty `image_urls` array. These local files were inspected only to
freeze the consumer and style contract before writing the prompt.
