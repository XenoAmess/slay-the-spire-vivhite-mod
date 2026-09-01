# Ironclad skin contract tools

`Validate-IroncladSkin.ps1` is the build gate for the optional bundle at
`res://Vivhite/skins/ironclad`.

候选输出的集合索引见 [`candidates/README.md`](candidates/README.md)。候选目录只用于离线研究，
不会因为存在 `.spjson` 或 PNG 就自动进入正式运行时资源。

- A missing bundle, or a bundle containing only `README.md`/`.gitkeep`, is inactive and does not block normal builds.
- Once any real file (or `.enabled`) exists, all 26 logical runtime assets are required before Spine semantic checks begin.
- Every skeleton-data resource must reference a Mod-private Spine 4.2.43 `.spjson`. Combat and merchant share White Qi's combat JSON, atlas, and page; rest-site and character-select use their own private JSON/atlas sets. Character-select owns its atlas regions instead of inheriting the Ironclad layout. Original Ironclad skeleton references and copied `.skel`/`.spskel` are rejected in both the source tree and PCK.
- The private skeletons must contain the lowercase `default` skin and satisfy the animation/slot/event names in `ironclad-skin.contract.json`. Character-select has `exactAnimations: true`, because its `NSpineAutoPlayer` parent contract requires exactly the single animation `animation`.
- `.spatlas` JSON, atlas page dimensions/rotated bounds, private resource references, all 12 PNG IHDR dimensions, scene bindings, and the exported PCK layout are checked as well.
- Private scenes may contain a `SpineSprite`, but may not serialize editor-preview `SpineMesh2D` children; every runtime mesh must be reconstructed from the private `.spjson`.
- The source root is limited to the 26 contracted logical files plus matching Godot `.import`/`.uid` artifacts; the PCK private root likewise rejects any extra entry.
- `project.godot` keeps `.spjson`/`.spatlas`/`.tres`/`.tscn` resources textual during export. The PCK phase inspects their payloads to prove private skeleton/atlas references survived packaging and that no original Ironclad path returned.

The source phase first runs Godot import, then mounts `SlayTheSpire2.pck`
without overriding Mod files and loads the four private skeleton-data resources
through the game's own Spine GDExtension. Validator-only extension files are installed
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
