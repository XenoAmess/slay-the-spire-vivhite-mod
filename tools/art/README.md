# Ironclad art extraction helper

## EvoLink native-transparent image generation

Every new transparent Vivhite asset must use EvoLink `gpt-image-2` with
`background=transparent`. No green-screen, chroma-key, background-removal, or
alternate image service is permitted. `evolink_transparent_image.py` keeps the
API key out of arguments and files, submits the fixed transparent request, and
verifies that the downloaded result is a PNG.

Set `EVOLINK_API_KEY` only in the current environment, or omit it and enter the
key at the hidden prompt:

```powershell
py -3 -B .\tools\art\evolink_transparent_image.py `
  --prompt-file .\path\to\asset.prompt.txt `
  --output .\path\to\asset.png `
  --image-url https://example.invalid/reference-1.png `
  --image-url https://example.invalid/reference-2.jpg
```

If generation finishes but download is interrupted, reuse its task without
creating or billing another image:

```powershell
py -3 -B .\tools\art\evolink_transparent_image.py `
  --task-id task-unified-example `
  --output .\path\to\asset.png
```

Never paste an API key into either command. Preserve every raw model result,
including rejected attempts. Validate the actual Alpha channel separately;
the script deliberately does not repair or postprocess Alpha.

`extract_ironclad_assets.py` opens the installed Slay the Spire 2 PCK
read-only and reconstructs local authoring sources for Ironclad's four Spine
presentations:

- `combat/`;
- `merchant/` (its atlas is separate, but its skeleton is shared with combat);
- `rest_site/`;
- `character_select/`.

It also extracts only the approved replacement UI under `ui/`: character
icon/outline, select/locked-select portrait, map marker, and the four
multiplayer hand images under `ui/multiplayer/`. Energy-orb art, transitions,
victory art, and combat VFX are intentionally out of scope.

The default output is the repository's versioned authoring-source directory:

```text
<repository>/assets/ironclad-v0.111.0/
  manifest.json
  combat/
    scene.tscn
    combat_skeleton_data.tres
    ironclad.skel
    ironclad.atlas
    ironclad.png, ironclad_2.png, ironclad_3.png, ironclad_4.png
  merchant/
  rest_site/
  character_select/
  ui/
    icon.png, icon_outline.png, select.png, select_locked.png, map_marker.png
    multiplayer/point.png, rock.png, paper.png, scissors.png
```

Spine importer payloads are restored as authoring `.skel` and `.atlas` files.
Godot 4.5.1 decodes every `.ctex`, `.s3tc.ctex`, or `.bptc.ctex` payload to an
RGBA PNG in a system temporary project. VRAM block-compression padding is
cropped back to `Texture2D`'s logical dimensions; this matters for the
3713x2427 character-select atlas.

Inside the repository, the extractor is hard-limited to the exact
`assets/ironclad-v0.111.0` root and never writes the `Vivhite/` runtime tree.
After editing, `publish_ironclad_skin.py` reads legacy scene structure and
checksums from that immutable extraction. The custom rig builder owns the
tracked combat and character-select `.spjson`/`.spatlas`/PNG/wrapper resources;
their atlas regions and packing are not constrained to the Ironclad layouts.
The remaining rest-site authoring page plus the four explicitly exempted
multiplayer gestures come from `assets/vivhite-ironclad/custom`. The five
standalone approved UI textures come directly from
`assets/vivhite-ironclad/approved`. The publisher reads all private rig outputs
before mirror-cleaning, rewrites the remaining wrappers to private skeleton
paths, and never copies or references a vanilla skeleton in the runtime tree.

## Run

From the repository root on Windows:

```powershell
py -3 .\tools\art\extract_ironclad_assets.py
```

To discard a previous generated tree before extracting, pass
`--clean-output`. For safety, that option is accepted only for the exact
repository `assets/ironclad-v0.111.0` directory.

The script first checks `--game-dir` / `--godot`, then `STS2_DIR` /
`GODOT_EXE`, and finally `Vivhite/local.props`. Explicit paths are supported:

```powershell
py -3 .\tools\art\extract_ironclad_assets.py `
  --game-dir 'G:\SteamLibrary\steamapps\common\Slay the Spire 2' `
  --godot 'C:\path\to\Godot_v4.5.1-stable_mono_win64.exe'
```

The v0.111.0 fingerprint check fails before extraction if the installed game
does not match the researched build. `--skip-version-check` is available only
for an intentional investigation of a newer build.

The tool overwrites its known output files, but does not delete the output
directory or unrelated files. `manifest.json` records every logical source,
actual imported PCK payload, transform, checksums, decoded dimensions, PCK
directory fingerprint, and Godot decoder version. It deliberately omits local
install paths and generation timestamps so a matching extraction is stable in
version control across machines.

## Atlas region masters and deterministic repacking

`atlas_region_tool.gd` manages the four Spine texture sets only; it does not
generate or repack the standalone UI images. Run it with Godot 4.5.1 from the
repository root. The first command creates missing logical masters below the
approved custom-art tree while keeping any existing masters intact:

```powershell
$godot = 'C:\path\to\Godot_v4.5.1-stable_mono_win64_console.exe'
& $godot --headless --path .\tools\art `
  --script res://atlas_region_tool.gd -- init-all `
  --source-root assets/ironclad-v0.111.0 `
  --custom-root assets/vivhite-ironclad/custom
```

Each workspace has this shape:

```text
assets/vivhite-ironclad/custom/combat/
  ironclad.atlas              # immutable copy of the original layout
  atlas-layout.json           # dimensions, bounds, rotation, offsets, hashes
  regions/                    # unrotated, trimmed logical region masters
    attack/...
    sword blade.png
    sword_handle.png
  spell_layers/               # optional; created by the artist when needed
    sword blade.png
  ironclad.png ...            # produced by pack
  atlas-pack-report.json
```

The legacy-layout workspaces also include `merchant/`, `rest_site/`, and
`character_select/`, but character-select production no longer uses its
Ironclad layout: its private rig builder emits a new atlas and regions directly.
A logical master normally has the unrotated width and
height from its atlas `bounds`. A differently sized replacement is allowed:
the packer resamples it to that region's exact logical bounds, applies the
original `rotate:90`, and writes it to the original packed rectangle. This is
why combat and merchant must be packed region by region rather than by scaling
whole pages: their region names match, but many rotation and packing choices
differ.

Re-run `init-all` to add any missing masters. It never overwrites an existing
master unless `--replace-masters` is explicitly supplied. Atlas text is
protected by its initialization hash; `pack` fails if page names, dimensions,
bounds, rotations, offsets, or any other atlas text changed. To intentionally
accept a newly researched layout, initialize it with `--force-layout`.

Pack one workspace with empty hands (the production default):

```powershell
& $godot --headless --path .\tools\art `
  --script res://atlas_region_tool.gd -- pack `
  --workspace assets/vivhite-ironclad/custom/combat `
  --weapon-policy clear
```

`clear` forces both `sword blade` and `sword_handle` to alpha zero, regardless
of their logical masters. `spell` also forces the handle to alpha zero, but
may read `spell_layers/sword blade.png` as a magical projection and clamps its
alpha to 191. A missing spell layer becomes transparent. The tool therefore
cannot accidentally restore an opaque held weapon. The extracted
character-select `top arm` region is research evidence only; it must not be
repacked into the private White Qi character-select atlas.

Verify the unpack/unrotate/rotate/repack implementation against every tracked
template in an ignored work directory:

```powershell
& $godot --headless --path .\tools\art `
  --script res://atlas_region_tool.gd -- verify-all `
  --source-root assets/ironclad-v0.111.0 `
  --work-root .work/atlas-region-roundtrip
```

The verifier's internal preserve mode is not available to production packing.
It requires the copied `.atlas` bytes and every reconstructed page pixel to be
identical; it also reports whether the PNG encoding itself is byte-identical.
Choose an unused work directory, or pass `--force-work` to overwrite only the
tool's known verification artifacts there.

## Retired legacy art pipeline

The former 190-region / ten-page workflow is permanently retired. It combined
checkerboard-descended AI RGB with original Ironclad Alpha and pose geometry,
then used chroma-key and Alpha-repair code for UI. That violates both the clean
image lineage and custom-rig requirements.

The old sources, products, reports, and executable scripts are preserved only
under `assets/vivhite-ironclad/legacy-contaminated/2026-08-27/`. Do not move
`build_vivhite_gameplay_regions.gd`, `process_vivhite_ui.gd`, or
`remove_chroma.gd` back into `tools/art`, and do not restore their old commands.

The replacement pipeline starts with archived EvoLink native-transparent
outputs and builds a private Vivhite skeleton, mesh, weights, poses, atlas, and
UI without deriving Alpha or body geometry from Ironclad.

## Build the private character-select rig

The character-select hero uses a dedicated Vivhite Spine 4.2.43 JSON rig. It
does not reuse the Ironclad skeleton, mesh, weights, animation transforms, or
atlas regions. Its hero and independently generated magic-sigil masters remain
read-only below `assets/vivhite-ironclad/custom/character_select/sources/`.

Run the deterministic builder from the repository root with Godot 4.5.1:

```powershell
& $GodotExe --headless --path .\tools\art `
  --script res://build_vivhite_character_select_rig.gd -- build-character-select
```

The builder crops transparent padding, uniformly downsizes when necessary,
and places the unchanged RGBA content on the fixed 3713x2427 private atlas
page. It performs no Alpha extraction or repair. The private runtime output is
written to `Vivhite/Vivhite/skins/ironclad/spine/character_select/`: one atlas
page, one `.spatlas`, one `.spjson`, and one skeleton-data `.tres`.

After the builder rewrites the atlas PNG, run a Godot editor import before
previewing so `.godot/imported` cannot retain a stale hero-only `.ctex`:

```powershell
$env:DOTNET_ROOT = "C:\Users\xenoa\AppData\Local\Microsoft\dotnet"
& $GodotExe --headless --editor --path .\Vivhite --import
```

The JSON contains exactly one 5.3333335-second animation named `animation`, as
required by `NSpineAutoPlayer`. Its 9x13 hero mesh has 117 weighted vertices,
192 triangles, a 40-vertex hull, and separate Vivhite influences for torso,
head, hair, butterfly, both arms, skirt, and both legs. The magic sigil is a
separate rigid region attachment on its own rotating bone behind the hero; its
glow is never baked into deforming body joints. With the existing scene's
`SpineSprite` position `(-185, -20)` and scale `0.46`, the setup mesh stays in
the researched right-side hero area at `x=2213..4385`, `y=-2401..-121`. This is
five percent smaller than the original attachment union so hair and butterfly
retain a visible top margin on the 2560x1200 canvas.

### Preview only the private character-select rig

The character-select rig can be rendered before the other skin sets exist. The
preview mounts `SlayTheSpire2.pck` read-only for the game's Spine extension,
loads and instantiates the real private `character_select.tscn` on a 2560x1200
canvas, and writes only below `.work`. It never starts or modifies the game and
never edits the source image, atlas, or Alpha channel. There is no synthetic
bare-`SpineSprite` fallback.

Run this with the real Vulkan display driver (not `--headless`):

```powershell
$previewScript = (Resolve-Path `
  .\tools\art\render_vivhite_character_select_preview.gd).Path
& $GodotExe --path (Resolve-Path .\Vivhite).Path `
  --rendering-driver vulkan `
  --script $previewScript -- `
  --pck "G:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.pck" `
  --scene "res://Vivhite/skins/ironclad/scenes/character_select.tscn" `
  --resource "res://Vivhite/skins/ironclad/spine/character_select/character_select_skeleton_data.tres" `
  --output ".work/vivhite-character-select-preview"
```

The command captures five evenly spaced frames from `animation` over
5.3333335 seconds and writes `frames/*.png` plus `report.json`. It fails if the
resource is not a private Spine 4.2.43 `.spjson` rig with exactly the one
required animation, if the real scene does not reference that exact resource,
if `NSpineAutoPlayer` is not the direct scripted child of `SpineSprite`, if any
frame is empty or touches the canvas boundary, or if all five rendered frames
are pixel-identical. A standalone Mod project cannot register the game's C#
class from `sts2.dll` as its own script class, so the preview records that
known limitation and explicitly selects the scene's sole animation; actual
`NSpineAutoPlayer._Ready` execution is verified in game. The first and last
samples may match because they are the endpoints of a closed loop.

## Build the private combat and merchant rig

Combat uses `build_vivhite_combat_rig.gd`; it reads the accepted body and
magic-arc masters from `assets/vivhite-ironclad/custom/combat/sources/` and
reuses the accepted character-select sigil as a separate spell layer. All
three inputs must already be native RGBA8 with zero-Alpha corners. A missing
input fails closed; the builder never substitutes legacy art or repairs Alpha.

```powershell
& $GodotExe --headless --path .\tools\art `
  --script res://build_vivhite_combat_rig.gd -- build-combat
```

The deterministic output is one private 3072x2304 atlas plus Spine 4.2.43
JSON and wrapper under `Vivhite/Vivhite/skins/ironclad/spine/combat/`.
Vivhite is one continuous 15x23 mesh (345 weighted vertices, 616 triangles)
driven by 25 body controls in a 30-bone rig. It never imports Ironclad bones,
weights, meshes, transforms, or a weapon pose. The atlas also contains rigid
magic-arc and sigil attachments so glow never becomes a deforming joint seam.

The rig contains exactly the eight game animations at the v0.111.0 durations:
`idle_loop` 2.0s, `low_health_loop` 1.4666667s, `relaxed_loop` 12.000001s,
`attack` 1.1666667s, `attack_heavy` 1.5333334s, `cast` 1.5666667s, `hurt`
1.0s, and `die` 2.3333335s. Its attack/heavy/cast events occur at 0.15s,
0.20s, and 0.25s respectively, matching the character-code animation delays.
`relaxed_loop` is closed at its 12-second boundary so the merchant may enter
at any phase without a visible pop.

The combat scene retains the original `Visuals/NIroncladVfx`,
`Visuals/SlashVfxSlot`, and `Visuals/EyeSlot/EyeFire` chain, shader step values,
and layout anchors while binding only the private skeleton. The generated
magic ribbon is attached directly to required slot `slash_mesh`, so the
Spine slot consumer and the private arc share one hand anchor instead of
drawing detached or doubled weapon-like geometry. Its consumer
materials replace Ironclad red/orange with violet/indigo/cyan; the separate
arc and sigil art supplies the restrained gold detail. The merchant's
first child remains its `SpineSprite`, uses lowercase `default`, and points to
a wrapper that deliberately shares this combat skeleton and atlas.

## Publish edited assets

After building all private rigs and preparing the approved UI sources, run from
the repository root:

```powershell
py -3 .\tools\art\publish_ironclad_skin.py
cd .\Vivhite
dotnet build
```

The publisher writes the 26 runtime resources below
`Vivhite/Vivhite/skins/ironclad/`. It strictly decodes every RGBA8 PNG and
refuses wrong dimensions or any protected image whose decoded pixels still
match the extracted game asset, even after a lossless re-encode. The remaining
legacy rest-site atlas text must remain byte-for-byte identical to its versioned
template; character-select uses its own private atlas and arbitrary private
region names. Generated private rig inputs are selected with
`--private-runtime-root` (the tracked runtime tree by default), validated, and
read fully before the destination is cleaned. Combat and merchant deliberately
share the same private JSON, atlas, and page so every `pose_*` attachment
resolves. Character-select must expose exactly one animation named `animation`,
as required by the game's `NSpineAutoPlayer`. The destination is mirrored to
the exact 26-file allowlist, so stale
debug/import files cannot silently enter the PCK. Extracted `.skel` files remain
read-only research references and are never copied or referenced by the Mod.
The character-select scene is also scrubbed of serialized editor-preview
`SpineMesh2D` children; its replacement mesh must come from the private JSON.

The source roots are intentionally independent: `--template-root` (with the old
`--authoring-root` spelling retained as an alias) defaults to the immutable
`assets/ironclad-v0.111.0`, while `--art-root` defaults to
`assets/vivhite-ironclad/custom` and `--approved-root` defaults to
`assets/vivhite-ironclad/approved`. Publishing never requires overwriting the
tracked template or duplicating approved UI into the custom tree.

A local conversion preview is available without touching the mod tree:

```powershell
py -3 .\tools\art\publish_ironclad_skin.py `
  --destination .\.work\ironclad-runtime-preview `
  --allow-unchanged
```

`--allow-unchanged` is restricted to destinations below `.work`; it cannot be
used to put unmodified game art in the distributable Mod.

## Editing notes

- The replacement is a private White Qi rig, not a texture-only reskin. Do not
  fit new art to, reference, or publish an original Ironclad skeleton.
- Every runtime skeleton is Spine JSON 4.2.43. Combat and merchant share
  `vivhite_combat.spjson`; rest-site and character-select have separate JSON.
- Godot export must keep private `.spjson`/`.spatlas`/`.tres`/`.tscn` files
  readable so the post-export validator can verify the complete reference
  graph. `Vivhite/project.godot` and the build gate enforce this.
- A rebuilt skeleton should preserve the animation names listed in the
  manifest. Reusing Ironclad's combat scene also requires its Spine VFX slots
  and event names.
- Do not copy the game's `.import` hashes or UIDs into the mod project.

Keep the repository containing extracted Mega Crit assets private unless their
redistribution is authorized. Review the applicable game-art and Spine Runtime
terms before publishing derived files.
