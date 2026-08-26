# Ironclad skin contract tools

`Validate-IroncladSkin.ps1` is the build gate for the optional bundle at
`res://Vivhite/skins/ironclad`.

- A missing bundle, or a bundle containing only `README.md`/`.gitkeep`, is inactive and does not block normal builds.
- Once any real file (or `.enabled`) exists, all 33 logical runtime assets are required before Spine semantic checks begin.
- Production assets must be binary Spine `4.2.43`, contain the lowercase `default` skin, and satisfy the animation/slot/event names in `ironclad-skin.contract.json`.
- `.spatlas` JSON, page names, private resource references, PNG signatures, scene bindings, and the exported PCK layout are checked as well.

The source phase first runs Godot import, then loads the four skeleton-data resources through the game's own Spine GDExtension. Validator-only extension files are installed under the ignored `bin/spine_contract/<content-hash>/` directory and are excluded from the PCK.

Normal `dotnet build` invokes both source and post-export PCK phases automatically. For a manual source check from this directory:

`Export-ModPck.ps1` writes a unique staging PCK beside the requested output,
checks that it is fresh and non-empty, runs the PCK phase, and only then
replaces the previous output. Failed exports leave the last validated PCK in
place and do not run the DLL/manifest copy target.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Validate-IroncladSkin.ps1 `
  -ProjectDir . -Phase Source -GodotExe $GodotExe -Sts2Dir $Sts2Dir
```

For read-only validation of the extracted vanilla templates before they are uniformly re-exported as Spine 4.2.43, add `-AllowExtractedTemplateVersions`. MSBuild never enables this compatibility switch.

To inspect a produced pack:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Validate-IroncladSkin.ps1 `
  -ProjectDir . -Phase Pck -PckPath .\Vivhite.pck
```

The PCK phase rejects `tools`, `bin`, `.work`, `vanilla`, and every approved original Ironclad replacement prefix.
