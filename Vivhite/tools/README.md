# Ironclad skin contract tools

`Validate-IroncladSkin.ps1` is the build gate for the optional bundle at
`res://Vivhite/skins/ironclad`.

- A missing bundle, or a bundle containing only `README.md`/`.gitkeep`, is inactive and does not block normal builds.
- Once any real file (or `.enabled`) exists, all 30 logical runtime assets are required before Spine semantic checks begin.
- The private skeleton-data resources must reference the exact vanilla skeletons declared in the contract. No copied `.skel`/`.spskel` is allowed in the source tree or PCK.
- The mounted vanilla skeletons must match their exact v0.111.0 versions, contain the lowercase `default` skin, and satisfy the animation/slot/event names in `ironclad-skin.contract.json`.
- `.spatlas` JSON, atlas page dimensions/rotated bounds, private resource references, all 19 PNG IHDR dimensions, scene bindings, and the exported PCK layout are checked as well.
- The source root is limited to the 30 contracted logical files plus matching Godot `.import`/`.uid` artifacts; the PCK private root likewise rejects any extra entry.
- `project.godot` keeps `.tres`/`.tscn` resources textual during export. The PCK phase rejects converted/remapped wrappers and inspects their payloads to prove the vanilla skeleton and private-atlas references survived packaging.

The source phase first runs Godot import, then mounts `SlayTheSpire2.pck`
without overriding Mod files and loads the four skeleton-data resources through
the game's own Spine GDExtension. Validator-only extension files are installed
under the ignored `bin/spine_contract/<content-hash>/` directory and are
excluded from the PCK.

Normal `dotnet build` invokes both source and post-export PCK phases automatically. For a manual source check from this directory:

`Export-ModPck.ps1` writes a unique staging PCK beside the requested output,
checks that it is fresh and non-empty, runs the PCK phase, and only then
replaces the previous output. Failed exports leave the last validated PCK in
place and do not run the DLL/manifest copy target.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Validate-IroncladSkin.ps1 `
  -ProjectDir . -Phase Source -GodotExe $GodotExe -Sts2Dir $Sts2Dir
```

To inspect a produced pack:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Validate-IroncladSkin.ps1 `
  -ProjectDir . -Phase Pck -PckPath .\Vivhite.pck
```

The PCK phase rejects `tools`, `bin`, `.work`, `vanilla`, copied `.skel`/`.spskel`
files, and every approved original Ironclad replacement prefix.
