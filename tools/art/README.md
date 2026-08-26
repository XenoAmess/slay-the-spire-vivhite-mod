# Ironclad art extraction helper

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
After editing, `publish_ironclad_skin.py` turns the authoring files into private
`.spskel` and `.spatlas` resources, rewrites skeleton-data/scene paths, and
stages them for the mod.

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

## Publish edited assets

After replacing/re-exporting all character art in the five authoring domains,
run from the repository root:

```powershell
py -3 .\tools\art\publish_ironclad_skin.py `
  --authoring-root .\assets\ironclad-v0.111.0
cd .\Vivhite
dotnet build
```

The publisher writes the 33 runtime resources below
`Vivhite/Vivhite/skins/ironclad/`. It refuses to install any skeleton or image
whose checksum still matches the extracted game asset. A local conversion
preview is available without touching the mod tree:

```powershell
py -3 .\tools\art\publish_ironclad_skin.py `
  --destination .\.work\ironclad-runtime-preview `
  --allow-unchanged
```

`--allow-unchanged` is restricted to destinations below `.work`; it cannot be
used to put unmodified game art in the distributable Mod.

## Editing notes

- Use Spine Editor/export runtime 4.2.x for these `.skel` files.
- For a texture-only reskin, keep atlas page names, dimensions, region layout,
  and skeleton attachments unchanged.
- A rebuilt skeleton should preserve the animation names listed in the
  manifest. Reusing Ironclad's combat scene also requires its Spine VFX slots
  and event names.
- Do not copy the game's `.import` hashes or UIDs into the mod project.

Keep the repository containing extracted Mega Crit assets private unless their
redistribution is authorized. Review the applicable game-art and Spine Runtime
terms before publishing derived files.
