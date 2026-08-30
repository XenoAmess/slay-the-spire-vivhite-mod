# Vivhite

Languages: [中文](README.md) | English

`Vivhite` is a custom character mod for Slay the Spire 2. Vivhite is a magical girl and master magician with deep knowledge of mathematics, computing, and art. She treats health as material for magical calculation and fights through a “spend health to cast → heal through kills or Drain → keep casting” loop.

This README describes the approved `0.2.0` implementation contract. See [Vivhite Character and Alternating Brain Implementation](../docs/2026-08-30-白绮角色与轮换大脑实现.md) for the complete 61-card catalog, exact values, and runtime checks that remain outstanding; this README does not claim that those checks have been completed.

**Character summary:**

- Starting stats: `78` max HP, `99` gold, `3` energy per turn, and `5` cards drawn per turn.
- Starter deck: 4 × Luminous Projection, 4 × Closed-Domain Mapping, and 1 × Vivhite's Transformation Formula.
- Starter relic: Solitary Crown — whenever any enemy dies, immediately heal `5%` of Max HP, rounded up; each death of one entity resolves only once.
- A dedicated `61`-card pool: 3 basic, 18 common, 24 uncommon, and 16 rare cards.
- Three primary builds: Conservation Geometry, Recursive Star Calculus, and Crimson Integral, plus cross-build cards.
- Every card currently uses RitsuLib placeholder art; no card art is generated in this phase.

## Learning Resources

- [STS2-RitsuLib](https://github.com/BAKAOLC/STS2-RitsuLib): the base library used for content registration, character integration, and Godot resources.
- [RitsuLib Documentation](https://github.com/GlitchedReme/SlayTheSpire2ModdingTutorials/tree/master/RitsuLib): tutorials and examples organized by file.
- [Slay the Spire 2 Modding Tutorials](https://glitchedreme.github.io/SlayTheSpire2ModdingTutorials/index.html): the full tutorial site.

## Install and Use

### Option A: build from source (recommended)

1. Install Slay the Spire 2 and prepare Godot 4.5.1 Mono, .NET 9, and RitsuLib.
2. Create `local.props` and configure the local paths described below.
3. Run `dotnet build .\Vivhite.csproj` from this directory. A full build creates and deploys the DLL, manifest, and PCK.
4. Confirm that the game's `mods` directory contains both `Vivhite` and its `STS2-RitsuLib` dependency.

### Option B: install build artifacts

Place all three artifacts in `<game directory>\mods\Vivhite\`:

- `Vivhite.dll`
- `Vivhite.json`
- `Vivhite.pck`

Install the `STS2-RitsuLib` version declared by the manifest as well. The game must be started with Vulkan; use this Steam launch option:

```text
%command% --rendering-driver vulkan
```

If the game directory already contains `launch_vulkan.bat`, that wrapper can be used instead.

## Local Path Configuration

```powershell
Copy-Item .\local.props.template .\local.props
```

Set these values in `local.props` (the file is ignored by Git and must not be committed):

| Field | Description |
|---|---|
| `Sts2Dir` | Slay the Spire 2 installation directory |
| `Sts2DataDir` | Game DLL directory, usually `$(Sts2Dir)/data_sts2_windows_x86_64` |
| `GodotExe` | Godot 4.5.1 Mono executable used to export the PCK |
| `RitsuLibDeployDir` | Local RitsuLib deployment directory, defaulting to `$(Sts2Dir)/mods/STS2-RitsuLib`; this is not this mod's output directory |

## RitsuLib Version Compatibility

> **Align the manifest and csproj before every release.**
>
> `dependencies[STS2-RitsuLib].version` in `Vivhite.json` must match the `STS2.RitsuLib` version actually used by the `.csproj`. The build synchronizes that dependency version, while `min_game_version` still requires manual review.

### Current version snapshot (2026-08-30)

| Item | Value |
|---|---|
| Target game | Slay the Spire 2 `0.111.0` |
| Engine / SDK | Godot 4.5.1 Mono / `Godot.NET.Sdk` 4.5.1 |
| Target framework | `.NET 9` / `net9.0` |
| RitsuLib | `0.5.14` |
| Vivhite implementation | `0.2.0` |

### Version mapping

| RitsuLib version | Target STS2 version | Project status |
|---|---|---|
| `0.5.14` | `0.111.0` | Current compile baseline |

Before selecting another version, consult the [STS2-RitsuLib releases](https://github.com/BAKAOLC/STS2-RitsuLib/releases) and the matching game branch. Do not assume that old APIs or compatibility packages remain drop-in replacements.

### Package selection

The project pins the current mainline package:

```xml
<PackageReference Include="STS2.RitsuLib" Version="0.5.14" GeneratePathProperty="true" />
```

Enable only one mainline or compatibility package at a time. When switching packages, recheck the game version, public APIs, manifest dependency, and in-game loading behavior.

### Pre-release checklist: version alignment

1. After building, confirm that `dependencies[STS2-RitsuLib].version` in `Vivhite.json` matches the resolved NuGet version.
2. Confirm that `min_game_version` matches the target game branch.
3. Confirm that the DLL, JSON, and PCK are deployed to the same `mods/Vivhite` directory.
4. Launch with Vulkan and use the actual game log to confirm that both the dependency and mod are recognized.

### Upgrade notes

- The current baseline is STS2 `0.111.0`, RitsuLib `0.5.14`, and Godot 4.5.1 Mono.
- After upgrading RitsuLib or the game, rebuild and inspect card commands, hooks, character resource profiles, and PCK export behavior.
- `Vivhite.json` controls runtime dependency checks, while `.csproj` controls compile-time dependencies; both paths must be updated.

## Build

| Command | Behavior |
|---|---|
| `dotnet build .\Vivhite.csproj` | Full build: compile + `CopyMod` + `ExportPCK` |
| `... /p:RunPckExport=false` | Skip PCK export |
| `... /p:CopyModOnBuild=false` | Skip copying to the game's mods directory; output stays in `bin/` |
| `... /p:RunPckExport=false /p:CopyModOnBuild=false` | C# compile check only |

A full build runs these targets after `Build`:

- **`CopyMod`**: copies the DLL and manifest to the game's `mods/Vivhite` directory.
- **`ExportPCK`**: invokes `GodotExe` and exports the PCK to the same mod directory.

> `RitsuLibDeployDir` controls only the deployment location of RitsuLib itself. This mod's DLL, manifest, and PCK are controlled by `ModOutputDir`, which defaults to `$(Sts2Dir)/mods/$(MSBuildProjectName)`.

## Directory Layout

```text
Vivhite/
├── VivhiteCode/   # C# character, cards, relics, and combat rules
├── Vivhite/       # Godot resources and bilingual localization
├── Vivhite.csproj
├── Vivhite.json   # Mod manifest
├── project.godot
└── local.props.template
```

`res://Vivhite/...` is the Godot/PCK resource path mapped to the repository's `Vivhite/` resource directory; it is not a C# namespace.

## Vivhite Content

### Character configuration

| Property | Value |
|---|---|
| Type | `VivhiteCharacter` |
| Character ID | `VIVHITE_CHARACTER_VIVHITE_CHARACTER` |
| Starting stats | 78 max HP, 99 gold, 3 energy, 5 cards drawn per turn |
| Starter deck | 4 × Luminous Projection, 4 × Closed-Domain Mapping, 1 × Vivhite's Transformation Formula |
| Starter relic | Solitary Crown: heal 5% of Max HP, rounded up, whenever an enemy dies |
| Card pool | 61 cards: 3 basic, 18 common, 24 uncommon, 16 rare |

### Card pool and three builds

| Build | Primary direction |
|---|---|
| Conservation Geometry | Use Margin to offset Life Calculation, permanently grow max HP, and turn overhealing into resources |
| Recursive Star Calculus | Increase damage, on-kill healing, card draw, and energy chains |
| Crimson Integral | Combine multi-hit damage with Drain above 100% to create damage, healing, Block, and Strength loops |

Cross-build cards connect Margin, draw, kills, and Drain, including Vivhite's Crimson Transformation Ritual, whose attack cost and damage scale without a cap each turn. The [full implementation document](../docs/2026-08-30-白绮角色与轮换大脑实现.md) lists all 61 IDs, costs, effects, and upgrades. The old Vivhite Strike, Vivhite Defend, and White Silk Knot were discarded demo content and are not part of this pool.

### Core keywords

| Keyword | Semantics |
|---|---|
| `Life Calculation N` | Before the card resolves, lose N unblocked HP unaffected by Strength; the card is unplayable if payment would leave the player below 1 HP |
| `Margin N` | Automatically offsets Life Calculation one-for-one and is consumed |
| `Dimension Up N` | Permanently gain N max HP and gain the same amount of current HP |
| `Drain N%` | Heal from the actual enemy HP lost to that attack card times total Drain; aggregate multi-hit and AoE damage before rounding once |
| `Lethal` | Triggers when that card's damage directly kills its target |

Card-specific and global Drain are added as percentage points. Drain excludes blocked damage, overkill, self-damage, Thorns, and damage from non-attack cards.

### No artificial caps

Vivhite has no custom hard cap on max-HP growth, Margin, kill healing, Drain percentage, Drain healing, Strength, draw growth, or any other scaling counter. Generated cards, copies, repeated resolutions, and cards recovered from discard or exhaust have the same rights as original cards and can trigger permanent Dimension Up. Drain may exceed `100%`.

Only natural engine invariants remain:

- Current HP cannot exceed max HP.
- Actual Life Calculation cost has a minimum of 0.
- A card cannot be played if paying its cost would leave the player below 1 HP.
- Hand size and similar state continue to follow native game rules.
- The same death event for one enemy resolves once; this is event deduplication, not a healing cap.

### Shared V3 skin and placeholder card art

The independent Vivhite character and the Ironclad replacement skin use the same current Vivhite V3 five-page combat atlas, together with the matching merchant, rest-site, character-select, UI, Spine, and multiplayer resources. They retain separate character IDs, card pools, character state, and statistics; shared visuals do not merge their gameplay identities.

All 61 cards currently use RitsuLib placeholder card art. This implementation phase does not generate images, and it does not overwrite or regenerate existing Vivhite creative assets.

## Manifest Format

`Vivhite.json` is the mod manifest. The key fields for the `0.2.0` implementation are:

```json
{
  "id": "Vivhite",
  "name": "白绮 Vivhite",
  "pck_name": "Vivhite",
  "author": "VivhiteMod",
  "description": "Adds Vivhite, a magical-girl character with 61 cards, three builds, and uncapped health-magic loops.",
  "version": "0.2.0",
  "has_pck": true,
  "has_dll": true,
  "affects_gameplay": true,
  "min_game_version": "0.111.0",
  "dependencies": [
    { "id": "STS2-RitsuLib", "version": "0.5.14" }
  ]
}
```

### Field reference

| Field | Description |
|---|---|
| `id` | Must match `Entry.ModId` and the deployment directory |
| `pck_name` | Must match the exported `.pck` file name |
| `version` | SemVer version of the current Vivhite implementation |
| `has_pck` / `has_dll` | This mod distributes both resources and a code assembly |
| `affects_gameplay` | Must be `true` because Vivhite adds independent gameplay content |
| `min_game_version` | Minimum compatible STS2 version; keep it aligned with the compile target |
| `dependencies` | Runtime dependencies; the RitsuLib version must match the NuGet compile version |

## Development Tips

- Content IDs follow `{MODID}_{category}_{original name}`; full card IDs use `VIVHITE_CARD_<ID>`.
- New character content belongs to Vivhite's own pools and state. Do not write it into the Ironclad identity merely because the skin is shared.
- Character visuals must use the current V3 five-page Vivhite skin and must not fall back to the legacy single-page atlas or a separate static combat placeholder.
- Cards use placeholder art for now; code and documentation work must not trigger image generation.
- Balance changes may adjust energy, HP cost, base values, scaling, rarity, and Exhaust, but must not reintroduce artificial caps.
- Resource paths must begin with `res://`; verify directory names and case inside the PCK.
