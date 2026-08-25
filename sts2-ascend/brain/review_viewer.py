"""ASCEND-VISION —— sts2-ascend 复盘直播悬浮窗（赛博青蓝）。

独立进程，由 brain/llm_review.py 在启动大模型复盘时拉起；也可手动运行：

  py brain/review_viewer.py                     # 直播模式：tail knowledge/review_live.stream
  py brain/review_viewer.py --demo              # 演示模式：内置假数据，随时看特效
  py brain/review_viewer.py --attach-current    # 捞取模式：只读轮询 opencode.db 最近的复盘会话
  py brain/review_viewer.py --interactive       # 可交互（关闭点击穿透，可拖拽/ESC关闭）

设计约束：
  - 纯标准库（tkinter + ctypes + sqlite3），零 pip 依赖；
  - 只读：stream 文件 / opencode.db（mode=ro）/ 不写任何东西（viewer.lock 除外）；
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
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")   # opencode 偶尔漏出的 ANSI 转义

BASE_DIR = Path(__file__).resolve().parent.parent
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
        h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = ctypes.c_ulong(512)
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
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
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
    (0.2, "meta", {"model": "openrouter/stealth/ox-alpha", "source": "preferred", "run": 18, "time": "2026-08-22 12:30"}),
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

        self.source = None
        if mode == "demo":
            self._demo_idx = 0
            self._demo_next = time.time() + 0.5
        elif mode == "attach":
            self.source = DbSource()
        else:
            self.source = StreamSource()

        self._build_ui()
        self._build_rain()

    # ----- UI 构建 -----
    def _build_ui(self) -> None:
        r = tk.Tk()
        self.root = r
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

        if self.interactive:
            self.canvas.bind("<Button-1>", lambda e: setattr(self, "_drag", (e.x, e.y)))
            self.canvas.bind("<B1-Motion>", self._on_drag)
            r.bind("<Escape>", lambda _e: self._quit())
        r.update()
        if not self.interactive:
            self._make_focus_invisible()
            self._set_clickthrough()
            self.root.after(150, self._restore_previous_focus)

    def _make_focus_invisible(self) -> None:
        """悬浮窗纯覆盖、永不抢激活：WS_EX_NOACTIVATE。

        Tk overrideredirect 窗口（WS_POPUP）映射时默认抢激活——全屏游戏被踢出
        独占、任务栏盖到游戏上（右侧栏事故）。必须在映射（update）前打上样式。"""
        try:
            u32 = ctypes.windll.user32
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

    def _on_drag(self, e) -> None:
        if self._drag:
            x = self.root.winfo_x() + e.x - self._drag[0]
            y = self.root.winfo_y() + e.y - self._drag[1]
            self.root.geometry(f"+{x}+{y}")

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
        n = max(12, WIN_W // 14)
        for i in range(n):
            x = int((i + 0.5) * WIN_W / n)
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
        now = time.time()
        dt = 0.033
        if now - getattr(self, "_last_beat", 0) > 5:
            self._last_beat = now
            try:
                LOCK_FILE.touch()      # 心跳：mtime 即生命信号（心跳锁）
            except OSError:
                pass
        try:
            self._poll_source(now)
            self._update_rain(dt)
            self._render_text(dt, now)
            self._render_hud(now)
            self._check_end(now)
        except Exception as exc:
            self._debug_exc(exc)
        if self._fading:
            t = (now - self._fade_start) / FADE_SEC
            if t >= 1.0:
                self._quit()
                return
            self.root.attributes("-alpha", max(0.0, 0.92 * (1 - t)))
        self.root.after(33, self._frame)

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
        # 顶部分隔线
        c.create_line(0, 64, WIN_W, 64, fill=CYAN_DARK, tags="hud")
        # 呼吸辉光模型名
        breathe = 0.5 + 0.5 * math.sin(now * 2.2)
        glow = f"#{0x00:02x}{int(0x91 + (0xe5 - 0x91) * breathe):02x}{int(0xb2 + (0xff - 0xb2) * breathe):02x}"
        c.create_text(14, 10, anchor="nw", text="ASCEND-VISION", fill=CYAN_DARK,
                      font=self.font_hud, tags="hud")
        c.create_text(12, 8, anchor="nw", text="ASCEND-VISION", fill=glow,
                      font=self.font_hud, tags="hud")
        mode_tag = {"demo": "演示", "attach": "捞取回放", "live": "直播"}.get(self.mode, "直播")
        run_txt = f"第 {self.run_no} 局" if self.run_no else "待机"
        c.create_text(12, 30, anchor="nw",
                      text=f"{mode_tag} · {run_txt} · {self.model_name}",
                      fill=FG, font=self.font, tags="hud")
        elapsed = int(now - self.start_time)
        c.create_text(12, 46, anchor="nw",
                      text=f"T+{elapsed // 60:02d}:{elapsed % 60:02d} · {self.total_chars} chars",
                      fill=DIM, font=self.font_dim, tags="hud")
        vol = self._volume_label(now)
        if vol:
            c.create_text(WIN_W - 46, 40, anchor="nw", text=vol,
                          fill=CYAN, font=self.font_dim, tags="hud")
        # 旋转弧线 Loader（结束后变金）
        ang = (now * 240) % 360
        color = GOLD if self.ended else CYAN
        c.create_arc(WIN_W - 34, 10, WIN_W - 10, 34, start=ang, extent=110,
                     outline=color, width=3, style="arc", tags="hud")
        # 结束横幅
        if self.ended:
            phase = 0.5 + 0.5 * math.sin(now * 3)
            border = f"#{int(0xb2 + (0xff - 0xb2) * phase):02x}{int(0x8a + (0xd1 - 0x8a) * phase):02x}{0x33:02x}"
            c.create_rectangle(4, 70, WIN_W - 4, self.win_h - 8, outline=border,
                               width=2, tags="hud")
            c.create_text(WIN_W // 2, self.win_h - 34, anchor="center",
                          text="✦ 复盘完成 · 即将继续爬塔 ✦", fill=GOLD,
                          font=self.font_hud, tags="hud")
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
        release_lock()
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def run(self) -> None:
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
    if mode != "demo" and not acquire_lock():
        return
    try:
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
