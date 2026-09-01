# 白绮 / Ironclad art pipeline

这是白绮 Vivhite 的美术研究、提取、Spine 构建、离线渲染与发布前验收工具集。
这里的脚本属于**制作与证据链**，不是游戏运行时入口；默认不会启动、停止或控制
Slay the Spire 2、Brain、直播或 Steam。正式运行时只消费经过发布器门禁的
`Vivhite/Vivhite/skins/ironclad/` 资源。

![Vivhite workshop preview](../../workshop/preview.jpg)

## 从哪里开始

| 目的 | 入口 | 产物 / 边界 |
| --- | --- | --- |
| 提取游戏研究模板 | [`extract_ironclad_assets.py`](extract_ironclad_assets.py) | 只读读取 v0.111.0 PCK，写入 `assets/ironclad-v0.111.0/` |
| 原生透明生图 | [`evolink_transparent_image.py`](evolink_transparent_image.py) | 仅 EvoLink `gpt-image-2` + `background=transparent`；每次尝试追加归档 |
| Atlas region 主源 | [`atlas_region_tool.gd`](atlas_region_tool.gd) | `assets/vivhite-ironclad/custom/**`；禁止整页重绘与 Alpha 修补 |
| 私有运行时 rig | `build_vivhite_*_rig.gd` | 写正式 runtime 前先在 `candidates/` 或 `.work/` 验收 |
| 候选研究 | [`candidates/README.md`](candidates/README.md) | 所有候选默认 research-only / fail-closed，不得直接部署 |
| 多方案战斗对照 | [`compare/preview/README.md`](compare/preview/README.md) | 使用真实 Spine GDExtension 的隐藏 Vulkan，输出只在 `.work/` |
| 选人、休息、多人 UI 验收 | [`candidates/character_select_acceptance/README.md`](candidates/character_select_acceptance/README.md)、[`candidates/rest_site_acceptance/README.md`](candidates/rest_site_acceptance/README.md)、[`evaluations/multiplayer_gestures/README.md`](evaluations/multiplayer_gestures/README.md) | 离线证据，不改变运行时素材 |
| 发布前镜像与契约 | [`publish_ironclad_skin.py`](publish_ironclad_skin.py) | 只从已验收私有源生成完整运行时资源；随后才允许 `dotnet build` |

## 路径与运行模式（容易混淆的部分）

仓库根目录是所有命令的工作目录。`tools/art` 是一个最小 Godot 项目，而
`Vivhite` 是带游戏扩展与正式资源路径的 Godot .NET 项目：

```text
tools/art/                         # 本地脚本与候选源码（本目录不等于 runtime）
assets/ironclad-v0.111.0/          # 只读、版本化的游戏提取模板
assets/vivhite-ironclad/           # 生成原图、Prompt/请求归档、已验收制作源
Vivhite/tools/candidates/<name>/   # 候选输出；PCK 排除，禁止复制到 skins/
.work/                             # 临时 Vulkan 帧、报告、隔离 stage（可删除/重建）
Vivhite/Vivhite/skins/ironclad/    # 唯一正式运行时资源，由发布器镜像维护
```

因此：

1. **构建器**通常以 `--path tools/art` 启动，脚本会把输出解析到仓库根下的
   `Vivhite/tools/candidates/<name>/`；这两个路径不是同一个目录。
2. 需要读取 `res://tools/candidates/...`、游戏 Spine 类或正式场景的**验证器/渲染器**
   应使用 `--path Vivhite`，或直接使用候选目录提供的 `Invoke-*.ps1` 包装器。
3. 预览输出必须位于仓库 `.work/` 下；包装器会拒绝越界路径并使用新目录，避免
   把旧报告误当成新验收。
4. `Vivhite/tools/candidates/` 中的 `.import`、`.uid` 是 Godot 缓存，不是候选的
   authored 文件；不能提交、发布或拿来判断 Alpha。

## 全局制作与验收闸门

- 新的透明主体只能通过 EvoLink `gpt-image-2` 原生透明响应；不要使用抠图、色键、
  洪水填充、阈值、蒙版或任何代码 Alpha 修补。完整契约见仓库根 [`AGENTS.md`](../../AGENTS.md)。
- 在任何生成调用前，先判断 PNG 是单帧、atlas/spritesheet、tile sheet 还是多区域拼图，
  并同时核对相邻 atlas/Spine 元数据与实际 C#/GDScript 消费者。没有消费者证据时，
  只能记录证据缺口，不能把整页当插画交给模型。
- 每次付费尝试都要在 `assets/vivhite-ironclad/generated/` 追加保存未经后处理原图、
  逐字 Prompt、去秘密的请求参数；同一语义素材最多 8 次，失败候选也不能覆盖或删除。
- Alpha 验收必须程序化读取 RGBA 通道，并分别 SourceOver 到黑、白和接近真实场景的
  底色；四角应为 `Alpha=0`，内部主体应接近不透明。低 Alpha 触边只是需要复核的警告，
  不能单凭黑底缩略图或 `Alpha>0` bbox 判定光晕。
- 候选的“通过”只表示它满足该候选自己的结构/渲染证据，不表示生产资格。只有
  `hybrid_v3_final` 等明确通过完整 Source/Godot/PCK 门禁的资源，才可由发布器写入
  正式 runtime；semantic 灰盒永远保持 `deployable=false`。
- 离线 Vulkan 渲染使用 `WINDOW_FLAG_NO_FOCUS` 和屏幕外位置，且同一项目的 Spine
  扩展由 mutex 串行化。它不会获得 UAC，也不应替代真机验收。

## 常用检查顺序

```powershell
# 1) 仅在需要更新游戏模板时提取（默认不清理任何无关文件）
py -3 -B .\tools\art\extract_ironclad_assets.py

# 2) 构建/验证具体候选；优先使用候选 README 中的包装器
Get-Content .\tools\art\candidates\README.md

# 3) 发布前从私有源镜像并运行正式构建门禁
py -3 -B .\tools\art\publish_ironclad_skin.py
dotnet build .\Vivhite\Vivhite.csproj

# 4) 仅运行 Python 静态契约测试（不会启动游戏）
py -3 -B -m unittest discover -s .\tools\art\tests -p 'test_*.py' -v
```

如果某一步失败，先保存 `.work/` 中的完整 stdout/stderr、JSON 报告和输入哈希，
再修复源或消费者契约；不要通过 `--allow-unchanged`、复制旧 `.import` 或手工修改
候选 JSON 绕过门禁。`--allow-unchanged` 只允许写入 `.work/` 的调查目录。

## EvoLink native-transparent image generation

Every new transparent Vivhite asset must use EvoLink `gpt-image-2` with
`background=transparent`. No green-screen, chroma-key, background-removal, or
alternate image service is permitted. `evolink_transparent_image.py` keeps the
API key out of arguments and files, submits the fixed transparent request, and
verifies that the downloaded result is a PNG.

Set `EVOLINK_API_KEY` in the current process environment or in the Windows user
environment. The tool checks both without printing the value; on other systems,
or when neither is configured, it falls back to an interactive hidden prompt:

```powershell
py -3 -B .\tools\art\evolink_transparent_image.py `
  --prompt-file .\.work\evolink-prompts\next-asset.txt `
  --output .\assets\vivhite-ironclad\generated\evolink-paid\2026-08-28\next-asset-attempt-01\output.png `
  --image-url https://example.invalid/reference-1.png `
  --image-url https://example.invalid/reference-2.jpg
```

If generation finishes but download is interrupted, reuse its task without
creating or billing another image:

```powershell
py -3 -B .\tools\art\evolink_transparent_image.py `
  --task-id task-unified-example `
  --output .\assets\vivhite-ironclad\generated\evolink-paid\2026-08-28\next-asset-attempt-01\output.png
```

Resume must use the same output path as the original attempt. The tool refuses
to resume when the matching `.prompt.txt` or sanitized `.request.json` is
missing, and records the non-secret task id in a `.task.json` sidecar as soon as
EvoLink accepts a request. This keeps a timed-out paid task recoverable without
allowing resume mode to bypass the append-only archive contract.

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
1.0s, and `die` 2.3333335s. Its attack/heavy/cast events occur at 0.08s,
0.12s, and 0.25s respectively. Each attack event now coincides with its hand
impulse and arc attachment. `NIroncladVfx` holds the ordinary arc for 0.15s
before a 0.20s fade and fades the heavy arc continuously over 0.35s; the
heavier animation also uses a larger torso, arm, root, and arc impulse.
`relaxed_loop` is closed at its 12-second boundary so the merchant may enter
at any phase without a visible pop.

The combat scene retains the original `Visuals/NIroncladVfx`,
`Visuals/SlashVfxSlot`, and `Visuals/EyeSlot/EyeFire` chain, runtime-facing
shader step parameters, and layout anchors while binding only the private
skeleton. `SlashVfxSlot` uses a pass-through canvas shader that exposes the
parameters expected by `NIroncladVfx` but deliberately does not reuse the
Ironclad slash shape mask: that mask clips the wide private ribbon into opaque
purple blobs in the real game even though the bare Spine preview is correct.
The runtime `step.x` tween is consumed as an overall Alpha fade, so interrupted
animations cannot leave an opaque ribbon behind while the authored silhouette
remains intact.
The generated
magic ribbon is attached directly to required slot `slash_mesh`, so the
Spine slot consumer and the private arc share one hand anchor instead of
drawing detached or doubled weapon-like geometry. Its consumer
material preserves the ribbon's authored violet/indigo/cyan and gold pixels.
The merchant's
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
