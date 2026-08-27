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
After editing, `publish_ironclad_skin.py` reads legacy non-combat scene and
skeleton-data structure plus checksums from that immutable extraction, while
taking finished non-combat atlases, pages, and UI from
`assets/vivhite-ironclad/custom`. The custom rig builder owns the tracked
combat `.spjson`/`.spatlas`/PNG/wrapper and combat scene; rest-site and
character-select likewise supply private `.spjson` files. The publisher reads
those private rig outputs before mirror-cleaning, rewrites the remaining
wrappers to private skeleton paths, and never copies or references a vanilla
skeleton in the runtime tree.

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

The other workspaces are `merchant/`, `rest_site/`, and
`character_select/`. A logical master normally has the unrotated width and
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
cannot accidentally restore an opaque held weapon. Character-select's
composite `top arm` region contains both arm and vanilla sword, so it cannot be
cleared automatically without deleting the arm; custom art for that region
must be reviewed manually to ensure the sword is absent.

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

## Publish edited assets

After packing all finished character art into the five custom-art domains, run
from the repository root:

```powershell
py -3 .\tools\art\publish_ironclad_skin.py
cd .\Vivhite
dotnet build
```

The publisher writes the 26 runtime resources below
`Vivhite/Vivhite/skins/ironclad/`. It strictly decodes every RGBA8 PNG and
refuses wrong dimensions or any image whose decoded pixels still match the
extracted game asset, even after a lossless re-encode. Legacy non-combat atlas
text must remain byte-for-byte identical to its versioned template. Generated
private rig inputs are selected with `--private-runtime-root` (the tracked
runtime tree by default), validated, and read fully before the destination is
cleaned. Combat and merchant deliberately share the same private JSON, atlas,
and page so every `pose_*` attachment resolves. The destination is mirrored to
the exact 26-file allowlist, so stale
debug/import files cannot silently enter the PCK. Extracted `.skel` files remain
read-only research references and are never copied or referenced by the Mod.
The character-select scene is also scrubbed of serialized editor-preview
`SpineMesh2D` children; its replacement mesh must come from the private JSON.

The two inputs are intentionally independent: `--template-root` (with the old
`--authoring-root` spelling retained as an alias) defaults to the immutable
`assets/ironclad-v0.111.0`, while `--art-root` defaults to
`assets/vivhite-ironclad/custom`. Publishing never requires overwriting the
tracked template.

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
