# third_party — 上游依赖说明

## STS2-Agent（CharTyr/STS2-Agent，AGPL-3.0-only）

- **上游**：https://github.com/CharTyr/STS2-Agent
- **基线版本**：v0.9.0（release zip 由 `scripts/Deploy-Mod.ps1` 自动下载到 `dist/`，不入库）
- **当前部署的是带本地补丁的源码构建**，补丁见 `STS2-Agent-v0.9.0-aoe-potion-fix.patch`：

  `use_potion` 对 AoE/随机目标药水（如爆炸药瓶 EXPLOSIVE_AMPOULE）永远 pending：
  `ResolvePotionTarget` 对 `AllEnemies/AllAllies/RandomEnemy` 错误地返回 `Owner.Creature`，
  游戏静默丢弃非法目标。补丁让这三类返回 `null`（游戏内部自行解析全体目标）。

### 如何复现这个构建

```powershell
git clone https://github.com/CharTyr/STS2-Agent.git
cd STS2-Agent; git checkout v0.9.0
git apply <本目录>/STS2-Agent-v0.9.0-aoe-potion-fix.patch
$env:DOTNET_ROOT = "C:\Users\xenoa\AppData\Local\Microsoft\dotnet"   # 本机 SDK 位置
$env:PATH = "$env:DOTNET_ROOT;$env:PATH"
$env:STS2_DATA_DIR = "G:\SteamLibrary\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64"
.\scripts\build-mod.ps1 -Configuration Release -GameRoot "G:\SteamLibrary\steamapps\common\Slay the Spire 2" -GodotExe "<Godot 4.5.1 mono 路径>"
```

- 注意：`-GameRoot` 只管部署；csproj 的程序集引用路径由环境变量 `STS2_DATA_DIR` 提供
- 该补丁已验证：`use_potion` 对 AoE 药水返回 completed，敌人全体扣血
- 若上游修复了此问题，直接切回官方 release 即可（Deploy-Mod.ps1）
