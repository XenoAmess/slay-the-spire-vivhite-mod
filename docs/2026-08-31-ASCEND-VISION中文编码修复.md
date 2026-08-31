# ASCEND-VISION 中文编码修复

## 现象与定位

`live_dashboard.<SESSION_ID>.json` 的发布器原本使用 `ensure_ascii=False` 后编码为无 BOM 的 UTF-8。文件字节可以通过严格 UTF-8 校验，Python viewer 也显式按 UTF-8 读取；但 Windows PowerShell 5.1 等依赖 BOM 自动判断编码的读取端会把文件按当前 ANSI 代码页解释，导致 `observation`、`reason` 等中文显示为乱码。

同一份故障现场文件的对照证据：

- `Get-Content -Encoding UTF8`：`对局结束：失败（层数 15）…`
- `Get-Content` 默认读取：`瀵瑰眬缁撴潫锛氬け璐…`
- 严格 UTF-8 字节解码成功，说明中文不是在决策对象或 JSON 序列化前被破坏；失配发生在无签名 UTF-8 文件与 Windows 自动编码读取的边界。

## 修复

- 发布器将本地 JSON 快照编码改为 `utf-8-sig`，保留 `ensure_ascii=False`，因此文件中仍是可读的中文原文，同时 Windows 可可靠识别 UTF-8。
- viewer 改用 `utf-8-sig` 读取；该编码同时兼容历史无 BOM UTF-8 快照，不尝试猜测或修复已经乱码的历史字符串。
- 没有修改 `agent.py`、策略逻辑或历史运行数据。

## 验证

- `tests.test_live_dashboard`：验证 BOM、JSON 内中文原文，以及 observation、selected reason、explanation 的逐字往返。
- `tests.test_dashboard_viewer`：验证带签名中文快照进入 viewer 后保持原文，并由既有测试继续覆盖历史无签名 UTF-8 快照。

针对性结果：发布器 10 项通过，viewer 29 项通过。
