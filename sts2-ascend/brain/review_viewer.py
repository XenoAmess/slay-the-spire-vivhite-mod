"""ASCEND-VISION —— sts2-ascend 实时决策与复盘驾驶舱（赛博青蓝）。

独立常驻进程，由大脑的 dashboard supervisor 拉起/自愈；也可手动运行：

  py brain/review_viewer.py                     # 自动模式：游戏状态驱动 LIVE/TREND/REVIEW
  py brain/review_viewer.py --demo              # 组合演示：实时决策 + 多行复盘流
  py brain/review_viewer.py --attach-current    # 捞取模式：只读轮询 opencode.db 最近的复盘会话
  py brain/review_viewer.py --interactive       # 1/2/3 切页，0 自动，可拖拽/ESC关闭

设计约束：
  - 纯标准库（tkinter + ctypes + sqlite3），零 pip 依赖；
  - 业务数据只读：snapshot / stats / stream / opencode.db（mode=ro）；仅写
    session 范围的 viewer lock/PID 与有界诊断日志；
  - 任何异常自吞退出，绝不影响复盘与大脑主循环。
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import random
import re
import sqlite3
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from lifecycle import (RUNTIME_DIR, SESSION_ID, STACK_ROOT, pid_file,
                       stop_requested, viewer_launch_disabled)
from window_layers import reassert_viewer_topmost

try:
    from floor_stats import FloorStatsProvider
except Exception:  # stats are optional to the crash-isolated viewer
    FloorStatsProvider = None

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")   # opencode 偶尔漏出的 ANSI 转义

BASE_DIR = STACK_ROOT
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
STREAM_FILE = KNOWLEDGE_DIR / "review_live.stream"
LOCK_FILE = KNOWLEDGE_DIR / "viewer.lock"
OPENCODE_DB = Path(os.path.expanduser("~/.local/share/opencode/opencode.db"))

# ---- 赛博青蓝配色 ----
BG = "#030b14"
FG = "#b8f0ff"            # 正文冰蓝
CYAN = "#00e5ff"          # 主青
CYAN_DIM = "#0891b2"
CYAN_DARK = "#164e63"
MAGENTA = "#ff2ea6"       # 工具调用
GOLD = "#ffd166"          # 关键事件 / 结束
RED = "#ff4d5e"           # 错误
DIM = "#5b7a8d"           # 弱化（推理/统计行）
RAIN_CHARS = "アイウエオカキクケコサシスセソ0123456789ﾊﾋﾌﾍﾎ<>*+=-"

WIN_W = 400
LINE_H = 16
MAX_LINES = 500
END_LINGER_SEC = 30       # 直播/演示：结束后停留秒数再淡出
ATTACH_LINGER_SEC = 600   # 捞取回放：已结束的会话多留 10 分钟（人要看）
FADE_SEC = 2.0
VIEWER_Z_ORDER_INTERVAL_SEC = 0.5
DASHBOARD_SCHEMA = "sts2.ascend-live/v1"
DASHBOARD_STALE_SEC = 5.0
DECISION_ANIMATION_SEC = 0.65
DECISION_FRESH_SEC = 20.0
VIEW_PAGES = ("LIVE", "TREND", "REVIEW")


def dashboard_path(runtime_dir: Path | None = None, session_id: str | None = None) -> Path:
    root = Path(runtime_dir) if runtime_dir is not None else RUNTIME_DIR
    sid = SESSION_ID if session_id is None else (str(session_id).strip() or "legacy")
    return root / f"live_dashboard.{sid}.json"


# ---------------------------------------------------------------------------
# 单实例锁
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    """OpenProcess + 映像名校验。仅凭 OpenProcess 成功判活会被 pid 复用毒锁：
    锁 pid 被无关进程复用时误判"活着"→ 单实例锁永久锁死（悬浮窗消失事故）。"""
    if pid <= 0:
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = ctypes.c_ulong(512)
            k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                       ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return "python" in buf.value.lower()
            return True   # 映像名拿不到（权限等）：保守视为活
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


LOCK_STALE_SEC = 15


def acquire_lock() -> bool:
    """心跳锁：持有者每 5s 触摸锁文件（mtime 即生命信号），mtime 超过
    LOCK_STALE_SEC 视为死锁接管。pid/映像名判活在 python 进程生态里会被
    pid 复用反复毒锁（悬浮窗消失事故：锁 pid 被自家 python 复用 → 永久锁死）。"""
    for _ in range(3):
        try:
            if LOCK_FILE.exists():
                age = time.time() - LOCK_FILE.stat().st_mtime
                if age < LOCK_STALE_SEC:
                    return False
                LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            return False
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode())
            finally:
                os.close(fd)
            return True
        except OSError:
            time.sleep(0.2)
    return False


def release_lock() -> None:
    try:
        if int(LOCK_FILE.read_text(encoding="utf-8").strip() or "0") == os.getpid():
            LOCK_FILE.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# 内容源
# ---------------------------------------------------------------------------

class StreamSource:
    """直播：tail review_live.stream，处理截断与哨兵行。"""

    def __init__(self) -> None:
        self.offset = 0

    def poll(self) -> list[str]:
        try:
            size = STREAM_FILE.stat().st_size
            if size < self.offset:      # 文件被截断（新一场复盘）
                self.offset = 0
            if size == self.offset:
                return []
            with STREAM_FILE.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self.offset)
                data = f.read()
                self.offset = f.tell()
            return [_ANSI_RE.sub("", ln) for ln in data.splitlines()]
        except OSError:
            return []


class DashboardSource:
    """Read the session-scoped latest-wins dashboard snapshot.

    A producer publishes by atomic replacement.  The viewer validates the
    schema and keeps the last good value when a partial/corrupt file is ever
    observed (for example while an antivirus delays the final rename).
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or dashboard_path()
        self.last_mtime_ns = -1
        self.last_good: dict = {}
        self.last_seq: object = None
        self.last_poll = 0.0
        self.last_error = ""

    def poll(self, now: float | None = None, *, force: bool = False) -> tuple[dict, bool]:
        wall_now = time.time() if now is None else now
        if not force and wall_now - self.last_poll < 0.10:
            return self.snapshot(wall_now), False
        self.last_poll = wall_now
        changed = False
        try:
            stat = self.path.stat()
            if force or stat.st_mtime_ns != self.last_mtime_ns:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or payload.get("schema") != DASHBOARD_SCHEMA:
                    raise ValueError("unsupported live dashboard schema")
                if not isinstance(payload.get("run", {}), dict):
                    raise ValueError("dashboard run must be an object")
                if not isinstance(payload.get("decision", {}), dict):
                    raise ValueError("dashboard decision must be an object")
                seq = payload.get("revision", payload.get("seq"))
                changed = seq != self.last_seq or payload != self.last_good
                self.last_seq = seq
                self.last_good = payload
                self.last_mtime_ns = stat.st_mtime_ns
                self.last_error = ""
        except FileNotFoundError:
            self.last_error = "waiting"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
        return self.snapshot(wall_now), changed

    def snapshot(self, now: float | None = None) -> dict:
        payload = dict(self.last_good)
        wall_now = time.time() if now is None else now
        try:
            age = max(0.0, wall_now - self.path.stat().st_mtime)
        except OSError:
            age = float("inf")
        payload["_stale"] = age > DASHBOARD_STALE_SEC
        payload["_age"] = age
        payload["_error"] = self.last_error
        return payload


class StatsSource:
    """Refresh floor history off the Tk thread and expose immutable snapshots."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._current: dict | None = None
        self._snapshot: dict = {}
        self._revision = 0
        self._seen_revision = -1
        self._provider = None
        if FloorStatsProvider is not None:
            try:
                self._provider = FloorStatsProvider(
                    KNOWLEDGE_DIR,
                    refresh_interval=1.0,
                    recent_window=20,
                    comparison_window=20,
                    trend_window=40,
                    rolling_window=5,
                )
            except Exception:
                self._provider = None
        self._thread = None
        if self._provider is not None:
            self._thread = threading.Thread(
                target=self._run, name="ascend-viewer-stats", daemon=True
            )
            self._thread.start()

    def set_current(self, current: dict | None) -> None:
        normalized = dict(current) if isinstance(current, dict) else None
        with self._lock:
            if normalized != self._current:
                self._current = normalized
                self._wake.set()

    def _run(self) -> None:
        while not stop_requested():
            try:
                with self._lock:
                    current = dict(self._current) if self._current else None
                result = self._provider.snapshot(current=current)
                if isinstance(result, dict):
                    with self._lock:
                        if result != self._snapshot:
                            self._snapshot = result
                            self._revision += 1
            except Exception:
                pass
            self._wake.wait(1.0)
            self._wake.clear()

    def poll(self) -> tuple[dict, bool]:
        with self._lock:
            result = dict(self._snapshot)
            revision = self._revision
        changed = revision != self._seen_revision
        self._seen_revision = revision
        return result, changed

    def close(self) -> None:
        self._wake.set()


class DbSource:
    """捞取：只读轮询 opencode.db 中最近一场 sts2-ascend 复盘会话的 parts。"""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id
        self.last_ts = 0
        self.meta: dict = {}
        self.ended = False

    def _connect(self) -> sqlite3.Connection:
        path = str(OPENCODE_DB).replace("\\", "/")
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def poll(self) -> list[tuple[str, str]]:
        """返回 [(style, text)]。style: body/reasoning/tool/patch/stats。"""
        out: list[tuple[str, str]] = []
        try:
            db = self._connect()
            try:
                if not self.session_id:
                    row = db.execute(
                        "SELECT id, title, model, time_created FROM session "
                        "WHERE title LIKE 'sts2-ascend%复盘%' ORDER BY time_created DESC LIMIT 1").fetchone()
                    if not row:
                        if not getattr(self, "_warned", False):
                            self._warned = True
                            return [("stats", "未找到复盘会话…")]
                        return []
                    self.session_id = row[0]
                    self.meta = {"title": row[1], "model": row[2], "time_created": row[3]}
                    # 跳过 user 提示词（几万字的数据包不属于"推理过程"），从 assistant 输出开始播
                    db2 = db.execute(
                        "SELECT m.time_created FROM part p JOIN message m ON p.message_id = m.id "
                        "WHERE p.session_id=? AND json_extract(m.data, '$.role') != 'user' "
                        "ORDER BY m.time_created LIMIT 1", (self.session_id,)).fetchone()
                    if db2 and db2[0]:
                        self.last_ts = db2[0] - 1
                rows = db.execute(
                    "SELECT time_created, data FROM part WHERE session_id=? AND time_created>? "
                    "ORDER BY time_created", (self.session_id, self.last_ts)).fetchall()
                for ts, raw in rows:
                    self.last_ts = max(self.last_ts, ts)
                    try:
                        d = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    ptype = d.get("type")
                    if ptype == "text" and d.get("text"):
                        out.append(("body", d["text"]))
                    elif ptype == "reasoning" and d.get("text"):
                        out.append(("reasoning", "💭 " + d["text"]))
                    elif ptype == "tool":
                        name = d.get("tool") or d.get("name") or "tool"
                        brief = json.dumps(d.get("input") or d.get("args") or {}, ensure_ascii=False)[:120]
                        out.append(("tool", f"⚙ {name} {brief}"))
                    elif ptype == "patch":
                        files = d.get("files") or []
                        out.append(("patch", "📦 修改 " + ", ".join(str(f).split("/")[-1] for f in files)))
                    elif ptype == "step-finish":
                        tok = (d.get("tokens") or {}).get("total")
                        if d.get("reason") == "stop":
                            self.ended = True
                        if tok:
                            out.append(("stats", f"· tokens {tok} ·"))
                return out
            finally:
                db.close()
        except (sqlite3.Error, OSError):
            return []


DEMO_SCRIPT = [
    (0.2, "meta", {"model": "opencode-go/glm-5.3-flash", "source": "preferred", "run": 18, "time": "2026-08-22 12:30"}),
    (0.6, "body", "读取 knowledge/stats.json … 17 局 0 胜，当前进阶 0"),
    (0.9, "reasoning", "💭 先定位主要死因：普通战 attrition 比精英更致命"),
    (0.8, "tool", "⚙ read sts2-ascend/knowledge/stats.json"),
    (0.7, "body", "分析卡组膨胀问题：最佳局 29 牌，输出密度不足"),
    (1.0, "tool", "⚙ edit sts2-ascend/brain/policy.py"),
    (0.8, "body", "block_safety_margin 1.60 → 1.70：致死战普遍差 1 张防御"),
    (0.6, "patch", "📦 修改 policy.py, lessons.md"),
    (0.7, "reasoning", "💭 需要跑自检确认没有改坏…"),
    (0.9, "tool", "⚙ bash py -3 sts2-ascend/brain/selfcheck.py"),
    (1.2, "gold", "SELFCHECK OK"),
    (0.5, "body", "复盘完成。总结：收敛卡组、优先格挡线、继续探索事件。"),
    (0.4, "stats", "· tokens 49140 ·"),
    (0.3, "end", {"exit": 0}),
]


# ---------------------------------------------------------------------------
# 悬浮窗
# ---------------------------------------------------------------------------

class Viewer:
    def __init__(self, mode: str, interactive: bool = False) -> None:
        self.mode = mode
        self.interactive = interactive
        self.start_time = time.time()
        self.lines: list[tuple[str, str]] = []        # (text, style) 已折行
        self.reveal = 0.0                              # 打字机揭示进度（字符）
        self.total_chars = 0
        self.run_no: int | None = None
        self.model_name = "—"
        self.ended = False
        self.end_at: float | None = None
        self.flash_until = 0.0
        self.rain_pulse = 1.0
        self._drag = None
        self._viewer_hwnd = 0
        self._last_viewer_reassert = 0.0
        self.dashboard_source = DashboardSource()
        self.stats_source = StatsSource()
        self.dashboard: dict = self._demo_dashboard() if mode == "demo" else {}
        self.floor_stats: dict = {}
        self._dash_dirty = True
        self._review_dirty = True
        self._decision_key: object = None
        self._decision_signature = ""
        self._decision_seen_at = 0.0
        self._decision_anim_at = time.time()
        self._last_dashboard_render = 0.0
        self._view_page = "REVIEW"
        self._manual_page: str | None = None

        self.source = None
        if mode == "demo":
            self._demo_idx = 0
            self._demo_next = time.time() + 0.5
        elif mode == "attach":
            self.source = DbSource()
        else:
            self.source = StreamSource()

        self._boot("init-start")
        self._build_ui()
        self._boot("ui-built")
        self._build_rain()
        self._boot("init-done")

    @staticmethod
    def _demo_dashboard() -> dict:
        return {
            "schema": DASHBOARD_SCHEMA,
            "session_id": "demo",
            "seq": 42,
            "revision": 42,
            "heartbeat": time.time(),
            "connection": {"status": "online", "message": "API 8080"},
            "run": {
                "run_id": "DEMO", "run_number": 657, "ascension": 0,
                "floor": 18, "turn": 3, "hp": 37, "max_hp": 68,
                "gold": 112, "screen": "COMBAT",
            },
            "decision": {
                "decision_id": "demo-42", "status": "proposed", "repeat_count": 1,
                "observation": "敌方下回合预计造成 18 点伤害，手牌可提供 16 点格挡。",
                "gates": [
                    {"label": "动作合法性", "status": "pass", "value": "3/3"},
                    {"label": "生存闸门", "status": "pass", "value": "预计掉血 2"},
                ],
                "candidates": [
                    {"label": "打出白绫防御", "score": 18.4, "status": "chosen",
                     "why": "保留生命并触发绫势"},
                    {"label": "打出白绫打击", "score": 12.1, "status": "rejected",
                     "why": "无法完成斩杀"},
                    {"label": "结束回合", "score": None, "status": "rejected",
                     "why": "会承受过量伤害"},
                ],
                "selected": {"action": "play_card", "label": "白绫防御 → 自身",
                             "reason": "先满足生存线，再保留下一回合输出。"},
                "explanation": ["当前没有斩杀线。", "格挡方案把预计掉血压到 2。",
                                "攻击候选因生存闸门被淘汰。"],
                "outcome": {"status": "pending", "message": "等待游戏回执"},
            },
            "history": [
                {"status": "applied", "label": "使用药水", "reason": "补足斩杀"},
                {"status": "applied", "label": "白绫打击", "reason": "最高净伤害"},
            ],
            "_stale": False,
        }

    def _boot(self, msg: str) -> None:
        """启动轨迹：卡死定位用（py-spy 不支持 3.14 抓不了栈）。"""
        try:
            with (KNOWLEDGE_DIR / "viewer_boot.log").open("a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] pid={os.getpid()} {msg}\n")
        except OSError:
            pass

    # ----- UI 构建 -----
    def _build_ui(self) -> None:
        r = tk.Tk()
        self.root = r
        self._boot("tk-created")
        r.title("ASCEND-VISION")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.attributes("-alpha", 0.92)
        r.configure(bg=BG)
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        self.win_h = min(760, sh - 120)
        r.geometry(f"{WIN_W}x{self.win_h}+{sw - WIN_W - 24}+48")

        self.canvas = tk.Canvas(r, width=WIN_W, height=self.win_h, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        # 边框 + 衬底（画一次即可，canvas 底部层级）
        self.canvas.create_rectangle(1, 1, WIN_W - 1, self.win_h - 1,
                                     outline=CYAN_DIM, width=2)
        self.canvas.create_rectangle(4, 4, WIN_W - 4, 62, fill="#061423",
                                     outline=CYAN_DARK)
        self.font = tkfont.Font(family="Consolas", size=10)
        self.font_bold = tkfont.Font(family="Consolas", size=10, weight="bold")
        self.font_hud = tkfont.Font(family="Consolas", size=12, weight="bold")
        self.font_dim = tkfont.Font(family="Consolas", size=9, slant="italic")
        self.font_tiny = tkfont.Font(family="Microsoft YaHei UI", size=8)
        self.font_card = tkfont.Font(family="Microsoft YaHei UI", size=10, weight="bold")

        if self.interactive:
            self.canvas.bind("<Button-1>", lambda e: setattr(self, "_drag", (e.x, e.y)))
            self.canvas.bind("<B1-Motion>", self._on_drag)
            r.bind("<Escape>", lambda _e: self._quit())
            for key, page in (("1", "LIVE"), ("l", "LIVE"),
                              ("2", "TREND"), ("t", "TREND"),
                              ("3", "REVIEW"), ("r", "REVIEW")):
                r.bind(f"<KeyPress-{key}>",
                       lambda _e, value=page: self._set_manual_page(value))
            r.bind("<KeyPress-0>", lambda _e: self._set_manual_page(None))
            r.bind("<KeyPress-a>", lambda _e: self._set_manual_page(None))
            r.bind("<Tab>", self._cycle_manual_page)
        elif not hasattr(self, "_hwnd_prev"):
            # Capture the game (or whatever was active) before Tk maps the
            # popup.  Mapping an overrideredirect window can activate it, so
            # taking the snapshot afterwards would only remember ourselves.
            try:
                self._hwnd_prev = ctypes.windll.user32.GetForegroundWindow()
            except Exception:
                self._hwnd_prev = 0
        r.update()
        self._boot("ui-mapped")
        if self.interactive:
            r.after(50, r.focus_force)
        else:
            self._make_focus_invisible()
            self._set_clickthrough()
            self.root.after(150, self._restore_previous_focus)
        self._reassert_viewer_topmost(force=True)

    def _make_focus_invisible(self) -> None:
        """悬浮窗纯覆盖、永不抢激活：WS_EX_NOACTIVATE。

        Tk overrideredirect 窗口（WS_POPUP）映射时默认抢激活——全屏游戏被踢出
        独占、任务栏盖到游戏上（右侧栏事故）。必须在映射（update）前打上样式。"""
        try:
            u32 = ctypes.windll.user32
            if not getattr(self, "_hwnd_prev", 0):
                self._hwnd_prev = u32.GetForegroundWindow()
            hwnd = int(self.root.wm_frame(), 16)
            gwl_exstyle = -20
            ws_ex_noactivate = 0x08000000
            style = u32.GetWindowLongPtrW(hwnd, gwl_exstyle)
            u32.SetWindowLongPtrW(hwnd, gwl_exstyle, style | ws_ex_noactivate)
        except Exception:
            self._hwnd_prev = 0

    def _restore_previous_focus(self) -> None:
        """把焦点还给建窗前的前台窗口（ALT 技巧绕过 SetForegroundWindow 前台锁）。"""
        try:
            u32 = ctypes.windll.user32
            hwnd_prev = getattr(self, "_hwnd_prev", 0)
            if hwnd_prev and u32.IsWindow(hwnd_prev):
                u32.keybd_event(0x12, 0, 0, 0)          # ALT down
                u32.SetForegroundWindow(hwnd_prev)
                u32.keybd_event(0x12, 0, 2, 0)          # ALT up
        except Exception:
            pass
        finally:
            # Restoring the game's focus can also move it ahead of the viewer
            # in the TOPMOST band. Repair only the z-order; never reactivate
            # ASCEND-VISION here.
            self._reassert_viewer_topmost(force=True)

    def _on_drag(self, e) -> None:
        if self._drag:
            x = self.root.winfo_x() + e.x - self._drag[0]
            y = self.root.winfo_y() + e.y - self._drag[1]
            self.root.geometry(f"+{x}+{y}")

    def _set_manual_page(self, page: str | None) -> None:
        self._manual_page = page if page in VIEW_PAGES else None
        self._dash_dirty = True
        self._review_dirty = True

    def _cycle_manual_page(self, _event=None) -> str:
        choices = (None,) + VIEW_PAGES
        try:
            index = choices.index(self._manual_page)
        except ValueError:
            index = 0
        self._set_manual_page(choices[(index + 1) % len(choices)])
        return "break"

    def _set_clickthrough(self) -> None:
        try:
            hwnd = int(self.root.wm_frame(), 16)
            gwl_exstyle = -20
            ws_ex_layered = 0x00080000
            ws_ex_transparent = 0x00000020
            u32 = ctypes.windll.user32
            style = u32.GetWindowLongPtrW(hwnd, gwl_exstyle)
            u32.SetWindowLongPtrW(hwnd, gwl_exstyle, style | ws_ex_layered | ws_ex_transparent)
        except Exception:
            pass

    # ----- 数字雨 -----
    def _build_rain(self) -> None:
        self.rain_cols = []
        # Keep animation on the frame edges.  A full-width rain curtain makes
        # small graphs and score labels shimmer on a game capture.
        xs = (7, 18, 30, 42, WIN_W - 42, WIN_W - 30, WIN_W - 18, WIN_W - 7)
        for x in xs:
            col = {
                "x": x, "y": random.uniform(-self.win_h, 0),
                "speed": random.uniform(60, 200), "trail": random.randint(6, 11),
                "items": [],
            }
            for j in range(col["trail"]):
                item = self.canvas.create_text(x, -50, text="", font=self.font_dim)
                col["items"].append(item)
            self.rain_cols.append(col)

    def _update_rain(self, dt: float) -> None:
        if self.rain_pulse > 1.0:
            self.rain_pulse = max(1.0, self.rain_pulse - dt * 1.5)
        for col in self.rain_cols:
            col["y"] += col["speed"] * self.rain_pulse * dt
            if col["y"] - col["trail"] * LINE_H > self.win_h:
                col["y"] = random.uniform(-200, -20)
                col["speed"] = random.uniform(60, 200)
            for j, item in enumerate(col["items"]):
                y = col["y"] - j * LINE_H
                if y < -20 or y > self.win_h + 20:
                    self.canvas.itemconfig(item, text="")
                    continue
                if random.random() < 0.08:
                    ch = random.choice(RAIN_CHARS)
                    self.canvas.itemconfig(item, text=ch)
                self.canvas.coords(item, col["x"], y)
                if j == 0:
                    color = CYAN
                elif j < 3:
                    color = CYAN_DIM
                else:
                    color = CYAN_DARK
                self.canvas.itemconfig(item, fill=color)

    # ----- 内容摄入 -----
    def add_text(self, text: str, style: str = "body") -> None:
        added = False
        for raw in text.splitlines():
            for seg in self._wrap(raw):
                if not seg.strip():
                    continue  # 纯空白行直接忽略（否则会不停追加空行，观感怪异）
                self.lines.append((seg, style))
                self.total_chars += len(seg)
                added = True
        self.lines = self.lines[-MAX_LINES:]
        if added:
            self.rain_pulse = 2.4
            self._review_dirty = True
        low = text.lower()
        if "selfcheck ok" in low:
            self.flash_until = time.time() + 0.8

    def _wrap(self, s: str) -> list[str]:
        max_px = WIN_W - 24
        if not s:
            return [s]
        # 字符宽度缓存：逐字 measure 一次，O(n) 完成折行（启动大量灌入时不卡）
        wcache = getattr(self, "_char_w", None)
        if wcache is None:
            wcache = self._char_w = {}

        def w_of(ch: str) -> int:
            w = wcache.get(ch)
            if w is None:
                w = self.font.measure(ch)
                wcache[ch] = w
            return w

        out, cur, cur_w = [], "", 0
        for ch in s:
            cw = w_of(ch)
            if cur_w + cw > max_px and cur:
                out.append(cur)
                cur, cur_w = ch, cw
            else:
                cur += ch
                cur_w += cw
        out.append(cur)
        return out

    # ----- 帧循环 -----
    def _frame(self) -> None:
        if stop_requested():
            self._quit()
            return
        now = time.time()
        dt = 0.033
        self._reassert_viewer_topmost()
        if not getattr(self, "_boot_f1", False):
            self._boot_f1 = True
            self._boot("frame-first")
        if self.mode != "demo" and now - getattr(self, "_last_beat", 0) > 5:
            self._last_beat = now
            try:
                owner = int(LOCK_FILE.read_text(encoding="utf-8").strip() or "0")
                if owner != os.getpid():
                    self._quit()
                    return
                LOCK_FILE.touch()      # 心跳：mtime 即生命信号（心跳锁）
            except (OSError, ValueError):
                self._quit()
                return
        try:
            self._poll_source(now)
            self._poll_dashboard(now)
            self._update_rain(dt)
            page = "REVIEW" if self.mode == "attach" else self._select_view_mode(now)
            if page != self._view_page:
                self._view_page = page
                self._dash_dirty = True
                self._review_dirty = True
                self.canvas.delete("dash" if page == "REVIEW" else "txt")
                self.canvas.delete("review")
            if page == "REVIEW":
                self.canvas.delete("dash")
                self.canvas.delete("review")
                self._render_text(dt, now)
            elif page == "TREND":
                self.canvas.delete("txt")
                self._render_trend_page(now)
            else:
                self.canvas.delete("txt")
                self._render_dashboard(now)
            self._render_hud(now)
            self._check_end(now)
        except Exception as exc:
            self._debug_exc(exc)
            self._reassert_viewer_topmost(force=True)
        if self._fading:
            t = (now - self._fade_start) / FADE_SEC
            if t >= 1.0:
                self._quit()
                return
            self.root.attributes("-alpha", max(0.0, 0.92 * (1 - t)))
        self.root.after(33, self._frame)

    def _poll_dashboard(self, now: float) -> None:
        if self.mode == "demo":
            dash_changed = False
        else:
            snapshot, dash_changed = self.dashboard_source.poll(now)
            if snapshot:
                self.dashboard = snapshot
        run = self.dashboard.get("run") if isinstance(self.dashboard, dict) else None
        self.stats_source.set_current(run if isinstance(run, dict) else None)
        stats, stats_changed = self.stats_source.poll()
        if stats:
            self.floor_stats = stats
        if self.mode == "demo" and not self.floor_stats:
            self.floor_stats = {
                "stale": False,
                "lifetime": {"runs": 656, "wins": 0, "win_rate": 0.0,
                             "mean_floor": 17.6, "best_floor": 40},
                "recent": {"window": 20, "count": 20, "mean_floor": 20.4,
                           "best_floor": 38},
                "previous": {"window": 20, "count": 20, "mean_floor": 17.1,
                             "best_floor": 31},
                "delta_mean": 3.3,
                "trend": [
                    {"run_number": 618 + i, "floor": floor,
                     "rolling_mean": sum([12, 15, 19, 17, 22, 18, 25, 21, 27, 24,
                                          28, 19, 31, 26, 33, 29, 35, 30, 38, 34][max(0, i-4):i+1])
                                     / min(5, i + 1)}
                    for i, floor in enumerate(
                        [12, 15, 19, 17, 22, 18, 25, 21, 27, 24,
                         28, 19, 31, 26, 33, 29, 35, 30, 38, 34]
                    )
                ],
                "current": dict(run or {}),
            }
            stats_changed = True
        decision = self.dashboard.get("decision", {}) if isinstance(self.dashboard, dict) else {}
        key = decision.get("decision_id") if isinstance(decision, dict) else None
        try:
            signature = json.dumps(decision, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")) if decision else ""
        except (TypeError, ValueError):
            signature = repr(decision)
        if signature and signature != self._decision_signature:
            self._decision_signature = signature
            self._decision_seen_at = now
            dash_changed = True
        # revision distinguishes a status/outcome update of the same decision;
        # the full animation restarts only for a genuinely new choice.
        if key != self._decision_key:
            self._decision_key = key
            self._decision_anim_at = now
            dash_changed = True
        if dash_changed or stats_changed:
            self._dash_dirty = True

    def _select_view_mode(self, now: float | None = None) -> str:
        """Choose a page from game state, never from a presentation timer.

        The freshness guard performs one fail-safe transition to REVIEW when a
        producer stops advancing; it is not a rotating slideshow.
        """
        if self.interactive and self._manual_page in VIEW_PAGES:
            return self._manual_page
        wall_now = time.time() if now is None else now
        dash = self.dashboard if isinstance(self.dashboard, dict) else {}
        run = dash.get("run") if isinstance(dash.get("run"), dict) else {}
        decision = dash.get("decision") if isinstance(dash.get("decision"), dict) else {}
        screen = str(run.get("screen") or "UNKNOWN").upper()
        if screen in {"GAME_OVER", "VICTORY", "RUN_COMPLETE"}:
            return "TREND"
        passive = {
            "UNKNOWN", "WAITING", "MAIN_MENU", "TITLE", "CHARACTER_SELECT",
            "PROFILE_SELECT", "RUN_HISTORY", "CREDITS",
        }
        # Demo is a stable visual fixture: keep its combined LIVE page visible
        # until an interactive user explicitly selects another page.  Production
        # still falls back to REVIEW when the telemetry producer stops advancing.
        fresh = (not dash.get("_stale") and bool(decision.get("decision_id"))
                 and (getattr(self, "mode", "live") == "demo"
                      or wall_now - self._decision_seen_at <= DECISION_FRESH_SEC))
        if screen not in passive and fresh:
            return "LIVE"
        return "REVIEW"

    def _debug_exc(self, exc: Exception) -> None:
        """帧内异常兜底：记录到 viewer_exc.log，绝不让 viewer 崩溃影响复盘。"""
        try:
            p = KNOWLEDGE_DIR / "viewer_exc.log"
            if p.exists() and p.stat().st_size > 20000:
                return
            import traceback
            with p.open("a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(exc))[-1500:] + "\n---\n")
        except Exception:
            pass

    _fading = False
    _fade_start = 0.0

    def _poll_source(self, now: float) -> None:
        if self.mode == "demo":
            if self._demo_idx < len(DEMO_SCRIPT) and now >= self._demo_next:
                delay, kind, payload = DEMO_SCRIPT[self._demo_idx]
                self._demo_next = now + delay
                self._demo_idx += 1
                if kind == "meta":
                    self.model_name = payload.get("model", "?")
                    self.run_no = payload.get("run")
                elif kind == "end":
                    self._begin_end(now)
                else:
                    self.add_text(payload, kind)
            return
        if self.source is None:
            return
        if isinstance(self.source, StreamSource):
            for ln in self.source.poll():
                if ln.startswith("[LIVE-START] "):
                    try:
                        meta = json.loads(ln[len("[LIVE-START] "):])
                        self.model_name = meta.get("model", "?")
                        self.run_no = meta.get("run")
                        self.start_time = now
                        self.lines.clear()
                        self.reveal = 0.0
                        self._review_dirty = True
                        self.ended = False        # 新复盘开始：清结束横幅，继续直播
                        self.end_at = None
                    except json.JSONDecodeError:
                        pass
                elif ln.startswith("[LIVE-END] "):
                    self._begin_end(now)
                else:
                    self.add_text(ln, self._classify(ln))
        elif isinstance(self.source, DbSource):
            if self.source.meta and self.model_name == "—":
                m = self.source.meta
                raw_model = str(m.get("model") or "?")
                try:
                    raw_model = json.loads(raw_model).get("id", raw_model)
                except (json.JSONDecodeError, AttributeError):
                    pass
                self.model_name = raw_model
                tc = m.get("time_created")
                if tc:
                    age = time.time() - tc / 1000
                    if 0 < age < 6 * 3600:
                        self.start_time = time.time() - age
                    # 时钟偏移或会话太旧：保持查看器启动时刻，避免 T+ 显示失真
            for style, text in self.source.poll():
                self.add_text(text, style)
            if self.source.ended:
                self._begin_end(now)

    @staticmethod
    def _classify(ln: str) -> str:
        low = ln.lower()
        if "selfcheck ok" in low:
            return "gold"
        if any(k in low for k in ("error", "traceback", "失败", "exception")):
            return "error"
        if ln.lstrip().startswith(("$", ">", "●", "✓")) or "edit(" in low or "bash(" in low:
            return "tool"
        if ".py" in low or ".json" in low or ".md" in low:
            return "path"
        return "body"

    def _render_text(self, dt: float, now: float) -> None:
        total = sum(len(t) for t, _ in self.lines)
        if total == 0:
            self.canvas.delete("txt")
            return
        # 追加滚动式：最后一行之前的所有内容瞬时上屏（老行只往上顶、不被改写），
        # 打字机动画只作用于最新一行——终端式观感。
        last_len = len(self.lines[-1][0])
        floor = float(total - last_len)
        if self.reveal < floor:
            self.reveal = floor
        self.reveal = min(float(total), self.reveal + 220.0 * dt)

        self.canvas.delete("txt")
        max_visible = (self.win_h - 130) // LINE_H   # 顶部 HUD(~78px) + 底部横幅(~50px) 避让
        visible = self.lines[-max_visible:]
        base = total - sum(len(t) for t, _ in visible)   # 可见区之前的字符数
        y0 = 78
        acc = base
        for i, (text, style) in enumerate(visible):
            shown = int(max(0, min(len(text), self.reveal - acc)))
            acc += len(text)
            if shown <= 0:
                break
            y = y0 + i * LINE_H
            color, font = self._style_of(style, now)
            # 深色衬底提升游戏画面上的可读性
            self.canvas.create_text(10, y + 1, anchor="nw", text=text[:shown],
                                    fill=BG, font=font, tags="txt")
            self.canvas.create_text(10, y, anchor="nw", text=text[:shown],
                                    fill=color, font=font, tags="txt")
        # 光标
        self.canvas.create_text(10, y0 + len(visible) * LINE_H + 2, anchor="nw",
                                text="▌", fill=CYAN, font=self.font_bold, tags="txt")

    @staticmethod
    def _metric(value: object, decimals: int = 1) -> str:
        if value is None or isinstance(value, bool):
            return "—"
        try:
            number = float(value)
            if not math.isfinite(number):
                return "—"
            if decimals <= 0 or number.is_integer():
                return str(int(number))
            return f"{number:.{decimals}f}"
        except (TypeError, ValueError):
            return "—"

    @staticmethod
    def _one_line(value: object, limit: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text if len(text) <= limit else text[:max(1, limit - 1)] + "…"

    @staticmethod
    def _status_color(status: object) -> str:
        key = str(status or "").lower()
        if key in {"pass", "chosen", "selected", "applied", "online", "connected", "ok", "success"}:
            return CYAN
        if key in {"pending", "proposed", "waiting", "wait", "starting", "reconnecting",
                   "reconciling", "uncertain", "warn"}:
            return GOLD
        if key in {"reject", "rejected", "failed", "error", "offline", "disconnected",
                   "retrying", "locked"}:
            return RED
        return DIM

    def _draw_card(self, x: int, y: int, width: int, label: str,
                   value: str, accent: str = CYAN) -> None:
        c = self.canvas
        c.create_rectangle(x, y, x + width, y + 39, fill="#061827",
                           outline=CYAN_DARK, tags="dash")
        c.create_rectangle(x, y, x + 3, y + 39, fill=accent,
                           outline=accent, tags="dash")
        c.create_text(x + 10, y + 4, anchor="nw", text=label, fill=DIM,
                      font=self.font_tiny, tags="dash")
        c.create_text(x + 10, y + 18, anchor="nw", text=value, fill=FG,
                      font=self.font_card, tags="dash")

    def _draw_trend(self, stats: dict, *, top: int = 177, bottom: int = 470) -> None:
        c = self.canvas
        x0, x1, y0, y1 = 14, WIN_W - 14, top + 23, bottom - 8
        c.create_rectangle(7, top, WIN_W - 7, bottom, fill="#04111e",
                           outline=CYAN_DARK, tags="dash")
        trend = stats.get("trend") if isinstance(stats, dict) else None
        trend = [row for row in (trend or []) if isinstance(row, dict)
                 and isinstance(row.get("floor"), (int, float))][-40:]
        current = stats.get("current") if isinstance(stats, dict) else None
        c.create_text(14, top + 4, anchor="nw", text=f"FLOOR TREND · 最近 {len(trend)} 局",
                      fill=CYAN, font=self.font_tiny, tags="dash")
        if not trend:
            c.create_text(WIN_W // 2, (top + bottom) // 2, anchor="center",
                          text="等待有效完结局数据",
                          fill=DIM, font=self.font_dim, tags="dash")
            return
        floors = [float(row["floor"]) for row in trend]
        life = stats.get("lifetime") or {}
        references = floors + [float(value) for value in
                               (life.get("mean_floor"), life.get("best_floor"))
                               if isinstance(value, (int, float))]
        if isinstance(current, dict) and isinstance(current.get("floor"), (int, float)):
            references.append(float(current["floor"]))
        ymax = max(1.0, max(references, default=1.0))

        def py(value: float) -> float:
            return y1 - (max(0.0, min(ymax, value)) / ymax) * (y1 - y0)

        for fraction in (0.0, 0.5, 1.0):
            gy = y1 - fraction * (y1 - y0)
            c.create_line(x0, gy, x1, gy, fill="#0b2638", tags="dash")
        mean = life.get("mean_floor")
        if isinstance(mean, (int, float)):
            c.create_line(x0, py(float(mean)), x1, py(float(mean)), fill=DIM,
                          dash=(3, 3), tags="dash")
        best = life.get("best_floor")
        if isinstance(best, (int, float)):
            c.create_line(x0, py(float(best)), x1, py(float(best)), fill="#7c6330",
                          dash=(5, 4), tags="dash")
        span = max(1, len(trend) - 1)
        raw_points: list[float] = []
        roll_points: list[float] = []
        for index, row in enumerate(trend):
            x = x0 + (x1 - x0 - 10) * index / span
            raw_points.extend((x, py(float(row["floor"]))))
            rolling = row.get("rolling_mean")
            if isinstance(rolling, (int, float)):
                roll_points.extend((x, py(float(rolling))))
        if len(raw_points) >= 4:
            c.create_line(*raw_points, fill=CYAN_DIM, width=1, tags="dash")
        for index in range(0, len(raw_points), 2):
            c.create_oval(raw_points[index] - 1.5, raw_points[index + 1] - 1.5,
                          raw_points[index] + 1.5, raw_points[index + 1] + 1.5,
                          fill=CYAN, outline="", tags="dash")
        if len(roll_points) >= 4:
            c.create_line(*roll_points, fill=MAGENTA, width=2, smooth=True, tags="dash")
        if isinstance(current, dict) and isinstance(current.get("floor"), (int, float)):
            live_x, live_y = x1, py(float(current["floor"]))
            c.create_line(raw_points[-2], raw_points[-1], live_x, live_y,
                          fill=GOLD, dash=(2, 2), tags="dash")
            c.create_oval(live_x - 4, live_y - 4, live_x + 4, live_y + 4,
                          outline=GOLD, width=2, tags="dash")
            c.create_text(live_x - 2, max(y0, live_y - 13), anchor="e", text="LIVE",
                          fill=GOLD, font=self.font_tiny, tags="dash")

    def _render_dashboard(self, now: float) -> None:
        animating = now - self._decision_anim_at < DECISION_ANIMATION_SEC
        if not self._dash_dirty and not animating:
            self._render_review_panel(now, 517, 714, title="LIVE REVIEW · 连续复盘流")
            return
        self._dash_dirty = False
        self._last_dashboard_render = now
        c = self.canvas
        c.delete("dash")
        dash = self.dashboard if isinstance(self.dashboard, dict) else {}
        stats = self.floor_stats if isinstance(self.floor_stats, dict) else {}
        life = stats.get("lifetime") or {}
        recent = stats.get("recent") or {}
        recent_count = int(recent.get("count") or 0)
        recent_label = f"近{recent_count}局均层" if recent_count else "近期均层"
        recent_best_label = f"近{recent_count}局最高" if recent_count else "近期最高"
        delta = stats.get("delta_mean")
        delta_txt, delta_color = "", DIM
        if isinstance(delta, (int, float)):
            delta_txt = f"  {'▲' if delta > 1 else '▼' if delta < -1 else '≈'} {delta:+.1f}"
            delta_color = CYAN if delta > 1 else RED if delta < -1 else DIM
        self._draw_card(7, 68, 190, "历史平均楼层", self._metric(life.get("mean_floor")))
        self._draw_card(203, 68, 190, recent_label,
                        self._metric(recent.get("mean_floor")) + delta_txt, delta_color)
        self._draw_card(7, 111, 190, "历史最高楼层",
                        "F" + self._metric(life.get("best_floor"), 0), GOLD)
        self._draw_card(203, 111, 190, recent_best_label,
                        "F" + self._metric(recent.get("best_floor"), 0), MAGENTA)
        run = dash.get("run") if isinstance(dash.get("run"), dict) else {}
        current_floor, recent_mean = run.get("floor"), recent.get("mean_floor")
        versus = "—"
        if isinstance(current_floor, (int, float)) and isinstance(recent_mean, (int, float)):
            versus = f"{current_floor - recent_mean:+.1f}F"
        win_rate = life.get("win_rate")
        rate = win_rate * 100 if isinstance(win_rate, (int, float)) and win_rate <= 1 else win_rate
        stale_mark = " · STALE" if stats.get("stale") else ""
        c.create_text(12, 157, anchor="nw",
                      text=(f"有效局 {self._metric(life.get('runs'), 0)} · 胜率 {self._metric(rate)}%"
                            f" · A{self._metric(run.get('ascension'), 0)} · 本局较近期 {versus}{stale_mark}"),
                      fill=DIM, font=self.font_tiny, tags="dash")
        c.create_text(12, 178, anchor="nw",
                      text="LIVE DECISION · 实时策略与执行机械链",
                      fill=CYAN_DIM, font=self.font_tiny, tags="dash")

        decision = dash.get("decision") if isinstance(dash.get("decision"), dict) else {}
        stages = ("SCAN", "GATE", "RANK", "LOCK", "ACK")
        stage_index = min(4, int(max(0.0, now - self._decision_anim_at)
                                 / (DECISION_ANIMATION_SEC / len(stages))))
        for index, label in enumerate(stages):
            x = 8 + index * 78
            if index < stage_index:
                fill, outline, fg = "#083243", CYAN_DIM, CYAN
            elif index == stage_index:
                fill, outline, fg = "#193542", GOLD, GOLD
            else:
                fill, outline, fg = "#071520", CYAN_DARK, DIM
            c.create_rectangle(x, 193, x + 67, 219, fill=fill, outline=outline,
                               width=1, tags="dash")
            c.create_text(x + 33, 206, anchor="center", text=label, fill=fg,
                          font=self.font_tiny, tags="dash")
            if index < 4:
                c.create_text(x + 72, 206, anchor="center", text="›", fill=CYAN_DIM,
                              font=self.font_bold, tags="dash")

        c.create_rectangle(7, 226, WIN_W - 7, 417, fill="#04111e",
                           outline=CYAN_DARK, tags="dash")
        screen = str(run.get("screen") or "WAITING").upper()
        context = (f"{screen} · F{self._metric(run.get('floor'), 0)}"
                   f" T{self._metric(run.get('turn'), 0)} · "
                   f"HP {self._metric(run.get('hp'), 0)}/{self._metric(run.get('max_hp'), 0)}"
                   f" · G {self._metric(run.get('gold'), 0)}")
        c.create_text(14, 232, anchor="nw", text=context, fill=CYAN,
                      font=self.font_tiny, tags="dash")
        observation_value = decision.get("observation")
        if isinstance(observation_value, dict):
            facts = observation_value.get("facts")
            if isinstance(facts, list) and facts:
                observation_value = " · ".join(str(item) for item in facts)
            else:
                observation_value = observation_value.get("title")
        observation = self._one_line(observation_value or "等待实时局面…", 49)
        c.create_text(14, 251, anchor="nw", text="OBS  " + observation, fill=FG,
                      font=self.font_tiny, tags="dash")
        gates = [gate for gate in (decision.get("gates") or []) if isinstance(gate, dict)][:2]
        if gates:
            for index, gate in enumerate(gates):
                color = self._status_color(gate.get("status"))
                passed = str(gate.get("status") or "").lower() == "pass"
                text = (f"{'●' if passed else '◆'} {self._one_line(gate.get('label'), 14)}  "
                        f"{self._one_line(gate.get('value'), 24)}")
                c.create_text(14, 272 + index * 17, anchor="nw", text=text,
                              fill=color, font=self.font_tiny, tags="dash")
        else:
            c.create_text(14, 272, anchor="nw", text="◇ 规则直达 · 无候选评分",
                          fill=DIM, font=self.font_tiny, tags="dash")
        candidates = [row for row in (decision.get("candidates") or [])
                      if isinstance(row, dict)]
        visible_candidates = candidates[:3]
        c.create_text(14, 309, anchor="nw", text="RANK  候选动作",
                      fill=MAGENTA, font=self.font_tiny, tags="dash")
        for index, row in enumerate(visible_candidates):
            status = row.get("status")
            chosen = str(status or "").lower() in {"chosen", "selected"}
            color = GOLD if chosen else self._status_color(status)
            score = self._metric(row.get("score"))
            prefix = "▶" if chosen else f"{index + 1}."
            text = (f"{prefix} {self._one_line(row.get('label'), 18):<18} "
                    f"S:{score:<5} {self._one_line(row.get('why'), 18)}")
            c.create_text(14, 327 + index * 19, anchor="nw", text=text,
                          fill=color, font=self.font_tiny, tags="dash")
        if len(candidates) > 3:
            c.create_text(WIN_W - 14, 309, anchor="ne", text=f"+{len(candidates) - 3}",
                          fill=DIM, font=self.font_tiny, tags="dash")
        if not visible_candidates:
            c.create_text(14, 329, anchor="nw", text="— 本次为规则直达动作 —",
                          fill=DIM, font=self.font_tiny, tags="dash")
        selected = decision.get("selected") if isinstance(decision.get("selected"), dict) else {}
        outcome = decision.get("outcome") if isinstance(decision.get("outcome"), dict) else {}
        selected_label = selected.get("label") or selected.get("action") or "等待选择"
        outcome_status = outcome.get("status") or decision.get("status") or "waiting"
        c.create_rectangle(11, 389, WIN_W - 11, 411, fill="#10202a",
                           outline=self._status_color(outcome_status), tags="dash")
        c.create_text(17, 393, anchor="nw",
                      text=(f"LOCK ▶ {self._one_line(selected_label, 27)}  "
                            f"[{str(outcome_status).upper()}]"),
                      fill=self._status_color(outcome_status), font=self.font_tiny,
                      tags="dash")

        c.create_rectangle(7, 422, WIN_W - 7, 511, fill="#061827",
                           outline=CYAN_DARK, tags="dash")
        c.create_text(14, 427, anchor="nw", text="WHY · 为什么这样选？", fill=GOLD,
                      font=self.font_tiny, tags="dash")
        explanation = decision.get("explanation")
        if isinstance(explanation, str):
            explanation = [explanation]
        if not isinstance(explanation, list):
            explanation = []
        if not explanation:
            fallback = selected.get("reason") or outcome.get("message") or observation
            explanation = [fallback] if fallback else ["等待决策证据…"]
        for index, line in enumerate(explanation[:3]):
            c.create_text(16, 448 + index * 19, anchor="nw",
                          text=f"{index + 1:02d}  {self._one_line(line, 46)}",
                          fill=FG if index == 0 else DIM, font=self.font_tiny, tags="dash")

        self.auto_mode = "LIVE"
        self._render_review_panel(now, 517, 714, title="LIVE REVIEW · 连续复盘流")

    def _render_review_panel(self, now: float, top: int, bottom: int, *, title: str) -> None:
        """Render a continuous, styled review stream without touching trace data."""
        total = sum(len(text) for text, _style in self.lines)
        if not self._review_dirty and self.reveal >= total:
            return
        self._review_dirty = False
        c = self.canvas
        c.delete("review")
        c.create_rectangle(7, top, WIN_W - 7, bottom, fill="#030e19",
                           outline=CYAN_DARK, tags="review")
        c.create_text(14, top + 5, anchor="nw",
                      text=f"{title} · {self.model_name}", fill=CYAN_DIM,
                      font=self.font_tiny, tags="review")
        if total <= 0:
            c.create_text(14, top + 30, anchor="nw",
                          text="等待 review_live.stream；决策遥测不会从复盘文本推断",
                          fill=DIM, font=self.font_tiny, tags="review")
            return
        last_len = len(self.lines[-1][0])
        floor = float(total - last_len)
        if self.reveal < floor:
            self.reveal = floor
        self.reveal = min(float(total), self.reveal + 220.0 * 0.033)
        max_visible = max(2, (bottom - top - 30) // LINE_H)
        visible = self.lines[-max_visible:]
        base = total - sum(len(text) for text, _style in visible)
        acc = base
        y0 = top + 25
        for index, (text, style) in enumerate(visible):
            shown = int(max(0, min(len(text), self.reveal - acc)))
            acc += len(text)
            if shown <= 0:
                break
            color, font = self._style_of(style, now)
            y = y0 + index * LINE_H
            c.create_text(13, y + 1, anchor="nw", text=text[:shown], fill=BG,
                          font=font, tags="review")
            c.create_text(13, y, anchor="nw", text=text[:shown], fill=color,
                          font=font, tags="review")
        cursor_y = min(bottom - 16, y0 + len(visible) * LINE_H)
        c.create_text(13, cursor_y, anchor="nw", text="▌", fill=CYAN,
                      font=self.font_bold, tags="review")

    def _render_trend_page(self, now: float) -> None:
        if not self._dash_dirty:
            self._render_review_panel(now, 528, 714, title="LIVE REVIEW · 结算复盘流")
            return
        self._dash_dirty = False
        c = self.canvas
        c.delete("dash")
        dash = self.dashboard if isinstance(self.dashboard, dict) else {}
        stats = self.floor_stats if isinstance(self.floor_stats, dict) else {}
        life = stats.get("lifetime") or {}
        recent = stats.get("recent") or {}
        run = dash.get("run") if isinstance(dash.get("run"), dict) else {}
        recent_count = int(recent.get("count") or 0)
        delta = stats.get("delta_mean")
        delta_txt = f"  {delta:+.1f}" if isinstance(delta, (int, float)) else ""
        self._draw_card(7, 68, 190, "历史平均楼层", self._metric(life.get("mean_floor")))
        self._draw_card(203, 68, 190, f"近{recent_count}局均层" if recent_count else "近期均层",
                        self._metric(recent.get("mean_floor")) + delta_txt,
                        CYAN if isinstance(delta, (int, float)) and delta >= 0 else RED)
        self._draw_card(7, 111, 190, "历史最高楼层",
                        "F" + self._metric(life.get("best_floor"), 0), GOLD)
        self._draw_card(203, 111, 190,
                        f"近{recent_count}局最高" if recent_count else "近期最高",
                        "F" + self._metric(recent.get("best_floor"), 0), MAGENTA)
        c.create_text(12, 157, anchor="nw",
                      text=(f"RUN COMPLETE · #{run.get('run_number') or '—'} · "
                            f"F{self._metric(run.get('floor'), 0)} · "
                            f"有效局 {self._metric(life.get('runs'), 0)}"),
                      fill=GOLD, font=self.font_tiny, tags="dash")
        self._draw_trend(stats, top=177, bottom=474)
        decision = dash.get("decision") if isinstance(dash.get("decision"), dict) else {}
        selected = decision.get("selected") if isinstance(decision.get("selected"), dict) else {}
        outcome = decision.get("outcome") if isinstance(decision.get("outcome"), dict) else {}
        outcome_status = outcome.get("status") or decision.get("status") or "waiting"
        c.create_rectangle(7, 480, WIN_W - 7, 522, fill="#061827",
                           outline=self._status_color(outcome_status), tags="dash")
        c.create_text(14, 486, anchor="nw", text="LAST DECISION",
                      fill=CYAN_DIM, font=self.font_tiny, tags="dash")
        c.create_text(14, 503, anchor="nw",
                      text=(f"{self._one_line(selected.get('label') or selected.get('action'), 30)}"
                            f" · {str(outcome_status).upper()} · "
                            f"{self._one_line(outcome.get('message'), 20)}"),
                      fill=self._status_color(outcome_status), font=self.font_tiny, tags="dash")
        self.auto_mode = "TREND"
        self._render_review_panel(now, 528, 714, title="LIVE REVIEW · 结算复盘流")

    def _style_of(self, style: str, now: float) -> tuple[str, tkfont.Font]:
        if style == "tool":
            return MAGENTA, self.font_bold
        if style == "patch":
            return GOLD, self.font_bold
        if style == "gold":
            return GOLD, self.font_bold
        if style == "error":
            pulse = 0.5 + 0.5 * math.sin(now * 6)
            r = 255
            g = int(0x4d + 0x30 * pulse)
            return f"#{r:02x}{g:02x}{0x5e:02x}", self.font_bold
        if style == "path":
            return "#22d3ee", self.font
        if style in ("reasoning", "stats"):
            return DIM, self.font_dim
        return FG, self.font

    def _volume_label(self, now: float) -> str:
        if now - getattr(self, "_vol_check", 0.0) > 1.0:
            self._vol_check = now
            try:
                d = json.loads((KNOWLEDGE_DIR / "voice_volume.json").read_text(encoding="utf-8"))
                self._vol_label = "🔇" if d.get("muted") else f"🔊 {int(d.get('volume', 100))}%"
            except Exception:
                self._vol_label = ""
        return getattr(self, "_vol_label", "")

    def _render_hud(self, now: float) -> None:
        self.canvas.delete("hud")
        c = self.canvas
        c.create_rectangle(4, 4, WIN_W - 4, 62, fill="#061423",
                           outline=CYAN_DARK, tags="hud")
        c.create_line(0, 64, WIN_W, 64, fill=CYAN_DARK, tags="hud")
        breathe = 0.5 + 0.5 * math.sin(now * 2.2)
        glow = f"#{0x00:02x}{int(0x91 + (0xe5 - 0x91) * breathe):02x}{int(0xb2 + (0xff - 0xb2) * breathe):02x}"
        c.create_text(14, 10, anchor="nw", text="ASCEND-VISION", fill=CYAN_DARK,
                      font=self.font_hud, tags="hud")
        c.create_text(12, 8, anchor="nw", text="ASCEND-VISION", fill=glow,
                      font=self.font_hud, tags="hud")
        if self.mode == "attach":
            run_txt = f"第 {self.run_no} 局" if self.run_no else "待机"
            subline = f"捞取回放 · {run_txt} · {self.model_name}"
            detail = f"T+{int(now - self.start_time) // 60:02d}:{int(now - self.start_time) % 60:02d}"
            state_color = GOLD if self.ended else CYAN
        else:
            dash = self.dashboard if isinstance(self.dashboard, dict) else {}
            run = dash.get("run") if isinstance(dash.get("run"), dict) else {}
            decision = dash.get("decision") if isinstance(dash.get("decision"), dict) else {}
            number = run.get("run_number") or self.run_no
            mode_tag = (("MANUAL/" if self._manual_page else "AUTO/")
                        + self._view_page)
            if self.mode == "demo":
                mode_tag = "DEMO/" + self._view_page
            subline = (f"{mode_tag} · #{number or '—'} · F{self._metric(run.get('floor'), 0)}"
                       f" · {str(run.get('screen') or 'WAITING').upper()}")
            connection = dash.get("connection") if isinstance(dash.get("connection"), dict) else {}
            conn_status = "stale" if dash.get("_stale") else connection.get("status") or "waiting"
            detail = (f"{str(decision.get('status') or 'waiting').upper()} · "
                      f"{self._one_line(connection.get('message') or '等待智能体快照', 28)}")
            state_color = self._status_color(conn_status)
        c.create_text(12, 30, anchor="nw", text=subline,
                      fill=FG, font=self.font, tags="hud")
        c.create_text(12, 47, anchor="nw", text=detail,
                      fill=state_color, font=self.font_tiny, tags="hud")
        vol = self._volume_label(now)
        if vol:
            c.create_text(WIN_W - 76, 47, anchor="nw", text=vol,
                          fill=CYAN, font=self.font_dim, tags="hud")
        ang = (now * 240) % 360
        color = state_color
        c.create_arc(WIN_W - 34, 10, WIN_W - 10, 34, start=ang, extent=110,
                     outline=color, width=3, style="arc", tags="hud")
        if self.ended and self.mode == "attach":
            phase = 0.5 + 0.5 * math.sin(now * 3)
            border = f"#{int(0xb2 + (0xff - 0xb2) * phase):02x}{int(0x8a + (0xd1 - 0x8a) * phase):02x}{0x33:02x}"
            c.create_rectangle(4, 70, WIN_W - 4, self.win_h - 8, outline=border,
                               width=2, tags="hud")
            c.create_text(WIN_W // 2, self.win_h - 34, anchor="center",
                          text="✦ 复盘完成 · 即将继续爬塔 ✦", fill=GOLD,
                          font=self.font_hud, tags="hud")
        if self.mode != "attach":
            footer_y = min(720, self.win_h - 39)
            c.create_rectangle(4, footer_y, WIN_W - 4, self.win_h - 4,
                               fill="#061423", outline=CYAN_DARK, tags="hud")
            stale = bool((self.dashboard or {}).get("_stale"))
            if self.interactive:
                footer = "1 LIVE · 2 TREND · 3 REVIEW · 0 AUTO"
            else:
                footer = ("AUTO · SNAPSHOT STALE · 等待自愈" if stale
                          else "AUTO · TOPMOST · NO-ACTIVATE · CLICK-THROUGH")
            c.create_text(12, footer_y + 10, anchor="nw", text=footer,
                          fill=RED if stale else DIM, font=self.font_tiny, tags="hud")
        # SELFCHECK 金色闪光
        if now < self.flash_until:
            k = max(0.0, min(1.0, (self.flash_until - now) / 0.8))
            flash = f"#{0xff:02x}{0xd1:02x}{int(0x66 * k):02x}"
            c.create_rectangle(0, 64, WIN_W, self.win_h, outline=flash, width=4, tags="hud")

    # ----- 结束流程 -----
    def _begin_end(self, now: float) -> None:
        if not self.ended:
            self.ended = True
            self.end_at = now
            self._dash_dirty = True

    def _check_end(self, now: float) -> None:
        if not self.ended or not self.end_at or self._fading:
            return
        if self.mode == "live":
            return  # 直播模式常驻：复盘结束后停留（横幅+待命），下一场 LIVE-START 自动接续
        linger = ATTACH_LINGER_SEC if self.mode == "attach" else END_LINGER_SEC
        if now - self.end_at > linger:
            self._fading = True
            self._fade_start = now

    def _quit(self) -> None:
        if getattr(self, "_quitting", False):
            return
        self._quitting = True
        self.stats_source.close()
        release_lock()
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    def _reassert_viewer_topmost(self, force: bool = False) -> None:
        """Keep ASCEND-VISION above other TOPMOST windows without activation."""
        now = time.monotonic()
        if not force and now - self._last_viewer_reassert < VIEWER_Z_ORDER_INTERVAL_SEC:
            return
        try:
            hwnd = int(self.root.wm_frame(), 16)
        except (AttributeError, tk.TclError, TypeError, ValueError):
            return
        if not hwnd:
            return
        self._viewer_hwnd = hwnd
        self._last_viewer_reassert = now
        # A failed call is intentionally retried on the next heartbeat. The
        # viewer must never steal focus just to recover from a transient Win32
        # z-order failure.
        reassert_viewer_topmost(hwnd=hwnd)

    def run(self) -> None:
        self._boot("run-entered")
        self.root.after(33, self._frame)
        try:
            self.root.mainloop()
        except Exception:
            pass
        release_lock()


def main() -> None:
    args = set(sys.argv[1:])
    interactive = "--interactive" in args
    if "--demo" in args:
        mode = "demo"
    elif "--attach-current" in args:
        mode = "attach"
    else:
        mode = "live"
    if viewer_launch_disabled():
        return
    try:
        with (KNOWLEDGE_DIR / "viewer_boot.log").open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] pid={os.getpid()} main-entered mode={mode}\n")
    except OSError:
        pass
    if mode != "demo" and not acquire_lock():
        return
    try:
        if mode == "demo":
            Viewer(mode, interactive=interactive).run()
        else:
            with pid_file("viewer"):
                Viewer(mode, interactive=interactive).run()
    except Exception as exc:
        # 尸检日志：viewer 之死必须留痕（此前静默 release，消失无迹可寻）
        try:
            import traceback
            with (KNOWLEDGE_DIR / "viewer_exc.log").open("a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(exc))[-1500:] + "\n===main-exit===\n")
        except OSError:
            pass
        release_lock()


if __name__ == "__main__":
    main()
